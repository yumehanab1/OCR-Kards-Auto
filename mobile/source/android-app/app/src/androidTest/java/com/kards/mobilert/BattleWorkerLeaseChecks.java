package com.kards.mobilert;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Tests real process ownership with fake tokens only; never touches a device API. */
final class BattleWorkerLeaseChecks {
    private final JSONArray checks = new JSONArray();
    private int failures;

    static JSONObject run() throws Exception {
        BattleWorkerLeaseChecks test = new BattleWorkerLeaseChecks();
        if (BattleWorkerLease.isOwned()) {
            test.check("suite_requires_no_existing_worker", false);
            return test.result();
        }
        test.identityAndRestart();
        test.concurrentClaim();
        test.boundLiveWorker();
        test.terminatedWorkerRecovery();
        test.ownerFinallyRelease();
        test.startDiagnostics();
        return test.result();
    }

    private void identityAndRestart() throws Exception {
        // Deliberately equal values in distinct objects expose equals-vs-identity mistakes.
        Object oldOwner = new String("same session label");
        Object impostor = new String("same session label");
        Object replacement = new Object();
        try {
            boolean refusedNull = false;
            try { BattleWorkerLease.tryClaim(null); }
            catch (IllegalArgumentException expected) { refusedNull = true; }
            check("null_owner_cannot_claim", refusedNull && !BattleWorkerLease.isOwned());
            check("first_session_claims", BattleWorkerLease.tryClaim(oldOwner));
            check("same_token_cannot_start_second_worker", !BattleWorkerLease.tryClaim(oldOwner));
            check("replacement_service_waits_for_old_worker", !BattleWorkerLease.tryClaim(replacement));
            check("equal_but_distinct_token_cannot_release", !BattleWorkerLease.release(impostor));
            check("null_token_cannot_release", !BattleWorkerLease.release(null));
            check("ownership_remains_until_exact_worker_exits", BattleWorkerLease.isOwnedBy(oldOwner)
                    && !BattleWorkerLease.isOwnedBy(impostor));
            check("worker_finally_releases", BattleWorkerLease.release(oldOwner) && !BattleWorkerLease.isOwned());
            check("replacement_claims_after_worker_exit", BattleWorkerLease.tryClaim(replacement));
            check("late_old_callback_cannot_release_new_session", !BattleWorkerLease.release(oldOwner)
                    && BattleWorkerLease.isOwnedBy(replacement));
            check("release_is_not_reentrant", BattleWorkerLease.release(replacement)
                    && !BattleWorkerLease.release(replacement) && !BattleWorkerLease.isOwned());
        } finally {
            BattleWorkerLease.release(oldOwner);
            BattleWorkerLease.release(replacement);
        }
    }

    private void concurrentClaim() throws Exception {
        final int contenders = 12;
        CountDownLatch ready = new CountDownLatch(contenders);
        CountDownLatch start = new CountDownLatch(1);
        CountDownLatch done = new CountDownLatch(contenders);
        AtomicInteger accepted = new AtomicInteger();
        AtomicReference<Object> winner = new AtomicReference<>();
        AtomicReference<Throwable> failure = new AtomicReference<>();
        Object[] owners = new Object[contenders];
        Thread[] threads = new Thread[contenders];
        for (int i = 0; i < contenders; i++) {
            final Object candidate = owners[i] = new Object();
            threads[i] = new Thread(() -> {
                ready.countDown();
                try {
                    if (!start.await(5, TimeUnit.SECONDS)) throw new IllegalStateException("claim start timeout");
                    if (BattleWorkerLease.tryClaim(candidate)) {
                        accepted.incrementAndGet();
                        winner.set(candidate);
                    }
                } catch (Throwable error) { failure.compareAndSet(null, error); }
                finally { done.countDown(); }
            }, "battle-lease-test-" + i);
            threads[i].start();
        }
        try {
            check("all_competing_threads_ready", ready.await(5, TimeUnit.SECONDS));
            start.countDown();
            check("all_competing_claims_return", done.await(5, TimeUnit.SECONDS));
            check("concurrent_claims_do_not_throw", failure.get() == null);
            check("exactly_one_process_owner", accepted.get() == 1
                    && winner.get() != null && BattleWorkerLease.isOwnedBy(winner.get()));
            boolean outsidersCannotRelease = true;
            for (Object candidate : owners) if (candidate != winner.get()) {
                outsidersCannotRelease &= !BattleWorkerLease.release(candidate);
            }
            check("losing_callbacks_cannot_release_winner", outsidersCannotRelease
                    && BattleWorkerLease.isOwnedBy(winner.get()));
        } finally {
            start.countDown();
            for (Thread thread : threads) thread.join(5000);
            // These tokens belong only to this test; never clear an unrelated lease.
            for (Object candidate : owners) BattleWorkerLease.release(candidate);
        }
        check("concurrency_test_leaves_no_worker", !BattleWorkerLease.isOwned());
    }

