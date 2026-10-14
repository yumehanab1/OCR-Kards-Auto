package com.kards.mobilert;

import org.json.JSONObject;

/** Java-owned menu options; never passed to the battle engine's strict option parser. */
final class MatchEntryOptions {
    static final String TRAINING = "training";
    static final String CASUAL = "casual";
    static final String RANKED = "ranked";

    private MatchEntryOptions() { }

    static String parseMode(JSONObject options) {
        Object value = options.has("match_mode") ? options.opt("match_mode") : TRAINING;
        if (!(value instanceof String) || !(TRAINING.equals(value) || CASUAL.equals(value)
                || RANKED.equals(value))) throw new IllegalArgumentException("invalid_match_mode");
        if (!TRAINING.equals(value)) {
            Object readOnly = options.has("read_only") ? options.opt("read_only") : Boolean.FALSE;
            if (!(readOnly instanceof Boolean)) throw new IllegalArgumentException("invalid_read_only");
            if (Boolean.TRUE.equals(readOnly)) throw new IllegalArgumentException("read_only_match_entry_forbidden");
        }
        return (String) value;
    }

    static boolean isMenuReady(JSONObject result, String expectedMode) {
        return result != null && (CASUAL.equals(expectedMode) || RANKED.equals(expectedMode))
                && expectedMode.equals(result.opt("mode"))
                && Boolean.TRUE.equals(result.opt("verified"))
                && Boolean.TRUE.equals(result.opt("queue_requested"))
                && Boolean.TRUE.equals(result.opt("first_deck_selected"))
                && "mulligan_ready".equals(result.opt("reason"));
    }

    static JSONObject runtimeOptions(JSONObject options) throws Exception {
        JSONObject result = new JSONObject(options.toString());
        // Campaign-level keys are owned by this boundary; the embedded engine
        // accepts only its own documented option names and rejects anything
        // else, so every session-only key must be dropped here.
        result.remove("entry_mode");
        result.remove("start_with_opening");
        result.remove("match_mode");
        result.remove("post_match_settle");
        result.remove("settle_points");
        result.remove("match_count");
        result.remove("debug_stage");
        result.remove("native_menu");
        result.remove("native_observe_only");
        result.remove("retain_full_evidence");
        return result;
    }
}
