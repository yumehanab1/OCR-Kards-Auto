package com.kards.mobilert;

/** Shared, tested eligibility rules for the continuously attached consent-owned producer. */
final class ProjectionFramePolicy {
    private ProjectionFramePolicy() { }

    static boolean fresh(long freshAfterNanos, long imageTimestampNanos) {
        return freshAfterNanos > 0L && imageTimestampNanos > freshAfterNanos;
    }

    static boolean ready(boolean closed, boolean liveGeometryMatches) {
        return !closed && liveGeometryMatches;
    }

    static boolean deliver(boolean closed, long nowUptime, long deadlineUptime) {
        return !closed && nowUptime < deadlineUptime;
    }

    static boolean recoverLogicalMirror(int api, boolean closed, boolean naturalBuffer,
                                        boolean attempted) {
        return api < 34 && !closed && naturalBuffer && !attempted;
    }

    static boolean awaitLogicalLayout(boolean closed, boolean recoveryAttempted,
                                      long nowUptime, long deadlineUptime) {
        return recoveryAttempted && deliver(closed, nowUptime, deadlineUptime);
    }

    static boolean prepareIdleGeometry(int api, boolean closed, boolean requestActive,
                                       long nowUptime, long preparationDeadlineUptime) {
        return api < 34 && !requestActive && deliver(closed, nowUptime, preparationDeadlineUptime);
    }

    static boolean useConsentSource(int api, boolean sourceExists) {
        return api < 34 && sourceExists;
    }
}
