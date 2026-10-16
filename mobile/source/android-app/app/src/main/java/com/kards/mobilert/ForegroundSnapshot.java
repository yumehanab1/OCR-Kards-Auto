package com.kards.mobilert;

/** Final facts from a single fresh metadata scan; never reused across input boundaries. */
final class ForegroundSnapshot {
    final String foregroundPackage;
    final long generation;
    final long departureEpoch;
    final GameWindowState windowState;
    final long elapsedRealtimeMs;

    ForegroundSnapshot(String foregroundPackage,long generation,long departureEpoch,
                       GameWindowState windowState,long elapsedRealtimeMs) {
        this.foregroundPackage=foregroundPackage;
        this.generation=generation;
        this.departureEpoch=departureEpoch;
        this.windowState=windowState;
        this.elapsedRealtimeMs=elapsedRealtimeMs;
    }
}
