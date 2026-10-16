package com.kards.mobilert;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Rect;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.UUID;
import java.util.function.Consumer;

/**
 * Explicitly armed, one-input session for keeping the original mulligan hand.
 * This class never authorizes a BoardObservation or calls a combat executor.
 * The default entry requires a NEW game foreground transition. An explicit
 * campaign token may instead lock the game already in front. Both require new frames.
 *
 * <p>All asynchronous work is generation checked. The platform must dispatch
 * synchronously and check the foreground again at the actual gesture boundary;
 * enqueueing an unchecked gesture would defeat cancellation and freshness.</p>
 */
public final class BoundedMulliganSession {
    public static final String GAME_PACKAGE = "com.android1939.kards";
    public static final String ACTION_SCOPE = "mulligan_confirm";
    public static final long TIME_BUDGET_MS = 90_000L;
    // Opponent-first starts include their turn, our turn banner, and the draw animation.
    // This allowance is read-only after the one confirm tap; the total 90 s limit still applies.
    public static final long POST_VERIFICATION_BUDGET_MS = 30_000L;
    public static final long MAX_FRAME_AGE_MS = 1_500L;
    public static final long SAMPLE_INTERVAL_MS = 650L;
    public static final long FOREGROUND_SETTLE_MS = 1_500L;
    public static final long POST_TAP_SETTLE_MS = 2_000L;
    private static final long WATCHDOG_INTERVAL_MS = 200L;
    private static final long MIN_FRAME_SEPARATION_MS = 250L;
    private static final int SAMPLE_COLUMNS = 80;
    private static final int SAMPLE_ROWS = 45;
    private static final double MAX_MEAN_CHANNEL_DELTA = 2.0;
    private static final double MAX_CHANGED_SAMPLE_FRACTION = 0.01;
    private static final int CHANGED_PIXEL_DELTA = 16;
    private static final int MAX_TARGET_MOVEMENT_PX = 2;

    public enum State {
        IDLE, WAITING_FOR_GAME, OBSERVING_MULLIGAN, DISPATCHING,
        VERIFYING, VERIFIED, STOPPED, CANCELLED
    }

    /** foregroundGeneration increases on every observed foreground package transition. */
    public interface Platform {
        /** Prepare an unobscured input boundary; release after the system callback or refusal. */
        default void prepareInput(java.util.function.Consumer<Runnable> ready) { ready.accept(()->{}); }
        default boolean inputOccluded() { return false; }
        String currentForegroundPackage();
        long foregroundGeneration();

        /**
         * Synchronously attempt this one normalized tap. Return the Android
         * dispatch acceptance value, which is NOT verification of game success.
         * Recheck GAME_PACKAGE at the actual dispatch boundary; do not queue it.
         */
        boolean dispatchTap(float xNormalized, float yNormalized, TapCallback callback);
    }

    public interface TapCallback {
        void onCompleted();
        void onCancelled();
    }

    /** Injection seam: saved/fake frames can exercise all gates without input. */
    public interface Inspector {
        MulliganRecognizer.Result inspect(Bitmap bitmap);
        default MulliganRecognizer.Result inspectSaved(Bitmap bitmap, File source) { return inspect(bitmap); }
    }

    public interface Clock {
        long wallTimeMillis();
        long elapsedRealtimeMillis();
    }

    /** Implementations must serialize scheduled callbacks; a fake scheduler can advance time. */
    public interface Scheduler {
        void postDelayed(Runnable callback, long delayMillis);
    }

    private final File filesDirectory;
    private final FrameSource frameSource;
    private final Platform platform;
    private final Inspector inspector;
    private final Clock clock;
    private final Scheduler scheduler;
    private final Consumer<String> onReport;
    private final GameEntryGate suppliedEntryGate;
    private GameEntryGate entryGate;
    private State state = State.IDLE;
    private boolean active;
    private boolean capturePending;
    private boolean foregroundAdmitted;
    private boolean dispatchAccepted;
    private boolean dispatchReturned;
    private boolean gestureCompleted;
    private boolean gestureCancelled;
    private boolean opponentMulliganWaitObserved;
    private long firstOpponentMulliganWaitFrameSequence;
    private int captureFailures;
    private boolean verified;
    private long generation;
    private long armedForegroundGeneration;
    private long admittedForegroundGeneration;
    private long startedElapsed;
    private long startedWall;
    private long latestFrameSequence;
    private long pendingFrameSequence;
    private long lastCapturedAt;
    private long dispatchedAtWall;
    private long dispatchedAtElapsed;
    private long beforeInputFrameSequence;
    private long firstVerifiedFrameSequence;
    private long secondVerifiedFrameSequence;
    private int gameInputs;
    private int eventSequence;
    private File sessionDirectory;
    private String sessionId = "";
    private String stopReason = "";
    private Evidence previous;
    private boolean nativePixels;

