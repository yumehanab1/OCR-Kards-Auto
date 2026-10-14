package com.kards.mobilert;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Rect;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.PriorityQueue;
import java.util.UUID;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;

/** Synthetic session safety tests. No AccessibilityService, device input, or game launch is used. */
public final class MulliganSessionChecks {
    private static final int STILL = 0xff303030;
    private static final int CHANGED = 0xff808080;
    private static final int BLACK = 0xff000000;
    private static final Rect CONFIRM = new Rect(600, 630, 680, 674); // center = (640, 652)
    private static final Rect END_TURN = new Rect(1090, 320, 1220, 375);

    private MulliganSessionChecks() { }

    public static JSONObject run(Context context) {
        return run(context.getFilesDir());
    }

    /** The caller supplies an app-private test directory, never a device connection. */
    public static JSONObject run(File appFiles) {
        File root = new File(appFiles, "single-action-tests/" + UUID.randomUUID());
        JSONArray cases = new JSONArray();
        int[] failures = {0};
        int[] fakeDispatchCalls = {0};
        runCase(root,cases,failures,fakeDispatchCalls,"overlay_prepare_cancel_before_input",f->{
            int[] releases={0};
            f.platform.inputPreparation=ready->f.scheduler.postDelayed(()->{
                f.session.cancel();ready.accept(()->releases[0]++);
            },80);
            f.source.add(mulligan(),STILL);f.source.add(mulligan(),STILL);f.startCurrentGame();f.runToStop();
            require(f.platform.taps==0 && releases[0]==1,"Cancel during overlay hide must release and emit no touch");
        });
        runCase(root,cases,failures,fakeDispatchCalls,"overlay_prepare_rechecks_frame_age",f->{
            int[] releases={0};
            f.platform.inputPreparation=ready->f.scheduler.postDelayed(()->ready.accept(()->releases[0]++),2000);
            f.source.add(mulligan(),STILL);f.source.add(mulligan(),STILL);f.startCurrentGame();f.runToStop();
            f.expectStopped("pre_dispatch_guard_rejected",0);
            require(f.platform.taps==0 && releases[0]==1,"Hidden interval cannot refresh an expired frame");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "new_foreground_event_required", f -> {
            f.platform.enterGame();
            f.session.start();
            f.scheduler.advanceBy(BoundedMulliganSession.TIME_BUDGET_MS);
            require(f.source.requests == 0 && f.platform.taps == 0, "Already foreground is not a new entry");
            f.expectStopped("time_budget", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "current_game_fresh_opening_and_post_pair", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.source.add(myTurn(), STILL); f.source.add(myTurn(), STILL);
            GameEntryGate entry = f.startCurrentGame();
            f.platform.finalDispatchGate = f.session::canDispatchPreparedTapNow;
            f.scheduler.until(() -> f.inspections == 3);
            require(!f.last().optBoolean("verified"), "Current entry still needs two post frames");
            f.runToStop();
            require(f.session.state() == BoundedMulliganSession.State.VERIFIED
                    && f.platform.emittedTaps == 1, "Current entry verifies exactly one tap");
            require(GameEntryGate.CURRENT_GAME.equals(f.last().optString("entryMode")), "Mode recorded");
            require(entry.check(f.platform.foreground, f.platform.generation) == null,
                    "Opening leaves the same campaign entry valid for battle");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "current_game_already_own_turn_handoff", f -> {
            f.source.add(myTurn(), STILL);
            GameEntryGate entry = f.startCurrentGame();
            f.runToStop(); f.expectStopped("already_my_turn_no_input", 0);
            require(entry.check(f.platform.foreground, f.platform.generation) == null, "Same entry hands off");
            f.platform.leaveGame(); f.platform.enterGame();
            require("foreground_changed".equals(entry.check(f.platform.foreground, f.platform.generation)),
                    "Battle cannot re-admit a returned game after opening");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "current_game_unknown_still_refused", f -> {
            f.source.add(unknown(), STILL);
            f.startCurrentGame(); f.runToStop(); f.expectStopped("unknown_screen", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "opening_black_frame_requires_a_new_stable_pair", f -> {
            f.source.add(mulligan(), STILL); f.source.add(unknown(), BLACK);
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.source.add(myTurn(), STILL); f.source.add(myTurn(), STILL);
            f.startCurrentGame();
            f.platform.finalDispatchGate = f.session::canDispatchPreparedTapNow;
            f.scheduler.until(() -> f.inspections == 3);
            require(f.session.isRunning() && f.platform.taps == 0,
                    "One opening frame after black cannot reuse the pre-black frame");
            require(f.last().optLong("pairedWithFrameSequence") == 0,
                    "Black capture cleared the previous stable-pair evidence");
            f.runToStop();
            require(f.session.state() == BoundedMulliganSession.State.VERIFIED
                    && f.platform.emittedTaps == 1, "Fresh opening and post pairs verify one tap");
            require(f.last().optLong("beforeInputFrameSequence") == 4,
                    "Only the second post-black opening frame authorizes dispatch");
            require(f.reports.stream().anyMatch(r -> r.optBoolean("emptyOpeningFrame")),
                    "Exact black recovery is recorded in frame evidence");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "continuous_opening_black_frames_keep_total_budget", f -> {
            for (int i = 0; i < 140; i++) f.source.add(unknown(), BLACK);
            f.startCurrentGame(); f.runToStop(); f.expectStopped("time_budget", 0);
            require(f.source.pending.isEmpty() && f.inspections > 100,
                    "Repeated black captures, rather than a hung request, reach the deadline");
            require(f.last().optLong("elapsedMillis") == BoundedMulliganSession.TIME_BUDGET_MS,
                    "Black recovery never resets the original 90 second deadline");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "near_black_unknown_is_not_empty", f -> {
            f.source.add(unknown(), 0xff000001);
            f.startCurrentGame(); f.runToStop(); f.expectStopped("unknown_screen", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "transparent_unknown_is_not_an_opaque_capture", f -> {
            f.source.add(unknown(), 0x00000000);
            f.startCurrentGame(); f.runToStop(); f.expectStopped("unknown_screen", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "one_unsampled_nonblack_pixel_is_not_empty", f -> {
            f.startCurrentGame(); f.scheduler.until(() -> f.source.requests == 1);
            Bitmap bitmap = f.source.deliver(f.source.pending.remove(), new FrameSpec(unknown(), BLACK));
            bitmap.setPixel(1279, 719, 0xff000001);
            f.runToStop(); f.expectStopped("unknown_screen", 0);
            require(bitmap.isRecycled(), "Nonempty unknown capture is still released");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "black_frame_after_recovery_still_requires_freshness", f -> {
            f.source.add(unknown(), BLACK);
            f.source.add(unknown(), BLACK).age = BoundedMulliganSession.MAX_FRAME_AGE_MS + 1;
            f.startCurrentGame(); f.runToStop(); f.expectStopped("stale_or_duplicate_frame", 0);
            require(f.inspections == 1, "Stale black frame never reaches recovery classification");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "black_recovery_keeps_foreground_generation_lock", f -> {
            f.source.add(unknown(), BLACK);
            f.onReport = report -> {
                if (report.optBoolean("emptyOpeningFrame")) {
                    f.platform.leaveGame(); f.platform.enterGame();
                }
            };
            f.startCurrentGame(); f.runToStop(); f.expectStopped("foreground_changed", 0);
            require(f.source.requests == 1, "Returned game cannot begin black-frame recovery");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "black_frame_expired_during_recognition_stops", f -> {
            f.source.add(unknown(), BLACK);
            f.onInspect = count -> f.clock.elapsed += BoundedMulliganSession.MAX_FRAME_AGE_MS + 1;
            f.startCurrentGame(); f.runToStop(); f.expectStopped("frame_expired_during_processing", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "black_frame_processing_cannot_extend_total_budget", f -> {
            f.source.add(unknown(), BLACK);
            f.onInspect = count -> f.clock.elapsed = BoundedMulliganSession.TIME_BUDGET_MS;
            f.startCurrentGame(); f.runToStop(); f.expectStopped("time_budget", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "nonblack_unknown_after_black_still_stops", f -> {
            f.source.add(unknown(), BLACK); f.source.add(unknown(), STILL);
            f.startCurrentGame(); f.runToStop(); f.expectStopped("unknown_screen", 0);
            require(f.inspections == 2, "Only the true black capture is retried");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "post_input_black_frame_never_repeats_tap", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.source.add(myTurn(), STILL); f.source.add(unknown(), BLACK);
            f.source.add(myTurn(), STILL); f.source.add(myTurn(), STILL);
            f.startCurrentGame();
            f.scheduler.until(() -> f.inspections == 5);
            require(f.session.isRunning() && f.platform.taps == 1 && !f.last().optBoolean("verified"),
                    "A post-input black capture still breaks the verification pair without retrying");
            f.runToStop();
            require(f.session.state() == BoundedMulliganSession.State.VERIFIED
                    && f.platform.taps == 1 && f.last().optLong("firstVerifiedFrameSequence") == 5
                    && f.last().optLong("secondVerifiedFrameSequence") == 6,
                    "Only the new post-input pair verifies the original single tap");
            require(f.reports.stream().noneMatch(r -> r.optBoolean("emptyOpeningFrame")),
                    "Post-input black frame uses the unchanged verification path");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "current_game_stale_frame_still_refused", f -> {
            f.source.add(mulligan(), STILL).age = BoundedMulliganSession.MAX_FRAME_AGE_MS + 1;
            f.startCurrentGame(); f.runToStop(); f.expectStopped("stale_or_duplicate_frame", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "current_game_leave_return_during_capture", f -> {
            f.startCurrentGame(); f.scheduler.until(() -> f.source.requests == 1);
            FrameSource.Callback callback = f.source.pending.remove();
            f.platform.leaveGame(); f.platform.enterGame();
            Bitmap late = f.source.deliver(callback, new FrameSpec(mulligan(), STILL));
            f.runToStop(); f.expectStopped("foreground_changed", 0);
            require(late.isRecycled() && f.inspections == 0, "Changed entry frame must close without recognition");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "current_game_final_foreground_gate", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.onReport = report -> {
                if ("pre_dispatch".equals(report.optString("event"))) { f.platform.leaveGame(); f.platform.enterGame(); }
            };
            f.startCurrentGame(); f.runToStop(); f.expectStopped("foreground_changed", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "current_game_platform_query_return_cannot_emit", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.startCurrentGame();
            f.platform.finalDispatchGate = f.session::canDispatchPreparedTapNow;
            f.platform.beforeFinalGate = () -> { f.platform.leaveGame(); f.platform.enterGame(); };
            f.runToStop(); f.expectStopped("foreground_changed", 1);
            require(f.platform.emittedTaps == 0, "Same package after a new generation cannot emit a tap");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "current_game_cancel_closes_pending_frame", f -> {
            f.startCurrentGame(); f.scheduler.until(() -> f.source.requests == 1);
            FrameSource.Callback callback = f.source.pending.remove();
            f.session.cancel();
            Bitmap late = f.source.deliver(callback, new FrameSpec(mulligan(), STILL));
            f.scheduler.advanceBy(0);
            require(late.isRecycled() && f.platform.taps == 0 && f.inspections == 0,
                    "Cancellation prevents an old current-game frame from authorizing input");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "one_tap_coordinates_and_two_frame_verification", f -> {
            require(!f.session.canDispatchPreparedTapNow(), "Unarmed session cannot dispatch");
            f.platform.finalDispatchGate = f.session::canDispatchPreparedTapNow;
            f.source.add(mulligan(), STILL);
            f.source.add(mulligan(), STILL);
            f.source.add(myTurn(), STILL);
            f.source.add(myTurn(), STILL);
            f.startAndEnter();
            f.scheduler.until(() -> f.platform.taps == 1);
            require(!f.last().optBoolean("verified"), "Dispatch acceptance cannot verify the game");
            require(Math.abs(f.platform.x - 0.5f) < 0.000001f, "x must be a 0..1 fraction");
            require(Math.abs(f.platform.y - 652f / 720f) < 0.000001f, "y must be a 0..1 fraction");
            f.scheduler.until(() -> f.inspections == 3);
            require(!f.last().optBoolean("verified"), "One post-input frame cannot verify");
            f.scheduler.until(() -> !f.session.isRunning());
            require(f.session.state() == BoundedMulliganSession.State.VERIFIED, "Two stable post frames verify");
            require(f.last().optBoolean("verified") && f.last().optInt("gameInputs") == 1, "Verified one input");
            require(f.platform.taps == 1, "No second platform tap");
            require(f.platform.emittedTaps == 1, "Fresh prepared dispatch passes the final gate");
            require(!f.session.canDispatchPreparedTapNow(), "Finished session cannot dispatch");
            require(f.last().optLong("firstVerifiedFrameSequence") == 3
                    && f.last().optLong("secondVerifiedFrameSequence") == 4, "Exact post-input pair recorded");
            File directory = f.session.sessionDirectory();
            require(new File(directory, "summary.json").isFile(), "Durable summary exists");
            for (int i = 1; i <= 4; i++) {
                String base = String.format(java.util.Locale.ROOT, "frame-%04d", i);
                require(new File(directory, base + ".png").isFile()
                        && new File(directory, base + ".json").isFile(), "Every frame has PNG and JSON");
            }
        });
        runCase(root, cases, failures, fakeDispatchCalls, "unknown_before_input_stops", f -> {
            f.source.add(unknown(), STILL);
            f.startAndEnter(); f.runToStop(); f.expectStopped("unknown_screen", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "opponent_first_after_completed_confirm_hands_off", f -> {
            f.source.add(mulligan(),STILL);f.source.add(mulligan(),STILL);
            f.source.add(result(MulliganRecognizer.Phase.CONFIRMED_OPPONENT_TURN,new Rect(1120,486,1191,523),"opponent"),STILL);
            f.source.add(result(MulliganRecognizer.Phase.CONFIRMED_OPPONENT_TURN,new Rect(1120,486,1191,523),"opponent"),STILL);
            f.startAndEnter();f.runToStop();
            require(f.session.state()==BoundedMulliganSession.State.VERIFIED && f.platform.taps==1
                    && "opponent_turn_after_completed_confirm".equals(f.last().optString("stopReason")),"Confirmed enemy turn hands off after one completed confirm");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "opponent_turn_before_confirm_cannot_verify", f -> {
            f.source.add(result(MulliganRecognizer.Phase.CONFIRMED_OPPONENT_TURN,new Rect(1120,486,1191,523),"opponent"),STILL);
            f.startAndEnter();f.runToStop();f.expectStopped("unexpected_phase_before_input",0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "already_my_turn_is_zero_input", f -> {
            f.source.add(myTurn(), STILL);
            f.startAndEnter(); f.runToStop(); f.expectStopped("already_my_turn_no_input", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "stale_frame_rejected", f -> {
            f.source.add(mulligan(), STILL).age = BoundedMulliganSession.MAX_FRAME_AGE_MS + 1;
            f.startAndEnter(); f.runToStop(); f.expectStopped("stale_or_duplicate_frame", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "duplicate_capture_timestamp_rejected", f -> {
            long timestamp = FakeClock.BASE + BoundedMulliganSession.FOREGROUND_SETTLE_MS;
            f.source.add(mulligan(), STILL).fixedTimestamp = timestamp;
            f.source.add(mulligan(), STILL).fixedTimestamp = timestamp;
            f.startAndEnter(); f.runToStop(); f.expectStopped("stale_or_duplicate_frame", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "moving_scene_cannot_authorize", f -> {
            f.source.add(mulligan(), STILL);
            f.source.add(mulligan(), CHANGED);
            f.source.add(unknown(), STILL);
            f.startAndEnter(); f.runToStop(); f.expectStopped("unknown_screen", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "target_movement_cannot_authorize", f -> {
            f.source.add(mulligan(), STILL);
            f.source.add(result(MulliganRecognizer.Phase.MULLIGAN_CONFIRM,
                    new Rect(620, 630, 700, 674), "mulligan_ok_btn"), STILL);
            f.source.add(unknown(), STILL);
            f.startAndEnter(); f.runToStop(); f.expectStopped("unknown_screen", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "template_change_cannot_authorize", f -> {
            f.source.add(mulligan(), STILL);
            f.source.add(result(MulliganRecognizer.Phase.MULLIGAN_CONFIRM, CONFIRM, "other_template"), STILL);
            f.source.add(unknown(), STILL);
            f.startAndEnter(); f.runToStop(); f.expectStopped("unknown_screen", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "foreground_final_gate", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.onReport = report -> {
                if ("pre_dispatch".equals(report.optString("event"))) f.platform.leaveGame();
            };
            f.startAndEnter(); f.runToStop(); f.expectStopped("foreground_changed", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "frame_expires_during_recognition", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.onInspect = count -> { if (count == 2) f.clock.elapsed += 1_501L; };
            f.startAndEnter(); f.runToStop(); f.expectStopped("frame_expired_during_processing", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "platform_query_delay_expires_frame_before_emission", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.platform.beforeFinalGate = () -> f.clock.elapsed += BoundedMulliganSession.MAX_FRAME_AGE_MS + 1;
            f.platform.finalDispatchGate = f.session::canDispatchPreparedTapNow;
            f.startAndEnter(); f.runToStop(); f.expectStopped("dispatch_rejected", 1);
            require(f.platform.finalGateChecks == 1 && f.platform.emittedTaps == 0,
                    "Slow platform query must reject before the actual fake gesture");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "platform_query_delay_expires_total_budget", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.platform.beforeFinalGate = () -> f.clock.elapsed = BoundedMulliganSession.TIME_BUDGET_MS;
            f.platform.finalDispatchGate = f.session::canDispatchPreparedTapNow;
            require(f.session.start(), "Session starts");
            f.scheduler.advanceBy(87_000L);
            f.platform.enterGame();
            f.runToStop(); f.expectStopped("time_budget", 1);
            require(f.clock.wallTimeMillis() - f.source.lastCapturedAt <= BoundedMulliganSession.MAX_FRAME_AGE_MS,
                    "This case expires total budget while the last frame is still fresh");
            require(f.platform.finalGateChecks == 1 && f.platform.emittedTaps == 0,
                    "Expired total budget must reject before the actual fake gesture");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "time_budget_before_dispatch", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.onInspect = count -> { if (count == 2) f.clock.elapsed = 90_000L; };
            f.startAndEnter(); f.runToStop(); f.expectStopped("time_budget", 0);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "hung_capture_still_times_out", f -> {
            f.startAndEnter(); f.runToStop(); f.expectStopped("time_budget", 0);
            require(f.source.requests == 1, "A pending screenshot is never duplicated");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "foreground_departure_invalidates_late_frame", f -> {
            f.startAndEnter();
            f.scheduler.until(() -> f.source.requests == 1);
            FrameSource.Callback callback = f.source.pending.remove();
            f.platform.leaveGame();
            f.scheduler.until(() -> !f.session.isRunning());
            f.expectStopped("foreground_changed", 0);
            int reports = f.reports.size();
            Bitmap late = f.source.deliver(callback, new FrameSpec(mulligan(), STILL));
            f.scheduler.advanceBy(0L);
            require(late.isRecycled() && f.reports.size() == reports, "Late frame only closes its bitmap");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "cancel_restart_invalidates_old_frame", f -> {
            f.startAndEnter();
            f.scheduler.until(() -> f.source.requests == 1);
            FrameSource.Callback old = f.source.pending.remove();
            f.session.cancel(); require(f.session.start(), "Restart succeeds");
            int reports = f.reports.size();
            Bitmap late = f.source.deliver(old, new FrameSpec(mulligan(), STILL));
            f.scheduler.advanceBy(500L);
            require(late.isRecycled(), "Old frame is recycled");
            require(f.reports.size() == reports && f.platform.taps == 0, "Old frame cannot publish or tap");
            require(f.session.state() == BoundedMulliganSession.State.WAITING_FOR_GAME, "New session still waits");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "rejected_frame_report_reentrant_restart", f -> {
            f.source.add(mulligan(), STILL).age = 1_501L;
            boolean[] restarted = {false};
            f.onReport = report -> {
                if (!restarted[0] && "frame_rejected".equals(report.optString("event"))) {
                    restarted[0] = true;
                    f.session.cancel();
                    require(f.session.start(), "Reentrant restart succeeds");
                }
            };
            f.startAndEnter();
            f.scheduler.until(() -> restarted[0]);
            f.scheduler.advanceBy(500L);
            require(f.session.isRunning()
                    && f.session.state() == BoundedMulliganSession.State.WAITING_FOR_GAME,
                    "Old rejected-frame finish cannot stop the new generation");
            require(f.platform.taps == 0 && "armed".equals(f.last().optString("event")), "New report remains armed");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "rejected_dispatch_is_not_success", f -> {
            f.platform.accepted = false;
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.startAndEnter(); f.runToStop(); f.expectStopped("dispatch_rejected", 1);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "cancelled_gesture_is_not_success", f -> {
            f.platform.autoComplete = false;
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.startAndEnter(); f.scheduler.until(() -> f.platform.taps == 1);
            f.platform.callback.onCancelled();
            f.runToStop(); f.expectStopped("gesture_cancelled", 1);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "hung_gesture_still_times_out", f -> {
            f.platform.autoComplete = false;
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.startAndEnter(); f.runToStop(); f.expectStopped("post_verification_timeout", 1);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "cancel_restart_invalidates_old_gesture", f -> {
            f.platform.autoComplete = false;
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.startAndEnter(); f.scheduler.until(() -> f.platform.taps == 1);
            BoundedMulliganSession.TapCallback old = f.platform.callback;
            f.session.cancel(); f.session.start();
            int reports = f.reports.size();
            old.onCompleted(); f.scheduler.advanceBy(500L);
            require(f.reports.size() == reports && f.session.gameInputs() == 0, "Old gesture cannot update new session");
            require(f.session.state() == BoundedMulliganSession.State.WAITING_FOR_GAME, "New generation remains waiting");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "unknown_after_input_then_stable_turn_verifies", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL); f.source.add(unknown(), STILL);
            f.source.add(myTurn(), STILL); f.source.add(myTurn(), STILL);
            f.startAndEnter();
            f.scheduler.until(() -> f.inspections == 3);
            require(f.session.isRunning() && !f.last().optBoolean("verified"), "Unknown transition only waits");
            f.runToStop();
            require(f.session.state() == BoundedMulliganSession.State.VERIFIED
                    && f.last().optBoolean("verified"), "Two new confirmed turn frames verify after transition");
            require(f.platform.taps == 1 && f.session.gameInputs() == 1, "Transition never repeats input");
            require(f.last().optLong("firstVerifiedFrameSequence") == 4
                    && f.last().optLong("secondVerifiedFrameSequence") == 5, "Only post-unknown pair verifies");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "opponent_first_then_animated_draw_waits_for_stable_pair", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            // With 650 ms between frames, these cover the old 12 s limit before our turn.
            for (int i = 0; i < 18; i++) f.source.add(unknown(), STILL);
            f.source.add(myTurn(), STILL); f.source.add(myTurn(), CHANGED);
            f.source.add(myTurn(), STILL); f.source.add(myTurn(), STILL);
            f.startCurrentGame();
            f.scheduler.until(() -> f.inspections == 23);
            require(f.last().optLong("postVerificationElapsedMillis") > 12_000L,
                    "Opponent-first fixture exceeds the previous post-input allowance");
            require(f.session.isRunning() && !f.last().optBoolean("verified"),
                    "Friendly-turn and draw animation cannot substitute for stable frames");
            f.runToStop();
            require(f.session.state() == BoundedMulliganSession.State.VERIFIED
                    && f.platform.taps == 1 && f.session.gameInputs() == 1,
                    "A delayed consecutive stable pair verifies the single original tap");
            require(f.last().optLong("firstVerifiedFrameSequence") == 23
                    && f.last().optLong("secondVerifiedFrameSequence") == 24,
                    "Only the pair after opponent turn and draw animation verifies");
            require(f.last().optLong("postVerificationElapsedMillis")
                    < BoundedMulliganSession.POST_VERIFICATION_BUDGET_MS, "Verification is within budget");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "repeated_unknown_after_input_has_thirty_second_budget", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            for (int i = 0; i < 60; i++) f.source.add(unknown(), STILL);
            f.startAndEnter(); f.runToStop(); f.expectStopped("post_verification_timeout", 1);
            require(f.inspections > 3, "Multiple transition frames were observed without retry");
            require(f.source.pending.isEmpty(), "Permanent unknown, rather than a hung capture, reaches deadline");
            f.expectPostDeadline();
        });
        runCase(root, cases, failures, fakeDispatchCalls, "hung_post_input_capture_has_thirty_second_budget", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.startAndEnter(); f.runToStop(); f.expectStopped("post_verification_timeout", 1);
            require(f.source.requests == 3 && f.source.pending.size() == 1,
                    "Exactly one post-input screenshot remains hung");
            f.expectPostDeadline();
        });
        runCase(root, cases, failures, fakeDispatchCalls, "post_timeout_late_frame_and_failure_cannot_resume", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.startCurrentGame();
            f.scheduler.until(() -> f.source.requests == 3);
            FrameSource.Callback callback = f.source.pending.remove();
            f.runToStop(); f.expectStopped("post_verification_timeout", 1);
            int reports = f.reports.size();
            int inspections = f.inspections;
            Bitmap late = f.source.deliver(callback, new FrameSpec(myTurn(), STILL));
            callback.onFailure("late_capture_failure");
            f.scheduler.advanceBy(BoundedMulliganSession.SAMPLE_INTERVAL_MS);
            require(late.isRecycled() && f.reports.size() == reports && f.inspections == inspections,
                    "Late callbacks only release their frame without recognition or reports");
            require(f.source.requests == 3 && f.platform.taps == 1
                    && !f.session.canDispatchPreparedTapNow(), "Timeout cannot schedule more captures or input");
            f.expectStopped("post_verification_timeout", 1);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "post_timeout_late_gesture_cannot_resume", f -> {
            f.platform.autoComplete = false;
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.startCurrentGame(); f.runToStop(); f.expectStopped("post_verification_timeout", 1);
            int reports = f.reports.size();
            f.platform.callback.onCompleted();
            f.platform.callback.onCancelled();
            f.scheduler.advanceBy(BoundedMulliganSession.POST_TAP_SETTLE_MS);
            require(f.reports.size() == reports && f.source.requests == 2 && f.platform.taps == 1
                    && !f.session.canDispatchPreparedTapNow(), "Late gesture cannot start verification or tap again");
            f.expectStopped("post_verification_timeout", 1);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "opponent_wait_does_not_extend_total_budget", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            for (int i = 0; i < 60; i++) f.source.add(unknown(), STILL);
            require(f.session.start(), "Session starts");
            f.scheduler.advanceBy(70_000L);
            f.platform.enterGame();
            f.runToStop(); f.expectStopped("time_budget", 1);
            require(f.last().optLong("elapsedMillis") == BoundedMulliganSession.TIME_BUDGET_MS
                    && f.last().optLong("postVerificationElapsedMillis")
                        < BoundedMulliganSession.POST_VERIFICATION_BUDGET_MS,
                    "The original 90 s deadline takes precedence over the read-only allowance");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "delayed_post_frame_still_requires_freshness", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            for (int i = 0; i < 18; i++) f.source.add(unknown(), STILL);
            f.source.add(myTurn(), STILL).age = BoundedMulliganSession.MAX_FRAME_AGE_MS + 1;
            f.startCurrentGame(); f.runToStop(); f.expectStopped("stale_or_duplicate_frame", 1);
            require(f.last().optLong("postVerificationElapsedMillis") > 12_000L,
                    "The longer opponent wait does not relax frame freshness");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "delayed_post_wait_keeps_foreground_generation_lock", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            for (int i = 0; i < 18; i++) f.source.add(unknown(), STILL);
            f.startCurrentGame();
            f.scheduler.until(() -> f.inspections == 20);
            require(f.last().optLong("postVerificationElapsedMillis") > 12_000L,
                    "Fixture reaches the extended read-only interval");
            f.platform.leaveGame(); f.platform.enterGame();
            f.runToStop(); f.expectStopped("foreground_changed", 1);
            require(!f.session.canDispatchPreparedTapNow(), "Returning cannot grant a new input");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "unknown_breaks_post_input_stable_pair", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.source.add(myTurn(), STILL); f.source.add(unknown(), STILL);
            f.source.add(myTurn(), STILL); f.source.add(myTurn(), STILL);
            f.startAndEnter();
            f.scheduler.until(() -> f.inspections == 5);
            require(f.session.isRunning() && !f.last().optBoolean("verified"),
                    "Confirmed frames separated by UNKNOWN cannot form a stable pair");
            f.runToStop();
            require(f.session.state() == BoundedMulliganSession.State.VERIFIED
                    && f.platform.taps == 1, "Only a new consecutive pair verifies the same single input");
            require(f.last().optLong("firstVerifiedFrameSequence") == 5
                    && f.last().optLong("secondVerifiedFrameSequence") == 6, "Pair restarts after UNKNOWN");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "post_verification_budget_checked_after_recognition", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.source.add(myTurn(), STILL); f.source.add(myTurn(), STILL);
            f.onInspect = count -> {
                if (count == 4) f.clock.elapsed = f.last().optLong("dispatchedAtElapsedMillis")
                        + BoundedMulliganSession.POST_VERIFICATION_BUDGET_MS;
            };
            f.startAndEnter(); f.runToStop(); f.expectStopped("post_verification_timeout", 1);
            require(f.last().optLong("postVerificationElapsedMillis")
                    == BoundedMulliganSession.POST_VERIFICATION_BUDGET_MS,
                    "Recognition cannot verify at the deadline before watchdog executes");
        });
        runCase(root, cases, failures, fakeDispatchCalls, "mulligan_residual_never_retries", f -> {
            for (int i = 0; i < 4; i++) f.source.add(mulligan(), STILL);
            f.source.add(unknown(), STILL);
            f.startAndEnter(); f.runToStop(); f.expectStopped("post_verification_timeout", 1);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "unstable_post_frames_do_not_verify", f -> {
            f.source.add(mulligan(), STILL); f.source.add(mulligan(), STILL);
            f.source.add(myTurn(), STILL); f.source.add(myTurn(), CHANGED); f.source.add(unknown(), STILL);
            f.startAndEnter(); f.runToStop(); f.expectStopped("post_verification_timeout", 1);
        });
        runCase(root, cases, failures, fakeDispatchCalls, "evidence_failure_prevents_input", f -> {
            File notDirectory = new File(f.directory, "not-a-directory");
            require(f.directory.mkdirs() || f.directory.isDirectory(), "Test directory available");
            try (FileOutputStream stream = new FileOutputStream(notDirectory)) { stream.write(1); }
            BoundedMulliganSession blocked = f.createSession(notDirectory);
            require(!blocked.start() && !blocked.isRunning(), "Unwritable evidence refuses start");
            require(f.platform.taps == 0, "Evidence failure has no input");
        });
        JSONObject report = new JSONObject();
        put(report, "suite", "bounded-mulligan-session-synthetic-v1");
        put(report, "status", failures[0] == 0 ? "passed" : "failed");
        put(report, "case_count", cases.length());
        put(report, "failure_count", failures[0]);
        put(report, "real_device_inputs", 0);
        put(report, "game_launches", 0);
        put(report, "fake_dispatch_calls", fakeDispatchCalls[0]);
        put(report, "evidence_root", root.getAbsolutePath());
        put(report, "cases", cases);
        return report;
    }

    private interface Check { void run(Fixture fixture) throws Exception; }

    private static void runCase(File root, JSONArray cases, int[] failures, int[] fakeDispatchCalls,
                                String name, Check check) {
        JSONObject result = new JSONObject();
        put(result, "name", name);
        Fixture fixture = new Fixture(new File(root, name));
        try {
            check.run(fixture);
            put(result, "status", "passed");
        } catch (Throwable error) {
            failures[0]++;
            put(result, "status", "failed");
            put(result, "error", error.getClass().getSimpleName() + ": " + error.getMessage());
        } finally {
            fixture.onReport = null;
            fixture.session.cancel();
            fakeDispatchCalls[0] += fixture.platform.taps;
            put(result, "fake_dispatch_calls", fixture.platform.taps);
            put(result, "fake_emitted_taps", fixture.platform.emittedTaps);
            put(result, "frame_requests", fixture.source.requests);
            put(result, "real_device_inputs", 0);
            cases.put(result);
        }
    }

    private static final class Fixture {
        final File directory;
        final FakeClock clock = new FakeClock();
        final FakeScheduler scheduler = new FakeScheduler(clock);
        final FakePlatform platform = new FakePlatform();
        final IdentityHashMap<Bitmap, MulliganRecognizer.Result> recognition = new IdentityHashMap<>();
        final List<JSONObject> reports = new ArrayList<>();
        final FakeSource source = new FakeSource(this);
        BoundedMulliganSession session;
        Consumer<JSONObject> onReport;
        Consumer<Integer> onInspect;
        int inspections;
        Fixture(File directory) {
            this.directory = directory;
            session = createSession(directory);
        }
        BoundedMulliganSession createSession(File files) {
            return createSession(files, null);
        }
        BoundedMulliganSession createSession(File files, GameEntryGate entryGate) {
            return new BoundedMulliganSession(files, source, platform, bitmap -> {
                inspections++;
                if (onInspect != null) onInspect.accept(inspections);
                return recognition.remove(bitmap);
            }, clock, scheduler, raw -> {
                JSONObject report;
                try { report = new JSONObject(raw); }
                catch (JSONException error) { throw new AssertionError("Report must be JSON", error); }
                reports.add(report);
                if (onReport != null) onReport.accept(report);
            }, entryGate);
        }
        GameEntryGate startCurrentGame() {
            platform.enterGame();
            GameEntryGate entry = new GameEntryGate(GameEntryGate.CURRENT_GAME,
                    platform.foreground, platform.generation, clock.elapsedRealtimeMillis());
            session = createSession(directory, entry);
            require(session.start(), "Current game session starts without another entry");
            return entry;
        }
        void startAndEnter() { require(session.start(), "Session starts"); platform.enterGame(); }
        void runToStop() { scheduler.until(() -> !session.isRunning()); }
        JSONObject last() { return reports.get(reports.size() - 1); }
        void expectStopped(String reason, int inputs) {
            require(!session.isRunning(), "Session stopped");
            require(reason.equals(last().optString("stopReason")), "Stop reason: " + last());
            require(!last().optBoolean("verified"), "Stopped session cannot claim verified");
            require(session.gameInputs() == inputs && platform.taps == inputs, "Expected dispatch count " + inputs);
            require(BoundedMulliganSession.ACTION_SCOPE.equals(last().optString("actionScope")),
                    "Action scope is only mulligan_confirm");
        }
        void expectPostDeadline() {
            long postElapsed = last().optLong("postVerificationElapsedMillis");
            require(postElapsed >= BoundedMulliganSession.POST_VERIFICATION_BUDGET_MS
                    && postElapsed <= BoundedMulliganSession.POST_VERIFICATION_BUDGET_MS
                        + BoundedMulliganSession.SAMPLE_INTERVAL_MS,
                    "Independent watchdog stops near the 30 second post-input deadline");
            require(last().optLong("elapsedMillis") < BoundedMulliganSession.TIME_BUDGET_MS,
                    "Post-input timeout does not wait for the full 90 seconds");
        }
    }

    private static final class FakeClock implements BoundedMulliganSession.Clock {
        static final long BASE = 1_800_000_000_000L;
        long elapsed;
        @Override public long wallTimeMillis() { return BASE + elapsed; }
        @Override public long elapsedRealtimeMillis() { return elapsed; }
    }

    private static final class FakeScheduler implements BoundedMulliganSession.Scheduler {
        final FakeClock clock;
        final PriorityQueue<Scheduled> queue = new PriorityQueue<>();
        long order;
        FakeScheduler(FakeClock clock) { this.clock = clock; }
        @Override public void postDelayed(Runnable callback, long delay) {
            queue.add(new Scheduled(clock.elapsed + Math.max(0L, delay), ++order, callback));
        }
        void next() {
            require(!queue.isEmpty(), "Expected a scheduled callback");
            Scheduled next = queue.remove();
            clock.elapsed = Math.max(clock.elapsed, next.at);
            next.callback.run();
        }
        void until(BooleanSupplier condition) {
            for (int step = 0; !condition.getAsBoolean(); step++) {
                require(step < 2_000, "Fake scheduler progress bound"); next();
            }
        }
        void advanceBy(long millis) {
            long target = clock.elapsed + millis;
            int steps = 0;
            while (!queue.isEmpty() && queue.peek().at <= target) {
                require(++steps < 2_000, "Fake scheduler advance bound"); next();
            }
            clock.elapsed = Math.max(clock.elapsed, target);
        }
    }

    private static final class Scheduled implements Comparable<Scheduled> {
        final long at;
        final long order;
        final Runnable callback;
        Scheduled(long at, long order, Runnable callback) { this.at = at; this.order = order; this.callback = callback; }
        @Override public int compareTo(Scheduled other) {
            int time = Long.compare(at, other.at);
            return time == 0 ? Long.compare(order, other.order) : time;
        }
    }

    private static final class FrameSpec {
        final MulliganRecognizer.Result result;
        final int color;
        long age;
        long fixedTimestamp = -1;
        FrameSpec(MulliganRecognizer.Result result, int color) { this.result = result; this.color = color; }
    }

    private static final class FakeSource implements FrameSource {
        final Fixture fixture;
        final ArrayDeque<FrameSpec> frames = new ArrayDeque<>();
        final ArrayDeque<Callback> pending = new ArrayDeque<>();
        int requests;
        long lastCapturedAt;
        FakeSource(Fixture fixture) { this.fixture = fixture; }
        FrameSpec add(MulliganRecognizer.Result result, int color) {
            FrameSpec frame = new FrameSpec(result, color); frames.add(frame); return frame;
        }
        @Override public void requestFrame(Callback callback) {
            requests++;
            if (frames.isEmpty()) pending.add(callback);
            else deliver(callback, frames.remove());
        }
        Bitmap deliver(Callback callback, FrameSpec frame) {
            Bitmap bitmap = Bitmap.createBitmap(1280, 720, Bitmap.Config.ARGB_8888);
            bitmap.eraseColor(frame.color);
            fixture.recognition.put(bitmap, frame.result);
            long timestamp = frame.fixedTimestamp >= 0 ? frame.fixedTimestamp
                    : fixture.clock.wallTimeMillis() - frame.age;
            lastCapturedAt = timestamp;
            callback.onFrame(new FrameSnapshot(bitmap, timestamp, 1920, 1080));
            return bitmap;
        }
    }

    private static final class FakePlatform implements BoundedMulliganSession.Platform {
        String foreground = "test.prototype";
        long generation = 1;
        boolean accepted = true;
        boolean autoComplete = true;
        int taps;
        int emittedTaps;
        int finalGateChecks;
        Runnable beforeFinalGate;
        BooleanSupplier finalDispatchGate;
        Consumer<Consumer<Runnable>> inputPreparation=ready->ready.accept(()->{});
        float x;
        float y;
        BoundedMulliganSession.TapCallback callback;
        void enterGame() { foreground = BoundedMulliganSession.GAME_PACKAGE; generation++; }
        void leaveGame() { foreground = "test.other"; generation++; }
        @Override public String currentForegroundPackage() { return foreground; }
        @Override public long foregroundGeneration() { return generation; }
        @Override public void prepareInput(Consumer<Runnable> ready) { inputPreparation.accept(ready); }
        @Override public boolean dispatchTap(float x, float y, BoundedMulliganSession.TapCallback callback) {
            require(BoundedMulliganSession.GAME_PACKAGE.equals(foreground), "Only fake game foreground may dispatch");
            taps++; this.x = x; this.y = y; this.callback = callback;
            if (beforeFinalGate != null) beforeFinalGate.run();
            if (finalDispatchGate != null) {
                finalGateChecks++;
                if (!finalDispatchGate.getAsBoolean()) return false;
            }
            if (accepted) emittedTaps++;
            if (accepted && autoComplete) callback.onCompleted();
            return accepted;
        }
    }

    private static MulliganRecognizer.Result mulligan() {
        return result(MulliganRecognizer.Phase.MULLIGAN_CONFIRM, CONFIRM, "mulligan_ok_btn");
    }
    private static MulliganRecognizer.Result myTurn() {
        return result(MulliganRecognizer.Phase.CONFIRMED_MY_TURN, END_TURN, "end_turn_btn");
    }
    private static MulliganRecognizer.Result unknown() {
        return new MulliganRecognizer.Result(MulliganRecognizer.Phase.UNKNOWN, null, 0, "synthetic_unknown", "");
    }
    private static MulliganRecognizer.Result result(MulliganRecognizer.Phase phase, Rect target, String template) {
        return new MulliganRecognizer.Result(phase, new Rect(target), 0.99, "synthetic_fixture", template);
    }
    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    private static void put(JSONObject object, String key, Object value) {
        try { object.put(key, value); }
        catch (JSONException error) { throw new AssertionError("Invalid test report", error); }
    }
}
