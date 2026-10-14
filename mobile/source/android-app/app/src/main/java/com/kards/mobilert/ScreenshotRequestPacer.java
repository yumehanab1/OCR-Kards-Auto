package com.kards.mobilert;

/** Shared admission of native screenshot attempts, using the monotonic clock. */
final class ScreenshotRequestPacer {
    static final long MIN_INTERVAL_MS = 400;
    private long lastAttemptMs = -1;

    /** Zero admits a new attempt; a positive delay does not consume a slot. */
    synchronized long acquireDelay(long nowMs) {
        if (nowMs < 0) throw new IllegalArgumentException("negative screenshot clock");
        if (lastAttemptMs >= 0) {
            if (nowMs < lastAttemptMs) return MIN_INTERVAL_MS;
            long elapsed = nowMs - lastAttemptMs;
            if (elapsed < MIN_INTERVAL_MS) return MIN_INTERVAL_MS - elapsed;
        }
        lastAttemptMs = nowMs;
        return 0;
    }
}