    public BoundedMulliganSession(Context context, FrameSource frameSource,
                                  Platform platform, Consumer<String> onReport) {
        this(context, frameSource, platform, onReport, null);
    }

    BoundedMulliganSession(Context context, FrameSource frameSource,
                           Platform platform, Consumer<String> onReport, GameEntryGate entryGate) {
        this(context.getFilesDir(), frameSource, platform,
                new MulliganRecognizer(context)::inspect, new Clock() {
                    @Override public long wallTimeMillis() { return System.currentTimeMillis(); }
                    @Override public long elapsedRealtimeMillis() { return SystemClock.elapsedRealtime(); }
                }, mainThreadScheduler(), onReport, entryGate);
    }

    BoundedMulliganSession(Context context, FrameSource frameSource,
                           Platform platform, Consumer<String> onReport, GameEntryGate entryGate, boolean nativePixels) {
        this(context,frameSource,platform,onReport,entryGate,nativePixels,context.getFilesDir());
    }

    BoundedMulliganSession(Context context, FrameSource frameSource,
                           Platform platform, Consumer<String> onReport, GameEntryGate entryGate,
                           boolean nativePixels, File evidenceRoot) {
        this(evidenceRoot, frameSource, platform,
                nativePixels ? new NativeOpeningInspector(context) : new MulliganRecognizer(context)::inspect,
                new Clock() {
                    @Override public long wallTimeMillis() { return System.currentTimeMillis(); }
                    @Override public long elapsedRealtimeMillis() { return SystemClock.elapsedRealtime(); }
                }, mainThreadScheduler(), onReport, entryGate);
        this.nativePixels=nativePixels;
    }

    /** Test constructor; production uses Context.getFilesDir() via the constructor above. */
    public BoundedMulliganSession(File filesDirectory, FrameSource frameSource,
                                  Platform platform, Inspector inspector, Clock clock,
                                  Scheduler scheduler, Consumer<String> onReport) {
        this(filesDirectory, frameSource, platform, inspector, clock, scheduler, onReport, null);
    }

    BoundedMulliganSession(File filesDirectory, FrameSource frameSource,
                           Platform platform, Inspector inspector, Clock clock,
                           Scheduler scheduler, Consumer<String> onReport, GameEntryGate entryGate) {
        if (filesDirectory == null || frameSource == null || platform == null
                || inspector == null || clock == null || scheduler == null) {
            throw new IllegalArgumentException("Session dependencies must not be null");
        }
        this.filesDirectory = filesDirectory;
        this.frameSource = frameSource;
        this.platform = platform;
        this.inspector = inspector;
        this.clock = clock;
        this.scheduler = scheduler;
        this.onReport = onReport;
        this.suppliedEntryGate = entryGate;
    }

    private static Scheduler mainThreadScheduler() {
        Handler handler = new Handler(Looper.getMainLooper());
        return (callback, delay) -> handler.postDelayed(callback, Math.max(0L, delay));
    }

    /** A stopped instance may be explicitly started again; old callbacks stay invalid. */
    public synchronized boolean start() {
        if (active) return false;
        long token = ++generation;
        active = true;
        capturePending = false;
        foregroundAdmitted = false;
        dispatchAccepted = false;
        dispatchReturned = false;
        gestureCompleted = false;
        gestureCancelled = false;
        opponentMulliganWaitObserved = false;
        firstOpponentMulliganWaitFrameSequence = 0;
        captureFailures=0;
        verified = false;
        previous = null;
        gameInputs = 0;
        eventSequence = 0;
        latestFrameSequence = 0;
        pendingFrameSequence = 0;
        lastCapturedAt = 0;
        dispatchedAtWall = 0;
        dispatchedAtElapsed = 0;
        beforeInputFrameSequence = 0;
        firstVerifiedFrameSequence = 0;
        secondVerifiedFrameSequence = 0;
        stopReason = "";
        startedElapsed = clock.elapsedRealtimeMillis();
        startedWall = clock.wallTimeMillis();
        armedForegroundGeneration = -1L;
        admittedForegroundGeneration = -1;
        state = State.WAITING_FOR_GAME;
        sessionId = startedWall + "-" + UUID.randomUUID().toString().substring(0, 8);
        sessionDirectory = new File(new File(filesDirectory, "single-action"), sessionId);
        try {
            entryGate = suppliedEntryGate != null ? suppliedEntryGate
                    : new GameEntryGate(GameEntryGate.LAUNCH_GAME, platform.currentForegroundPackage(),
                            platform.foregroundGeneration(), startedElapsed);
            armedForegroundGeneration = entryGate.armedGeneration;
            if (!sessionDirectory.mkdirs()) throw new IOException("session_directory_unavailable");
            saveEvent("armed", null);
        } catch (IOException | RuntimeException error) {
            finish(token, State.STOPPED, "evidence_storage_unavailable");
            return false;
        }
        scheduler.postDelayed(() -> watchdog(token), 0L);
        return active;
    }

