package com.kards.mobilert;

import org.json.JSONObject;

/** Bounded display/transport only. Full ledgers remain the campaign policy's input. */
final class BattleProgressReport {
    static final String KIND = "campaign_progress_v1";
    static final int MAX_UTF16_BYTES = 16 * 1024;
    private static final int MAX_TEXT_CHARS = 512;

    private BattleProgressReport() { }

    /** Updated once for each closed round, using its complete original evidence. */
    static final class RoundTotals {
        private long closed;
        private boolean allSafe = true;
        private long turns, actions, unknown, skipped;
        private boolean turnsKnown = true, actionsKnown = true, unknownKnown = true, skippedKnown = true;
        private boolean qualityKnown = true, allQualityPassed = true;

        void add(JSONObject row) {
            JSONObject engine = row == null ? null : row.optJSONObject("engine");
            JSONObject settle = row == null ? null : row.optJSONObject("settle");
            allSafe &= row != null && integer(row.opt("round_index")) == closed + 1
                    && !Boolean.TRUE.equals(row.opt("input_status_uncertain"))
                    && MatchCampaignPlan.resultConfirmed(engine) && MatchCampaignPlan.returned(settle)
                    && MatchCampaignPlan.continuationEvidence(engine).safe
                    && !(engine.has("exception") && !engine.isNull("exception"));
            closed++;
            long value = count(engine, "engine_turns_seen");
            turnsKnown &= value >= 0 && turns <= Long.MAX_VALUE - Math.max(0, value);
            if (turnsKnown) turns += value;
            value = count(engine, "actions_confirmed");
            actionsKnown &= value >= 0 && actions <= Long.MAX_VALUE - Math.max(0, value);
            if (actionsKnown) actions += value;
            value = count(engine, "unconfirmed_inputs");
            unknownKnown &= value >= 0 && unknown <= Long.MAX_VALUE - Math.max(0, value);
            if (unknownKnown) unknown += value;
            value = count(engine, "unconfirmed_skipped");
            skippedKnown &= value >= 0 && skipped <= Long.MAX_VALUE - Math.max(0, value);
            if (skippedKnown) skipped += value;
            Object quality = engine == null ? null : engine.opt("full_game_passed");
            qualityKnown &= quality instanceof Boolean;
            if (Boolean.FALSE.equals(quality)) allQualityPassed = false;
        }

        JSONObject snapshot() throws Exception {
            return new JSONObject().put("closed_round_count", closed)
                    .put("all_closed_rounds_safe", closed > 0 && allSafe)
                    .put("engine_turns_seen", closed > 0 && turnsKnown ? turns : JSONObject.NULL)
                    .put("actions_confirmed", closed > 0 && actionsKnown ? actions : JSONObject.NULL)
                    .put("unconfirmed_inputs", closed > 0 && unknownKnown ? unknown : JSONObject.NULL)
                    .put("unconfirmed_skipped", closed > 0 && skippedKnown ? skipped : JSONObject.NULL)
                    .put("full_game_passed", !allQualityPassed ? false
                            : closed > 0 && qualityKnown ? true : JSONObject.NULL);
        }

        boolean complete(JSONObject campaign) {
            long target = integer(campaign.opt("match_count"));
            return target > 0 && closed == target && integer(campaign.opt("completed_matches")) == target
                    && Boolean.FALSE.equals(campaign.opt("active"))
                    && "finished".equals(campaign.opt("event"))
                    && "campaign_complete".equals(campaign.opt("reason"))
                    && !Boolean.TRUE.equals(campaign.opt("input_status_uncertain")) && allSafe;
        }
    }