    private void boundLiveWorker() throws Exception {
        Object owner = new Object();
        Object other = new Object();
        CountDownLatch running = new CountDownLatch(1);
        CountDownLatch finish = new CountDownLatch(1);
        Thread worker = new Thread(() -> {
            running.countDown();
            try { finish.await(); }
            catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
        }, "lease-blocked-live");
        try {
            check("unbound_owner_claims", BattleWorkerLease.tryClaim(owner, "live-session"));
            check("unbound_owner_is_not_reclaimed", BattleWorkerLease.snapshot().isOwned()
                    && !BattleWorkerLease.tryClaim(other));
            check("other_token_cannot_bind_worker", !BattleWorkerLease.bindWorker(other, worker));
            check("null_worker_cannot_bind", !BattleWorkerLease.bindWorker(owner, null));
            check("owner_binds_new_worker_once", BattleWorkerLease.bindWorker(owner, worker)
                    && !BattleWorkerLease.bindWorker(owner, new Thread()));
            BattleWorkerLease.Snapshot beforeStart = BattleWorkerLease.snapshot();
            check("new_thread_is_reserved_not_dead", "NEW".equals(beforeStart.workerState)
                    && beforeStart.isOwned() && !BattleWorkerLease.tryClaim(other));
            worker.start();
            check("bound_worker_reaches_wait", running.await(5, TimeUnit.SECONDS));
            BattleWorkerLease.Snapshot live = BattleWorkerLease.snapshot();
            check("live_bound_worker_keeps_owner", live.ownerToken == owner
                    && "live-session".equals(live.sessionId));
            check("ui_cannot_release_live_worker_even_with_exact_token", !BattleWorkerLease.release(owner)
                    && BattleWorkerLease.isOwnedBy(owner));
            check("inactive_report_does_not_make_live_worker_available",
                    "worker_still_finishing".equals(BattleStartAttempt.busyReason(live, false))
                    && !BattleWorkerLease.tryClaim(other));
            check("active_campaign_has_specific_rejection",
                    "active_campaign".equals(BattleStartAttempt.busyReason(live, true)));
            check("live_worker_does_not_expire_after_repeated_checks", BattleWorkerLease.snapshot().isOwned()
                    && BattleWorkerLease.snapshot().isOwned() && !BattleWorkerLease.tryClaim(other));
        } finally {
            finish.countDown();
            worker.join(5000);
            BattleWorkerLease.release(owner);
        }
        check("live_worker_test_leaves_no_owner", !BattleWorkerLease.isOwned());
    }

    private void terminatedWorkerRecovery() throws Exception {
        Object dead = new Object();
        Object replacement = new Object();
        Thread exitedWithoutRelease = new Thread(() -> { }, "lease-missing-finally");
        try {
            check("dead_test_owner_claims", BattleWorkerLease.tryClaim(dead, "dead-session"));
            check("dead_test_binds_actual_worker", BattleWorkerLease.bindWorker(dead, exitedWithoutRelease));
            exitedWithoutRelease.start();
            exitedWithoutRelease.join(5000);
            check("worker_is_definitely_terminated", exitedWithoutRelease.getState() == Thread.State.TERMINATED);
            BattleWorkerLease.Snapshot recovered = BattleWorkerLease.snapshot();
            check("terminated_owner_is_recovered_with_identity", !recovered.isOwned()
                    && recovered.recoveredToken == dead && "dead-session".equals(recovered.recoveredSessionId));
            check("recovery_is_reported_once", BattleWorkerLease.snapshot().recoveredToken == null);
            check("replacement_claims_after_dead_worker", BattleWorkerLease.tryClaim(replacement, "replacement"));
            check("late_dead_release_cannot_clear_replacement", !BattleWorkerLease.release(dead)
                    && BattleWorkerLease.isOwnedBy(replacement));
            check("terminated_thread_cannot_bind_new_owner", !BattleWorkerLease.bindWorker(replacement, exitedWithoutRelease));
            BattleWorkerLease.release(replacement);

            Thread exitedBeforeNextClaim = new Thread(() -> { }, "lease-claim-recovery");
            check("second_dead_owner_claims_and_binds", BattleWorkerLease.tryClaim(dead)
                    && BattleWorkerLease.bindWorker(dead, exitedBeforeNextClaim));
            exitedBeforeNextClaim.start();
            exitedBeforeNextClaim.join(5000);
            check("claim_recovers_dead_worker_without_status_poll", BattleWorkerLease.tryClaim(replacement));
            check("stale_bind_cannot_attach_to_replacement", !BattleWorkerLease.bindWorker(dead, new Thread())
                    && BattleWorkerLease.isOwnedBy(replacement));
        } finally {
            BattleWorkerLease.release(dead);
            BattleWorkerLease.release(replacement);
        }
        check("dead_worker_test_leaves_no_owner", !BattleWorkerLease.isOwned());
    }