    public synchronized void cancel() {
        if (active) finish(State.CANCELLED, "cancelled");
    }

    public synchronized boolean isRunning() { return active; }
    public synchronized State state() { return state; }
    public synchronized File sessionDirectory() { return sessionDirectory; }
    public synchronized int gameInputs() { return gameInputs; }

    /**
     * Last, side-effect-free time check for the synchronous platform dispatch.
     * Call after potentially slow foreground queries and gesture construction,
     * immediately before dispatchGesture. It makes no foreground query, writes
     * no evidence, and invokes no listener; rejection must not be retried.
     */
    public synchronized boolean canDispatchPreparedTapNow() {
        if (!active || state != State.DISPATCHING || gameInputs != 1
                || dispatchReturned || capturePending || beforeInputFrameSequence <= 0
                || beforeInputFrameSequence != latestFrameSequence
                || pendingFrameSequence != latestFrameSequence || !foregroundAdmitted || entryGate == null
                || entryGate.checkCapture(clock.elapsedRealtimeMillis(), platform.foregroundGeneration()) != null) return false;
        long age = clock.wallTimeMillis() - lastCapturedAt;
        long elapsed = clock.elapsedRealtimeMillis() - startedElapsed;
        return age >= 0L && age <= frameAgeLimit()
                && elapsed >= 0L && elapsed < TIME_BUDGET_MS;
    }

    private long frameAgeLimit() { return nativePixels ? 5000L : MAX_FRAME_AGE_MS; }

    private synchronized boolean isCurrent(long token) {
        return active && token == generation;
    }

    /** Independent watchdog also stops a hung screenshot/gesture callback. */
    private synchronized void watchdog(long token) {
        if (!isCurrent(token) || !withinBudget(token)) return;
        try {
            if (!foregroundAdmitted) {
                String rejection = entryGate.check(platform.currentForegroundPackage(), platform.foregroundGeneration());
                if (rejection == null) {
                    admittedForegroundGeneration = entryGate.admittedGeneration();
                    foregroundAdmitted = true;
                    state = State.OBSERVING_MULLIGAN;
                    saveEvent("game_foreground_admitted", null);
                    scheduler.postDelayed(() -> capture(token), FOREGROUND_SETTLE_MS);
                } else if (!GameEntryGate.WAITING.equals(rejection)) {
                    finish(token, State.STOPPED, rejection);
                    return;
                }
            } else if (!foregroundStillCurrent()) {
                finish(token, State.STOPPED, "foreground_changed");
                return;
            }
        } catch (IOException | RuntimeException error) {
            finish(token, State.STOPPED, "foreground_or_evidence_failure");
            return;
        }
        if (isCurrent(token)) scheduler.postDelayed(() -> watchdog(token), WATCHDOG_INTERVAL_MS);
    }

    private boolean withinBudget(long token) {
        long now = clock.elapsedRealtimeMillis();
        long elapsed = now - startedElapsed;
        if (elapsed < 0L || elapsed >= TIME_BUDGET_MS) {
            finish(token, State.STOPPED, "time_budget");
            return false;
        }
        if (gameInputs == 1 && !opponentMulliganWaitObserved
                && (state == State.DISPATCHING || state == State.VERIFYING)) {
            long verificationElapsed = now - dispatchedAtElapsed;
            if (verificationElapsed < 0L || verificationElapsed >= POST_VERIFICATION_BUDGET_MS) {
                finish(token, State.STOPPED, "post_verification_timeout");
                return false;
            }
        }
        return true;
    }

    private boolean foregroundStillCurrent() {
        return foregroundAdmitted
                && entryGate.check(platform.currentForegroundPackage(), platform.foregroundGeneration()) == null
                && platform.foregroundGeneration() == admittedForegroundGeneration;
    }

    private boolean gate(long token) {
        if (!isCurrent(token) || !withinBudget(token)) return false;
        if (!foregroundStillCurrent()) {
            finish(token, State.STOPPED, "foreground_changed");
            return false;
        }
        // Foreground inspection itself may consume the remaining session/post-input budget.
        return isCurrent(token) && withinBudget(token);
    }

    private synchronized void capture(long token) {
        if (!isCurrent(token) || capturePending) return;
        try {
            if (!gate(token)) return;
            capturePending = true;
            long requestSequence = ++pendingFrameSequence;
            frameSource.requestFrame(new FrameSource.Callback() {
                @Override public void onFrame(FrameSnapshot snapshot) {
                    scheduler.postDelayed(() -> receiveFrame(token, requestSequence, snapshot), 0L);
                }
                @Override public void onFailure(String message) {
                    // Platform error messages are not copied into private evidence.
                    scheduler.postDelayed(() -> captureFailed(token, requestSequence, message), 0L);
                }
            });
        } catch (RuntimeException error) {
            if (isCurrent(token)) finish(token, State.STOPPED, "capture_request_failed");
        }
    }

