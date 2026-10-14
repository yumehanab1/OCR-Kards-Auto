package com.kards.mobilert;

import android.os.Handler;
import android.os.Looper;

import java.util.function.Consumer;

/**
 * Bounded read-only polling loop for the APK shell.
 *
 * <p>Each tick requests a fresh accessibility screenshot, observes it, emits
 * contract JSON, and schedules the next tick only after the callback returns.
 * There is deliberately no action planner or gesture call here.  Stopping the
 * loop also prevents a pending callback from scheduling another tick.</p>
 */
public final class ReadOnlyObservationLoop {
    public static final long DEFAULT_INTERVAL_MS = 1000L;

    private final FrameSource service;
    private final MobileCore core;
    private final Handler handler;
    private final long intervalMillis;
    private final Consumer<String> onObservation;
    private final Consumer<String> onFailure;
    private boolean running;
    private boolean capturePending;
    private long generation;

    public ReadOnlyObservationLoop(FrameSource service,
                                   MobileCore core,
                                   Consumer<String> onObservation,
                                   Consumer<String> onFailure) {
        this(service, core, DEFAULT_INTERVAL_MS, onObservation, onFailure);
    }

    public ReadOnlyObservationLoop(FrameSource service,
                                   MobileCore core,
                                   long intervalMillis,
                                   Consumer<String> onObservation,
                                   Consumer<String> onFailure) {
        this.service = service;
        this.core = core == null ? new ReadOnlyMobileCore() : core;
        this.intervalMillis = Math.max(250L, intervalMillis);
        this.onObservation = onObservation;
        this.onFailure = onFailure;
        this.handler = new Handler(Looper.getMainLooper());
    }

    public synchronized boolean isRunning() {
        return running;
    }

    public synchronized void start() {
        if (running) return;
        running = true;
        capturePending = false;
        long startedGeneration = ++generation;
        handler.post(() -> tick(startedGeneration));
    }

    public synchronized void stop() {
        running = false;
        capturePending = false;
        generation++;
        handler.removeCallbacksAndMessages(null);
    }

    private void tick(long captureGeneration) {
        synchronized (this) {
            if (!isCurrent(captureGeneration) || capturePending) return;
            capturePending = true;
            if (service == null) {
                running = false;
                capturePending = false;
                if (onFailure != null) onFailure.accept("无障碍服务不可用；只读观察已停止");
                return;
            }
        }
        service.requestFrame(new FrameSource.Callback() {
            @Override
            public void onFrame(FrameSnapshot snapshot) {
                try {
                    if (!isCurrent(captureGeneration)) return;
                    BoardObservation observation = core.observe(snapshot);
                    String json = BoardObservationJson.toJson(observation, snapshot,
                            System.currentTimeMillis());
                    synchronized (ReadOnlyObservationLoop.this) {
                        if (isCurrent(captureGeneration) && onObservation != null) {
                            onObservation.accept(json);
                        }
                    }
                } catch (RuntimeException error) {
                    publishFailure(captureGeneration, "只读观察失败，本轮不执行动作："
                            + error.getClass().getSimpleName());
                } finally {
                    snapshot.close();
                    completeCapture(captureGeneration);
                }
            }

            @Override
            public void onFailure(String message) {
                try {
                    publishFailure(captureGeneration, message);
                } finally {
                    completeCapture(captureGeneration);
                }
            }
        });
    }

    private synchronized boolean isCurrent(long captureGeneration) {
        return running && generation == captureGeneration;
    }

    private synchronized void publishFailure(long captureGeneration, String message) {
        if (isCurrent(captureGeneration) && onFailure != null) {
            onFailure.accept(message == null
                    ? "截图失败，本轮不执行动作；稍后重试" : message);
        }
    }

    private synchronized void completeCapture(long captureGeneration) {
        if (!isCurrent(captureGeneration)) return;
        capturePending = false;
        handler.postDelayed(() -> tick(captureGeneration), intervalMillis);
    }
}