    private void ownerFinallyRelease() throws Exception {
        Object owner = new Object();
        AtomicReference<Boolean> released = new AtomicReference<>(false);
        Thread worker = new Thread(() -> {
            try { /* no platform or Python APIs */ }
            finally { released.set(BattleWorkerLease.release(owner)); }
        }, "lease-real-finally");
        try {
            check("finally_owner_claims_and_binds", BattleWorkerLease.tryClaim(owner)
                    && BattleWorkerLease.bindWorker(owner, worker));
            worker.start();
            worker.join(5000);
            check("bound_worker_finally_can_release_itself", Boolean.TRUE.equals(released.get())
                    && !BattleWorkerLease.isOwned());
        } finally { BattleWorkerLease.release(owner); }

        Object neverStarted = new Object();
        try {
            check("never_started_owner_claims_and_binds", BattleWorkerLease.tryClaim(neverStarted)
                    && BattleWorkerLease.bindWorker(neverStarted, new Thread()));
            check("failed_start_can_release_new_worker", BattleWorkerLease.release(neverStarted)
                    && !BattleWorkerLease.isOwned());
        } finally { BattleWorkerLease.release(neverStarted); }
    }

    private void startDiagnostics() throws Exception {
        Object owner = new Object();
        try {
            BattleWorkerLease.tryClaim(owner, "old-session");
            BattleWorkerLease.Snapshot reserved = BattleWorkerLease.snapshot();
            check("unbound_inactive_owner_has_reserved_reason",
                    "worker_reserved".equals(BattleStartAttempt.busyReason(reserved, false)));
            JSONObject previous = new JSONObject().put("event", "finished").put("active", false)
                    .put("session_id", "old-session").put("reason", "engine_finished");
            String previousBytes = previous.toString();
            JSONObject rejection = new JSONObject(BattleStartAttempt.report(false, "battle", "worker_reserved",
                    123, "old-session", false, "", reserved, ""));
            check("rejection_is_an_independent_request_answer", "start_rejected".equals(rejection.getString("event"))
                    && !rejection.getBoolean("accepted") && "worker_reserved".equals(rejection.getString("reason"))
                    && "".equals(rejection.getString("session_id")));
            check("rejection_links_prior_session_without_reusing_its_report",
                    "old-session".equals(rejection.getString("prior_session_id"))
                    && !rejection.getBoolean("prior_active") && previousBytes.equals(previous.toString()));
            check("rejection_includes_actual_lease_facts", rejection.getJSONObject("lease").getBoolean("owned")
                    && "UNBOUND".equals(rejection.getJSONObject("lease").getString("worker_state")));
            check("active_and_finishing_have_distinct_chinese_messages",
                    BattleStartAttempt.userMessage("{\"reason\":\"active_campaign\"}").contains("仍在运行")
                    && BattleStartAttempt.userMessage("{\"reason\":\"worker_still_finishing\"}").contains("后台引擎仍在"));
            check("invalid_parameter_message_is_specific",
                    BattleStartAttempt.userMessage("{\"reason\":\"invalid_options\"}").contains("参数无效"));
            check("unknown_refusal_remains_diagnostic",
                    BattleStartAttempt.userMessage("{\"reason\":\"worker_claim_race\"}").contains("worker_claim_race"));
            BattleWorkerLease.release(owner);
            check("no_lease_has_no_busy_reason", "".equals(BattleStartAttempt.busyReason(BattleWorkerLease.snapshot(), true)));
            JSONObject accepted = new JSONObject(BattleStartAttempt.report(true, "battle", "started", 124,
                    "old-session", false, "new-session", BattleWorkerLease.snapshot(), ""));
            check("accepted_attempt_distinguishes_old_and_new_session", accepted.getBoolean("accepted")
                    && "old-session".equals(accepted.getString("prior_session_id"))
                    && "new-session".equals(accepted.getString("session_id")));
        } finally { BattleWorkerLease.release(owner); }
    }

    private void check(String name, boolean passed) throws Exception {
        checks.put(new JSONObject().put("name", name).put("passed", passed));
        if (!passed) failures++;
    }

    private JSONObject result() throws Exception {
        return new JSONObject().put("checks", checks).put("check_count", checks.length())
                .put("failure_count", failures).put("device_inputs", 0)
                .put("uses_real_service", false);
    }
}