    private synchronized void captureFailed(long token, long requestSequence,String reason) {
        if (isCurrent(token) && capturePending && requestSequence == pendingFrameSequence) {
            if("temporary_window_capture_error".equals(reason) && ++captureFailures<=3) {
                capturePending=false;previous=null;
                scheduler.postDelayed(() -> capture(token),350L);return;
            }
            if(GameWindowState.OCCLUDED.equals(reason)) {
                capturePending=false;previous=null;
                scheduler.postDelayed(() -> capture(token),300L);
                return;
            }
            finish(token, State.STOPPED, "capture_failed");
        }
    }

    private synchronized void receiveFrame(long token, long requestSequence, FrameSnapshot frame) {
        try {
            if (!isCurrent(token) || !capturePending || requestSequence != pendingFrameSequence) return;
            capturePending = false;
            captureFailures=0;
            if (!gate(token)) return;
            if (frame == null || !frame.isUsable() || (nativePixels ? !NativeFrameCoordinates.valid(frame.width(), frame.height(), frame.sourceWidth(), frame.sourceHeight())
                    : frame.width() != 1280 || frame.height() != 720)) {
                finish(token, State.STOPPED, "invalid_frame");
                return;
            }
            latestFrameSequence = requestSequence;
            long capturedAt = frame.capturedAtMillis();
            long age = clock.wallTimeMillis() - capturedAt;
            if (age < 0L || age > frameAgeLimit() || capturedAt < startedWall || capturedAt <= lastCapturedAt
                    || (gameInputs > 0 && capturedAt <= dispatchedAtWall)) {
                saveEvent("frame_rejected", json("frameSequence", requestSequence,
                        "frameAgeMillis", age, "reason", "stale_or_duplicate_frame"));
                finish(token, State.STOPPED, "stale_or_duplicate_frame");
                return;
            }
            lastCapturedAt = capturedAt;
            String frameName = String.format(Locale.ROOT, "frame-%04d", requestSequence);
            long persistStarted = clock.elapsedRealtimeMillis();
            File sourcePng = new File(sessionDirectory, frameName + ".png");
            savePng(sourcePng, frame.bitmap());
            long persistMillis = clock.elapsedRealtimeMillis() - persistStarted;
            JSONObject report = baseReport("frame");
            put(report, "frameSequence", requestSequence);
            put(report, "capturedAtMillis", capturedAt);
            put(report, "sourceWidth", frame.sourceWidth());
            put(report, "sourceHeight", frame.sourceHeight());
            put(report, "captureScope",frame.captureScope);
            put(report, "captureWindowId",frame.captureWindowId);
            put(report, "captureWindowBounds",new org.json.JSONArray().put(frame.captureBounds.left).put(frame.captureBounds.top)
                    .put(frame.captureBounds.width()).put(frame.captureBounds.height()));
            put(report, "width", frame.width());
            put(report, "height", frame.height());
            put(report, "screenshot", frameName + ".png");
            put(report, "observationPosition", gameInputs == 0 ? "before_input" : "after_input");
            put(report, "recognitionComplete", false);
            writeJson(new File(sessionDirectory, frameName + ".json"), report);
            if (!gate(token)) return;
            long inspectStarted = clock.elapsedRealtimeMillis();
            MulliganRecognizer.Result result = inspector.inspectSaved(frame.bitmap(), sourcePng);
            long inspectMillis = clock.elapsedRealtimeMillis() - inspectStarted;
            Evidence current = new Evidence(requestSequence, capturedAt, result, sample(frame.bitmap()), frame.width(), frame.height());
            Stability stability = compare(previous, current);
            boolean emptyOpeningFrame = current.phase == MulliganRecognizer.Phase.UNKNOWN
                    && gameInputs == 0 && state == State.OBSERVING_MULLIGAN
                    && isOpaqueBlackFrame(frame.bitmap());
            put(report, "recordedAtMillis", clock.wallTimeMillis());
            put(report, "elapsedMillis", Math.max(0L, clock.elapsedRealtimeMillis() - startedElapsed));
            put(report, "frameAgeMillis", clock.wallTimeMillis() - capturedAt);
            put(report, "recognitionComplete", true);
            put(report, "captureArrivalAgeMillis", age);
            put(report, "sourcePersistMillis", persistMillis);
            put(report, "inspectorMillis", inspectMillis);
            put(report, "phase", current.phase == null ? "UNKNOWN" : current.phase.name());
            put(report, "templateId", current.templateId);
            put(report, "score", result == null || !Double.isFinite(result.score)
                    ? JSONObject.NULL : result.score);
            put(report, "recognitionReason", result == null ? "missing_result" : result.reason);
            put(report, "confirmScore", result == null ? JSONObject.NULL : result.confirmScore);
            put(report, "titleScore", result == null ? JSONObject.NULL : result.titleScore);
            put(report, "endTurnScore", result == null ? JSONObject.NULL : result.endTurnScore);
            put(report, "targetBounds", rectJson(current.target));
            put(report, "stablePair", stability.stable);
            put(report, "meanChannelDelta", stability.comparable ? stability.mean : JSONObject.NULL);
            put(report, "changedSampleFraction", stability.comparable ? stability.changed : JSONObject.NULL);
            put(report, "pairedWithFrameSequence", previous == null ? 0L : previous.sequence);
            put(report, "emptyOpeningFrame", emptyOpeningFrame);
            writeJson(new File(sessionDirectory, frameName + ".json"), report);
            publish(report);
            if (!gate(token)) return;
            long processedFrameAge = clock.wallTimeMillis() - capturedAt;
            if (processedFrameAge < 0L || processedFrameAge > frameAgeLimit()) {
                if (nativePixels && processedFrameAge >= 0L) {
                    previous = null;
                    scheduler.postDelayed(() -> capture(token), SAMPLE_INTERVAL_MS);
                    return;
                }
                finish(token, State.STOPPED, "frame_expired_during_processing");
                return;
            }
            if (current.phase == MulliganRecognizer.Phase.WAITING_OPPONENT_MULLIGAN) {
                if (gameInputs != 1 || !dispatchAccepted || !dispatchReturned
                        || !gestureCompleted || gestureCancelled) {
                    finish(token, State.STOPPED, "opponent_mulligan_wait_without_completed_confirm");
                    return;
                }
                if (result == null || !Double.isFinite(result.score) || result.score < .90
                        || result.score > 1.0 || current.templateId.isEmpty()) {
                    finish(token, State.STOPPED, "invalid_recognition_result");
                    return;
                }
                // This is read-only waiting, never a turn handoff or another tap.
                // Only explicit current evidence can use the original total
                // deadline instead of the shorter post-input transition limit.
                if (!opponentMulliganWaitObserved) {
                    opponentMulliganWaitObserved = true;
                    firstOpponentMulliganWaitFrameSequence = current.sequence;
                    saveEvent("opponent_mulligan_wait_observed", json("frameSequence", current.sequence));
                }
                previous = null;
                if (isCurrent(token)) scheduler.postDelayed(() -> capture(token), SAMPLE_INTERVAL_MS);
                return;
            }
            if (current.phase == null || current.phase == MulliganRecognizer.Phase.UNKNOWN) {
                if (nativePixels) {
                    // Loading/animation or a missed label calls for a new image.
                    // The 90-second stage budget still bounds this observation loop.
                    previous = null;
                    scheduler.postDelayed(() -> capture(token), SAMPLE_INTERVAL_MS);
                    return;
                }
                if (emptyOpeningFrame) {
                    // A fully black capture can occur during the opening transition. It never
                    // authorizes input or preserves a stable pair, and does not reset the budget.
                    previous = null;
                    scheduler.postDelayed(() -> capture(token), SAMPLE_INTERVAL_MS);
                    return;
                }
                if (current.phase == MulliganRecognizer.Phase.UNKNOWN
                        && gameInputs == 1 && state == State.VERIFYING) {
                    // Deal/transition animation is read-only evidence, never permission to retry.
                    // A later confirmed frame must start a completely new stable pair.
                    previous = null;
                    scheduler.postDelayed(() -> capture(token), SAMPLE_INTERVAL_MS);
                    return;
                }
                finish(token, State.STOPPED, "unknown_screen");
                return;
            }
            if (result == null || !Double.isFinite(result.score) || result.score < 0.0
                    || result.score > 1.0 || current.templateId.isEmpty() || !validTarget(current.target,current.width,current.height)) {
                finish(token, State.STOPPED, "invalid_recognition_result");
                return;
            }
            if (gameInputs == 0) {
                if (current.phase != MulliganRecognizer.Phase.MULLIGAN_CONFIRM) {
                    finish(token, State.STOPPED,
                            current.phase == MulliganRecognizer.Phase.CONFIRMED_MY_TURN
                                    ? "already_my_turn_no_input" : "unexpected_phase_before_input");
                    return;
                }
                if (!validTarget(current.target,current.width,current.height)) {
                    finish(token, State.STOPPED, "invalid_confirm_target");
                    return;
                }
                if (stability.stable || nativePixels && result.score >= .90) {
                    dispatchOnce(token, current);
                    return;
                }
            } else if ((current.phase == MulliganRecognizer.Phase.CONFIRMED_MY_TURN
                    || current.phase == MulliganRecognizer.Phase.CONFIRMED_OPPONENT_TURN)
                    && (stability.stable || nativePixels && result.score >= .90) && dispatchAccepted && gestureCompleted && !gestureCancelled) {
                firstVerifiedFrameSequence = previous == null ? current.sequence : previous.sequence;
                secondVerifiedFrameSequence = current.sequence;
                verified = true;
                finish(token, State.VERIFIED, current.phase == MulliganRecognizer.Phase.CONFIRMED_OPPONENT_TURN
                        ? "opponent_turn_after_completed_confirm"
                        : nativePixels ? "current_my_turn_frame_after_completed_confirm" : "two_stable_my_turn_frames");
                return;
            }
            previous = current;
            if (isCurrent(token)) scheduler.postDelayed(() -> capture(token), SAMPLE_INTERVAL_MS);
        } catch (IOException | RuntimeException error) {
            if (isCurrent(token)) finish(token, State.STOPPED, "frame_processing_or_evidence_failure");
        } finally {
            if (frame != null) frame.close();
        }
    }

