package com.kards.mobilert;

import java.util.List;

/** Positive metadata evidence of leaving the game; window churn is not a departure. */
final class ForegroundDepartureTracker {
    private long epoch;
    private String departureFact = "";

    long epoch() { return epoch; }

    long observe(List<GameWindowState.Window> windows, boolean locked) {
        GameWindowState.Window externalApplication = null;
        boolean currentGame = false;
        for (GameWindowState.Window window : windows) {
            if (window.ownOverlay || window.type != 1 || window.bounds.isEmpty()
                    || (!window.active && !window.focused) || window.owner == null
                    || window.owner.isEmpty() || "com.android.systemui".equals(window.owner)) continue;
            if (GamePackages.isGame(window.owner)) currentGame = true;
            else if (externalApplication == null || window.layer > externalApplication.layer
                    || (window.layer == externalApplication.layer
                    && window.owner.compareTo(externalApplication.owner) > 0)) externalApplication = window;
        }
        if (locked || externalApplication != null) {
            String fact = locked ? "locked" : "external:" + externalApplication.owner;
            if (!fact.equals(departureFact)) epoch++;
            departureFact = fact;
        } else if (currentGame) {
            departureFact = "";
        }
        // Unknown/empty inventories and SystemUI preserve the last fact. They
        // cannot manufacture a return, or hide a different external app/lock.
        return epoch;
    }
}
