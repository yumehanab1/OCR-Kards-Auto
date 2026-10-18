package com.kards.mobilert;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

/** A timeout and the last pre-input claim must have exactly one winner.
 * No lock is held across an Android call, callback or evidence write. */
final class DispatchAttempt {
    static final int MAX_STAGES = 32;

    enum State {
        QUEUED, SUBMITTING, ACCEPTED, COMPLETED, CANCELLED, REJECTED,
        FAILED_BEFORE_INPUT, FAILED_INPUT_UNCERTAIN,
        TIMED_OUT_BEFORE_INPUT, TIMED_OUT_INPUT_UNCERTAIN
    }

    static final class Result {
        final State state;
        final boolean accepted;
        final boolean completed;
        final boolean inputUncertain;
        final String reason;

        Result(State state, boolean accepted, boolean completed, boolean uncertain, String reason) {
            this.state = state;
            this.accepted = accepted;
            this.completed = completed;
            this.inputUncertain = uncertain;
            this.reason = reason;
        }

        boolean terminal() {
            return state != State.QUEUED && state != State.SUBMITTING && state != State.ACCEPTED;
        }
    }

    static final class Stage {
        final String name;
        final long elapsedMs;
        Stage(String name, long elapsedMs) { this.name = name; this.elapsedMs = elapsedMs; }
    }

    private final AtomicReference<Result> result = new AtomicReference<>(
            new Result(State.QUEUED, false, false, false, "dispatch_queued"));
    private final List<Stage> stages = new ArrayList<>();

    boolean isPreparing() { return result.get().state == State.QUEUED; }
    Result result() { return result.get(); }

    static String interruptionReason(Result result) {
        if (result.accepted && result.completed) return "dispatch_interrupted_after_completed_input";
        if (result.inputUncertain) return "dispatch_interrupted_input_status_uncertain";
        return result.accepted ? "dispatch_interrupted_after_input" : "dispatch_interrupted_before_input";
    }

    /** This CAS is the sole authorization to enter dispatchGesture. If timeout
     * wins while QUEUED, even an already-running main task cannot submit later. */
    boolean trySubmit(long now) {
        Result current = result.get();
        if (current.state != State.QUEUED || !result.compareAndSet(current,
                new Result(State.SUBMITTING, false, false, true, "dispatch_submitting"))) return false;
        stage("submit_claimed", now);
        return true;
    }

    void submissionReturned(boolean accepted, long now) {
        stage(accepted ? "platform_accepted" : "platform_rejected", now);
        Result current = result.get();
        if (current.state != State.SUBMITTING) return;
        result.compareAndSet(current, accepted
                ? new Result(State.ACCEPTED, true, false, true, "dispatch_accepted")
                : new Result(State.REJECTED, false, false, false, "platform_rejected"));
    }

    /** First callback wins. A late callback cannot change a timeout's result. */
    boolean callback(boolean completed, long now) {
        stage(completed ? "callback_completed" : "callback_cancelled", now);
        while (true) {
            Result current = result.get();
            if (current.state != State.SUBMITTING && current.state != State.ACCEPTED) return false;
            Result next = new Result(completed ? State.COMPLETED : State.CANCELLED,
                    true, completed, !completed,
                    completed ? "gesture_completed_unverified" : "gesture_cancelled");
            if (result.compareAndSet(current, next)) return true;
        }
    }

    void rejectPreparation(String reason, long now) {
        stage("preparation_rejected", now);
        Result current = result.get();
        if (current.state == State.QUEUED) result.compareAndSet(current,
                new Result(State.FAILED_BEFORE_INPUT, false, false, false, reason));
    }

    void fail(String reason, long now) {
        stage("boundary_failed", now);
        while (true) {
            Result current = result.get();
            if (current.terminal()) return;
            boolean before = current.state == State.QUEUED;
            Result next = new Result(before ? State.FAILED_BEFORE_INPUT : State.FAILED_INPUT_UNCERTAIN,
                    current.accepted, false, !before, reason);
            if (result.compareAndSet(current, next)) return;
        }
    }

    Result timeout(String uncertainReason, long now) {
        stage("wait_timeout", now);
        while (true) {
            Result current = result.get();
            // A callback can win just after await returns false but before this CAS.
            if (current.terminal()) return current;
            boolean before = current.state == State.QUEUED;
            Result next = new Result(before ? State.TIMED_OUT_BEFORE_INPUT : State.TIMED_OUT_INPUT_UNCERTAIN,
                    current.accepted, false, !before,
                    before ? "dispatch_prepare_timeout_before_input" : uncertainReason);
            if (result.compareAndSet(current, next)) return next;
        }
    }

    synchronized void stage(String name, long now) {
        if (stages.size() < MAX_STAGES) stages.add(new Stage(name, now));
    }

    synchronized List<Stage> stages() { return new ArrayList<>(stages); }
}