    private void dispatchOnce(long token, Evidence current) throws IOException {
        if (gameInputs != 0 || !preDispatchGate(token, current)) return;
        platform.prepareInput(release -> {
            try {
                if (gameInputs != 0 || !preDispatchGate(token,current)) return;
                dispatchPrepared(token,current,release);
            } catch(IOException | RuntimeException error) {
                if(isCurrent(token)) finish(token,State.STOPPED,"dispatch_preparation_error");
            } finally { if(!dispatchAccepted)release.run(); }
        });
    }

    private void dispatchPrepared(long token,Evidence current,Runnable release) throws IOException {
        float x = current.target.exactCenterX() / current.width;
        float y = current.target.exactCenterY() / current.height;
        // Evidence is flushed before reserving the single dispatch call.
        saveEvent("pre_dispatch", json("frameSequence", current.sequence,
                "previousFrameSequence", previous == null ? 0 : previous.sequence, "xNormalized", x,
                "yNormalized", y, "targetBounds", rectJson(current.target),
                "templateId", current.templateId, "capturedAtMillis", current.capturedAt,
                "frameAgeMillis", clock.wallTimeMillis() - current.capturedAt));
        if (!preDispatchGate(token, current)) return;
        beforeInputFrameSequence = current.sequence;
        previous = null;
        state = State.DISPATCHING;
        dispatchedAtWall = clock.wallTimeMillis();
        dispatchedAtElapsed = clock.elapsedRealtimeMillis();
        gameInputs = 1; // Conservative count of calls attempted, even if Android rejects one.
        boolean accepted;
        try {
            accepted = platform.dispatchTap(x, y, new TapCallback() {
                @Override public void onCompleted() {
                    release.run();
                    scheduler.postDelayed(() -> gestureResult(token, true), 0L);
                }
                @Override public void onCancelled() {
                    release.run();
                    scheduler.postDelayed(() -> gestureResult(token, false), 0L);
                }
            });
        } catch (RuntimeException error) {
            finish(token, State.STOPPED, "dispatch_exception");
            return;
        }
        if (!isCurrent(token)) return;
        dispatchReturned = true;
        dispatchAccepted = accepted;
        saveEvent("dispatch_result", null);
        if (!gate(token)) return;
        if (!accepted) {
            finish(token, State.STOPPED, "dispatch_rejected");
        } else if (gestureCancelled) {
            finish(token, State.STOPPED, "gesture_cancelled");
        } else if (gestureCompleted) {
            beginVerification(token);
        }
    }

