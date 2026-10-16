package com.kards.mobilert;

import org.json.JSONObject;

import java.util.HashSet;
import java.util.Set;

/** One campaign's foreground admission, shared by opening and battle. No device I/O. */
final class GameEntryGate {
    static final String LAUNCH_GAME = "launch_game";
    static final String CURRENT_GAME = "current_game";
    static final String WAITING = "waiting_for_new_game_foreground";
    static final String RECAPTURE = "bootstrap_window_changed";
    private static final String GAME = "com.android1939.kards";

    final String mode;
    final String armedPackage;
    final long armedGeneration;
    final long armedElapsed;
    private long admittedGeneration = -1;
    private boolean invalidated;
    private boolean bootstrapEnabled;
    private boolean bootstrapSealed;
    private long bootstrapDepartureEpoch = -1;
    private int bootstrapRebindings;
    private final Set<Long> bootstrapGenerations = new HashSet<>();

    static String parseMode(JSONObject options) {
        Object value = options.has("entry_mode") ? options.opt("entry_mode") : LAUNCH_GAME;
        if (!(value instanceof String)
                || !(LAUNCH_GAME.equals(value) || CURRENT_GAME.equals(value))) {
            throw new IllegalArgumentException("invalid_entry_mode");
        }
        return (String) value;
    }

    GameEntryGate(String mode, String foreground, long generation, long elapsed) {
        if (!(LAUNCH_GAME.equals(mode) || CURRENT_GAME.equals(mode))) {
            throw new IllegalArgumentException("invalid_entry_mode");
        }
        if (generation < 0 || elapsed < 0) throw new IllegalArgumentException("invalid_entry_snapshot");
        if (CURRENT_GAME.equals(mode) && !GAME.equals(foreground)) {
            throw new IllegalArgumentException("current_game_not_foreground");
        }
        this.mode = mode;
        armedPackage = foreground == null ? "" : foreground;
        armedGeneration = generation;
        armedElapsed = elapsed;
        if (CURRENT_GAME.equals(mode)) admittedGeneration = generation;
    }

    /** Only launch mode can admit a later entry, and only once. */
    synchronized String check(String foreground, long generation) {
        if (invalidated) return "foreground_changed";
        if (admittedGeneration < 0) {
            if (!GAME.equals(foreground) || generation <= armedGeneration) return WAITING;
            admittedGeneration = generation;
        }
        if (!GAME.equals(foreground) || generation != admittedGeneration) {
            invalidated = true;
            return "foreground_changed";
        }
        return null;
    }

    /** Enable only for the first launch menu, before any game input or admission. */
    synchronized void enableBootstrap(long departureEpoch) {
        if (departureEpoch < 0) throw new IllegalArgumentException("invalid_departure_epoch");
        if (!LAUNCH_GAME.equals(mode) || bootstrapEnabled || bootstrapSealed
                || invalidated || admittedGeneration >= 0) {
            throw new IllegalStateException("bootstrap_requires_unadmitted_launch");
        }
        bootstrapEnabled = true;
        bootstrapDepartureEpoch = departureEpoch;
    }

    /**
     * During an input-free launch, same-package startup windows may replace one another.
     * The independent departure epoch must prove that no other application took over.
     */
    synchronized String check(String foreground, long generation, long departureEpoch) {
        if (!bootstrapEnabled || bootstrapSealed) return check(foreground, generation);
        if (invalidated) return "foreground_changed";
        if (departureEpoch != bootstrapDepartureEpoch) return invalidate();
        if (foreground == null || foreground.isEmpty()) return WAITING;
        if (!GAME.equals(foreground)) {
            if (admittedGeneration < 0 && armedPackage.equals(foreground)) return WAITING;
            return invalidate();
        }
        if (admittedGeneration < 0 && generation <= armedGeneration) return WAITING;
        if (admittedGeneration >= 0 && generation < admittedGeneration) return invalidate();
        if (generation != admittedGeneration) {
            if (admittedGeneration >= 0) bootstrapRebindings++;
            admittedGeneration = generation;
            bootstrapGenerations.add(generation);
        }
        return null;
    }

    /** Must be called before dispatching the first real game input. */
    synchronized void sealBootstrap() { bootstrapSealed = true; }

    /** A startup window can disappear while an asynchronous screenshot is in flight. */
    synchronized String captureFailureReason(String reason, String foreground, long generation,
                                            long departureEpoch) {
        String rejection = check(foreground, generation, departureEpoch);
        if (rejection != null && !WAITING.equals(rejection)) return rejection;
        if (bootstrapEnabled && !bootstrapSealed
                && ("game_window_missing".equals(reason) || "game_window_changed".equals(reason))) {
            return RECAPTURE;
        }
        return reason;
    }

    private String invalidate() {
        invalidated = true;
        return "foreground_changed";
    }

    synchronized boolean isAdmitted() { return admittedGeneration >= 0; }
    synchronized long admittedGeneration() { return admittedGeneration; }

    synchronized String checkCapture(long requestedElapsed, long generation) {
        if (invalidated) return "foreground_changed";
        if (admittedGeneration < 0) return bootstrapEnabled && !bootstrapSealed
                ? RECAPTURE : "foreground_changed";
        if (generation != admittedGeneration) return bootstrapGenerations.contains(generation)
                ? RECAPTURE : "foreground_changed";
        return requestedElapsed < armedElapsed ? "capture_before_arming" : null;
    }

    synchronized JSONObject evidence() throws Exception {
        return new JSONObject().put("entry_mode", mode).put("armed_package", armedPackage)
                .put("armed_generation", armedGeneration).put("armed_elapsed_ms", armedElapsed)
                .put("admitted_generation", admittedGeneration).put("invalidated", invalidated)
                .put("bootstrap_enabled", bootstrapEnabled).put("bootstrap_sealed", bootstrapSealed)
                .put("bootstrap_departure_epoch", bootstrapDepartureEpoch)
                .put("bootstrap_rebindings", bootstrapRebindings);
    }
}
