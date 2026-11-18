package com.kards.mobilert;

/** One capture call shares a bounded retry budget across transient pixel failures. */
final class CaptureRetryPolicy {
    static final int MAX_RETRIES = 3;
    private int retriesUsed;

    // Separate campaign-wide allowance for a cold game's input-free loading gap.
    // Each attempt still creates a new source request with its own 1500ms deadline.
    static final int MAX_STARTUP_TIMEOUT_RETRIES = 16;
    static final long STARTUP_TIMEOUT_WINDOW_MS = 30_000L;
    private int startupTimeoutRetries;
    private long firstStartupTimeout = -1L;

    boolean retryStartupTimeout(String reason, boolean startupMenu, long inputs,
                                boolean cancelled, boolean budgetExpired, long now) {
        if (!startupMenu || inputs != 0 || cancelled || budgetExpired || now < 0
                || !("compat_capture_timeout".equals(reason)
                    || (reason != null && reason.endsWith("（compat_capture_timeout）")))) return false;
        if (firstStartupTimeout < 0) firstStartupTimeout = now;
        if (now < firstStartupTimeout || now - firstStartupTimeout >= STARTUP_TIMEOUT_WINDOW_MS
                || startupTimeoutRetries >= MAX_STARTUP_TIMEOUT_RETRIES) return false;
        startupTimeoutRetries++;
        return true;
    }

    int startupTimeoutRetries() { return startupTimeoutRetries; }

    static final class Decision {
        final boolean retry;
        final boolean exhausted;
        final String reason;
        final int retriesUsed;

        Decision(boolean retry, boolean exhausted, String reason, int retriesUsed) {
            this.retry = retry;
            this.exhausted = exhausted;
            this.reason = reason;
            this.retriesUsed = retriesUsed;
        }
    }

    Decision onFailure(String reason, boolean cancelled, boolean budgetExpired) {
        if (cancelled) return stop("cancelled", false);
        if (budgetExpired) return stop("time_budget", false);
        if (!isRetryable(reason)) return stop(reason, false);
        if (retriesUsed >= MAX_RETRIES) {
            return stop("temporary_window_capture_error".equals(reason)
                    ? "window_capture_retry_exhausted" : reason, true);
        }
        retriesUsed++;
        return new Decision(true, false, reason, retriesUsed);
    }

    static boolean isRetryable(String reason) {
        return "temporary_window_capture_error".equals(reason)
                || "capture_black_frame".equals(reason)
                || "compat_capture_incomplete_frame".equals(reason);
    }

    private Decision stop(String reason, boolean exhausted) {
        return new Decision(false, exhausted, reason, retriesUsed);
    }
}