    private boolean preDispatchGate(long token, Evidence current) {
        if (!gate(token)) return false;
        if(platform.inputOccluded()) {
            previous=null;scheduler.postDelayed(() -> capture(token),300L);return false;
        }
        long age = clock.wallTimeMillis() - current.capturedAt;
        if (gameInputs != 0 || capturePending || latestFrameSequence != current.sequence
                || pendingFrameSequence != current.sequence || age < 0L || age > frameAgeLimit()
                || current.phase != MulliganRecognizer.Phase.MULLIGAN_CONFIRM
                || !validTarget(current.target,current.width,current.height)) {
            finish(token, State.STOPPED, "pre_dispatch_guard_rejected");
            return false;
        }
        return true;
    }

    private synchronized void gestureResult(long token, boolean completed) {
        if (!isCurrent(token) || gameInputs != 1 || gestureCompleted || gestureCancelled) return;
        gestureCompleted = completed;
        gestureCancelled = !completed;
        try {
            if (!gate(token)) return;
            saveEvent(completed ? "gesture_completed_unverified" : "gesture_cancelled", null);
            if (!dispatchReturned) return;
            if (!completed || !dispatchAccepted) {
                finish(token, State.STOPPED, completed ? "dispatch_rejected" : "gesture_cancelled");
            } else {
                beginVerification(token);
            }
        } catch (IOException | RuntimeException error) {
            finish(token, State.STOPPED, "gesture_or_evidence_failure");
        }
    }

    private void beginVerification(long token) {
        if (!isCurrent(token) || state == State.VERIFYING) return;
        state = State.VERIFYING;
        scheduler.postDelayed(() -> capture(token), POST_TAP_SETTLE_MS);
    }

