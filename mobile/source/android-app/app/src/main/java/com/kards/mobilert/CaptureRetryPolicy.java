package com.kards.mobilert;

/** One capture call shares a bounded retry budget across transient pixel failures. */
final class CaptureRetryPolicy {
    static final int MAX_RETRIES = 3;
    private int retriesUsed;

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