    static String project(JSONObject campaign, RoundTotals totals) throws Exception {
        JSONObject progress = new JSONObject().put("report_kind", KIND);
        copy(progress, campaign, "event", "active", "session_id", "directory", "elapsed_ms", "reason",
                "game_inputs", "frames", "read_only", "match_mode", "stage", "menu_inputs", "match_count",
                "round_index", "completed_matches", "budget_scope", "round_started_elapsed_ms",
                "round_deadline_elapsed_ms", "round_max_seconds", "round_max_inputs", "round_inputs",
                "round_frames", "input_status_uncertain", "total_game_inputs", "total_menu_inputs", "total_settle_inputs");
        progress.put("engine", engine(campaign.optJSONObject("engine")));
        progress.put("opening", subset(campaign.optJSONObject("opening"), "verified", "stopReason", "gameInputs"));
        progress.put("settle", subset(campaign.optJSONObject("settle"), "reason", "final_state", "reason_after_return"));
        progress.put("round_totals", totals.snapshot());
        progress.put("campaign_complete_verified", totals.complete(campaign));
        String result = progress.toString();
        if (utf16Bytes(result) <= MAX_UTF16_BYTES) return result;
        // Overflow is a diagnostic display failure, never proof of completion.
        JSONObject fallback = new JSONObject().put("report_kind", KIND).put("projection_overflow", true)
                .put("campaign_complete_verified", false);
        copy(fallback, campaign, "event", "active", "session_id", "directory", "elapsed_ms", "reason",
                "match_mode", "match_count", "round_index", "completed_matches", "input_status_uncertain");
        result = fallback.toString();
        if (utf16Bytes(result) > MAX_UTF16_BYTES) throw new IllegalStateException("progress_projection_overflow");
        return result;
    }

    private static Object engine(JSONObject source) throws Exception {
        if (source == null) return JSONObject.NULL;
        JSONObject target = subset(source, "kind", "state", "turn", "stop_reason", "result_verified", "exception",
                "engine_turns_seen", "actions_confirmed", "game_inputs", "unconfirmed_inputs", "unconfirmed_skipped",
                "failed_inputs", "pending_end_turn_inputs", "end_turns_confirmed", "end_turns_unconfirmed",
                "deployment_refusals_confirmed", "full_game_passed", "layout_profile", "source_shape");
        JSONObject sourceValue = source.optJSONObject("value");
        if (sourceValue != null) {
            JSONObject value = subset(sourceValue, "state", "turn", "stop_reason", "result_verified", "exception",
                    "engine_turns_seen", "actions_confirmed", "game_inputs", "unconfirmed_inputs", "unconfirmed_skipped",
                    "failed_inputs", "pending_end_turn_inputs", "end_turns_confirmed", "end_turns_unconfirmed",
                    "deployment_refusals_confirmed", "full_game_passed", "layout_profile", "source_shape");
            JSONObject opponent = sourceValue.optJSONObject("opponent_turn_label");
            if (opponent != null) value.put("opponent_turn_label", subset(opponent, "present"));
            target.put("value", value);
        }
        return target;
    }

    private static JSONObject subset(JSONObject source, String... keys) throws Exception {
        if (source == null) return null;
        JSONObject target = new JSONObject();
        copy(target, source, keys);
        return target;
    }

    private static void copy(JSONObject target, JSONObject source, String... keys) throws Exception {
        for (String key : keys) {
            if (!source.has(key)) continue;
            Object value = source.opt(key);
            if (value instanceof String) {
                String text = (String) value;
                int length = Math.min(text.length(), MAX_TEXT_CHARS);
                if (length < text.length() && length > 0 && Character.isHighSurrogate(text.charAt(length - 1))) length--;
                target.put(key, text.substring(0, length));
            } else if (value instanceof Boolean || value instanceof Number || value == JSONObject.NULL) target.put(key, value);
        }
    }

    static long utf16Bytes(String value) { return value.length() * 2L; }

    private static long count(JSONObject object, String key) {
        return object == null ? -1 : integer(object.opt(key));
    }

    private static long integer(Object value) {
        if (!(value instanceof Integer || value instanceof Long)) return -1;
        long number = ((Number) value).longValue();
        return number >= 0 ? number : -1;
    }
}