    private void finish(long token, State terminalState, String reason) {
        if (isCurrent(token)) finish(terminalState, reason);
    }

    private void finish(State terminalState, String reason) {
        if (!active) return;
        active = false;
        capturePending = false;
        previous = null;
        state = terminalState;
        stopReason = reason;
        generation++; // Invalidate pending frame, gesture, and timer callbacks before publishing.
        JSONObject summary = baseReport("finished");
        try {
            if (sessionDirectory != null && sessionDirectory.isDirectory()) {
                writeJson(new File(sessionDirectory, "summary.json"), summary);
            }
        } catch (IOException | RuntimeException error) {
            verified = false;
            state = State.STOPPED;
            stopReason = "summary_write_failed";
            put(summary, "verified", false);
            put(summary, "state", state.name());
            put(summary, "stopReason", stopReason);
            put(summary, "summaryWriteFailed", true);
        }
        publish(summary);
    }

    private JSONObject baseReport(String event) {
        JSONObject json = new JSONObject();
        put(json, "schemaVersion", 1);
        put(json, "sessionId", sessionId);
        put(json, "event", event);
        put(json, "actionScope", ACTION_SCOPE);
        put(json, "state", state.name());
        put(json, "active", active);
        put(json, "gameInputs", gameInputs);
        put(json, "gameInputsMeaning", "conservative_dispatch_attempt_count");
        put(json, "maxGameInputs", 1);
        put(json, "inputRetryAllowed", false);
        put(json, "dispatchAccepted", dispatchAccepted);
        put(json, "dispatchReturned", dispatchReturned);
        put(json, "gestureCompleted", gestureCompleted);
        put(json, "opponentMulliganWaitObserved", opponentMulliganWaitObserved);
        put(json, "firstOpponentMulliganWaitFrameSequence", firstOpponentMulliganWaitFrameSequence);
        put(json, "verified", verified);
        put(json, "stopReason", stopReason);
        put(json, "startedAtMillis", startedWall);
        put(json, "recordedAtMillis", clock.wallTimeMillis());
        put(json, "elapsedMillis", Math.max(0L, clock.elapsedRealtimeMillis() - startedElapsed));
        put(json, "timeBudgetMillis", TIME_BUDGET_MS);
        put(json, "postVerificationBudgetMillis", POST_VERIFICATION_BUDGET_MS);
        put(json, "postVerificationElapsedMillis", gameInputs == 1
                ? Math.max(0L, clock.elapsedRealtimeMillis() - dispatchedAtElapsed) : JSONObject.NULL);
        put(json, "frameFreshnessLimitMillis", frameAgeLimit());
        put(json, "maxMeanChannelDelta", MAX_MEAN_CHANNEL_DELTA);
        put(json, "maxChangedSampleFraction", MAX_CHANGED_SAMPLE_FRACTION);
        put(json, "minFrameSeparationMillis", MIN_FRAME_SEPARATION_MS);
        put(json, "armedForegroundGeneration", armedForegroundGeneration);
        put(json, "admittedForegroundGeneration", admittedForegroundGeneration);
        put(json, "entryMode", entryGate == null ? GameEntryGate.LAUNCH_GAME : entryGate.mode);
        put(json, "beforeInputFrameSequence", beforeInputFrameSequence);
        put(json, "latestFrameSequence", latestFrameSequence);
        put(json, "firstVerifiedFrameSequence", firstVerifiedFrameSequence);
        put(json, "secondVerifiedFrameSequence", secondVerifiedFrameSequence);
        put(json, "dispatchedAtMillis", dispatchedAtWall);
        put(json, "dispatchedAtElapsedMillis", dispatchedAtElapsed);
        put(json, "boardActionAuthorized", false);
        return json;
    }

    private void saveEvent(String event, JSONObject detail) throws IOException {
        JSONObject report = baseReport(event);
        if (detail != null) put(report, "detail", detail);
        File file = new File(sessionDirectory,
                String.format(Locale.ROOT, "event-%04d-%s.json", ++eventSequence, event));
        writeJson(file, report);
        publish(report);
    }

    private void publish(JSONObject report) {
        if (onReport == null) return;
        try { onReport.accept(report.toString()); }
        catch (RuntimeException ignored) { /* A view callback cannot grant or repeat input. */ }
    }

    private static void writeJson(File file, JSONObject json) throws IOException {
        try (FileOutputStream stream = new FileOutputStream(file, false)) {
            stream.write(json.toString().getBytes(StandardCharsets.UTF_8));
            stream.flush();
            stream.getFD().sync();
        }
    }

