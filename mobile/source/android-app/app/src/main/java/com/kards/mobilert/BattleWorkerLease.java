package com.kards.mobilert;

/**
 * Process-wide ownership of Python's shared mobile-core module state.
 *
 * <p>A Service instance can disappear while its worker is still unwinding.
 * Its replacement must not start another worker until the actual owner has
 * exited. Cancellation alone must therefore never release a running worker's
 * lease. Use a unique session object as the token; tokens compare by identity.
 */
final class BattleWorkerLease {
    private static Object owner;
    private static String ownerSessionId = "";
    private static Thread worker;

    /** Immutable facts taken under the same lock as claims and releases. */
    static final class Snapshot {
        final Object ownerToken;
        final String sessionId;
        final String workerState;
        final String workerName;
        final Object recoveredToken;
        final String recoveredSessionId;

        private Snapshot(Object recoveredToken, String recoveredSessionId) {
            this.ownerToken = owner;
            this.sessionId = ownerSessionId;
            this.workerState = owner == null ? "NONE" : worker == null ? "UNBOUND" : worker.getState().name();
            this.workerName = worker == null ? "" : worker.getName();
            this.recoveredToken = recoveredToken;
            this.recoveredSessionId = recoveredSessionId;
        }

        boolean isOwned() { return ownerToken != null; }
    }

    private BattleWorkerLease() { }

    /** A repeated claim by the same token is also rejected: one claim, one worker. */
    static synchronized boolean tryClaim(Object candidate) {
        return tryClaim(candidate, "");
    }

    static synchronized boolean tryClaim(Object candidate, String sessionId) {
        if (candidate == null) throw new IllegalArgumentException("owner must not be null");
        reclaimTerminatedWorker();
        if (owner != null) return false;
        owner = candidate;
        ownerSessionId = sessionId == null ? "" : sessionId;
        return true;
    }

    /** Bind before Thread.start(). An unstarted or unbound claim cannot expire. */
    static synchronized boolean bindWorker(Object candidate, Thread candidateWorker) {
        if (candidate == null || owner != candidate || worker != null || candidateWorker == null
                || candidateWorker.getState() != Thread.State.NEW) return false;
        worker = candidateWorker;
        return true;
    }

    /** Only the exact owner may release; a stale callback cannot release a new session. */
    static synchronized boolean release(Object candidate) {
        if (candidate == null || owner != candidate) return false;
        // A UI cancellation/report can happen while Python is still unwinding.
        // Only that worker's own finally may release a live bound worker.
        if (worker != null && worker != Thread.currentThread()
                && worker.getState() != Thread.State.NEW && worker.getState() != Thread.State.TERMINATED) return false;
        clear();
        return true;
    }

    static synchronized boolean isOwned() { return snapshot().isOwned(); }

    static synchronized boolean isOwnedBy(Object candidate) {
        reclaimTerminatedWorker();
        return candidate != null && owner == candidate;
    }

    static synchronized Snapshot snapshot() {
        Object recoveredToken = owner != null && worker != null
                && worker.getState() == Thread.State.TERMINATED ? owner : null;
        String recoveredSessionId = recoveredToken == null ? "" : ownerSessionId;
        reclaimTerminatedWorker();
        return new Snapshot(recoveredToken, recoveredSessionId);
    }

    private static void reclaimTerminatedWorker() {
        // No wall clock timeout: WAITING/BLOCKED Python still owns shared state.
        if (owner != null && worker != null && worker.getState() == Thread.State.TERMINATED) clear();
    }

    private static void clear() {
        owner = null;
        ownerSessionId = "";
        worker = null;
    }
}
