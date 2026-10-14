package com.kards.mobilert;

import org.json.JSONObject;

/** One campaign's foreground admission, shared by opening and battle. No device I/O. */
final class GameEntryGate {
    static final String LAUNCH_GAME = "launch_game";
    static final String CURRENT_GAME = "current_game";
    static final String WAITING = "waiting_for_new_game_foreground";
    private static final String GAME = "com.android1939.kards";

    final String mode;
    final String armedPackage;
    final long armedGeneration;
    final long armedElapsed;
    private long admittedGeneration = -1;
    private boolean invalidated;

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

    synchronized boolean isAdmitted() { return admittedGeneration >= 0; }
    synchronized long admittedGeneration() { return admittedGeneration; }

    synchronized String checkCapture(long requestedElapsed, long generation) {
        if (invalidated || admittedGeneration < 0 || generation != admittedGeneration) {
            return "foreground_changed";
        }
        return requestedElapsed < armedElapsed ? "capture_before_arming" : null;
    }

    synchronized JSONObject evidence() throws Exception {
        return new JSONObject().put("entry_mode", mode).put("armed_package", armedPackage)
                .put("armed_generation", armedGeneration).put("armed_elapsed_ms", armedElapsed)
                .put("admitted_generation", admittedGeneration).put("invalidated", invalidated);
    }
}