    private void savePng(File file, Bitmap bitmap) throws IOException {
        try (FileOutputStream stream = new FileOutputStream(file, false)) {
            if(nativePixels)OriginalPng.write(bitmap,stream);
            else if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, stream)) {
                throw new IOException("png_write_failed");
            }
            stream.flush();
            stream.getFD().sync();
        }
    }

    private static boolean validTarget(Rect rect) { return validTarget(rect,1280,720); }

    private static boolean validTarget(Rect rect, int width, int height) {
        return rect != null && rect.width() > 0 && rect.height() > 0
                && rect.left >= 0 && rect.top >= 0 && rect.right <= width && rect.bottom <= height;
    }

    private static int[] sample(Bitmap bitmap) {
        int[] pixels = new int[SAMPLE_COLUMNS * SAMPLE_ROWS];
        for (int y = 0; y < SAMPLE_ROWS; y++) {
            for (int x = 0; x < SAMPLE_COLUMNS; x++) {
                pixels[y * SAMPLE_COLUMNS + x] = bitmap.getPixel(
                        (x * bitmap.getWidth() + bitmap.getWidth() / 2) / SAMPLE_COLUMNS,
                        (y * bitmap.getHeight() + bitmap.getHeight() / 2) / SAMPLE_ROWS);
            }
        }
        return pixels;
    }

    private static boolean isOpaqueBlackFrame(Bitmap bitmap) {
        // Check every pixel: sparse stability samples must not hide a small dialog or control.
        int[] row = new int[bitmap.getWidth()];
        for (int y = 0; y < bitmap.getHeight(); y++) {
            bitmap.getPixels(row, 0, row.length, 0, y, row.length, 1);
            for (int pixel : row) {
                if (pixel != 0xff000000) return false;
            }
        }
        return true;
    }

    private static Stability compare(Evidence before, Evidence after) {
        if (before == null || before.phase != after.phase || before.templateId.isEmpty()
                || !before.templateId.equals(after.templateId)
                || after.sequence <= before.sequence
                || after.capturedAt - before.capturedAt < MIN_FRAME_SEPARATION_MS
                || before.width != after.width || before.height != after.height
                || !sameTarget(before.target, after.target, after.width, after.height)) return new Stability(false, false, 0, 0);
        long delta = 0;
        int changed = 0;
        for (int i = 0; i < after.pixels.length; i++) {
            int a = before.pixels[i];
            int b = after.pixels[i];
            int red = Math.abs(((a >> 16) & 255) - ((b >> 16) & 255));
            int green = Math.abs(((a >> 8) & 255) - ((b >> 8) & 255));
            int blue = Math.abs((a & 255) - (b & 255));
            delta += red + green + blue;
            if (Math.max(red, Math.max(green, blue)) > CHANGED_PIXEL_DELTA) changed++;
        }
        double mean = delta / (after.pixels.length * 3.0);
        double fraction = changed / (double) after.pixels.length;
        return new Stability(true, mean <= MAX_MEAN_CHANNEL_DELTA
                && fraction <= MAX_CHANGED_SAMPLE_FRACTION, mean, fraction);
    }

    private static boolean sameTarget(Rect a, Rect b, int width, int height) {
        return validTarget(a,width,height) && validTarget(b,width,height)
                && Math.abs(a.left - b.left) <= MAX_TARGET_MOVEMENT_PX
                && Math.abs(a.top - b.top) <= MAX_TARGET_MOVEMENT_PX
                && Math.abs(a.right - b.right) <= MAX_TARGET_MOVEMENT_PX
                && Math.abs(a.bottom - b.bottom) <= MAX_TARGET_MOVEMENT_PX;
    }

    private static Object rectJson(Rect r) {
        return r == null ? JSONObject.NULL
                : json("left", r.left, "top", r.top, "right", r.right, "bottom", r.bottom);
    }

    private static JSONObject json(Object... pairs) {
        JSONObject result = new JSONObject();
        for (int i = 0; i < pairs.length; i += 2) put(result, (String) pairs[i], pairs[i + 1]);
        return result;
    }

    private static void put(JSONObject object, String key, Object value) {
        try { object.put(key, value == null ? JSONObject.NULL : value); }
        catch (JSONException error) { throw new IllegalArgumentException("Invalid report field", error); }
    }

    private static final class Evidence {
        final long sequence;
        final long capturedAt;
        final MulliganRecognizer.Phase phase;
        final String templateId;
        final Rect target;
        final int[] pixels;
        final int width, height;
        Evidence(long sequence, long capturedAt, MulliganRecognizer.Result result, int[] pixels, int width, int height) {
            this.width=width;this.height=height;
            this.sequence = sequence;
            this.capturedAt = capturedAt;
            this.phase = result == null ? null : result.phase;
            this.templateId = result == null || result.templateId == null ? "" : result.templateId;
            this.target = result == null || result.targetBounds == null ? null : new Rect(result.targetBounds);
            this.pixels = pixels;
        }
    }

    private static final class Stability {
        final boolean comparable;
        final boolean stable;
        final double mean;
        final double changed;
        Stability(boolean comparable, boolean stable, double mean, double changed) {
            this.comparable = comparable;
            this.stable = stable;
            this.mean = mean;
            this.changed = changed;
        }
    }
}
