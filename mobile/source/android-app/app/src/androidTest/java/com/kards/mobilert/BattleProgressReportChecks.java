package com.kards.mobilert;

import org.json.JSONArray;
import org.json.JSONObject;

/** Transport bounds and completion proofs using the actual unchanged campaign gate. */
public final class BattleProgressReportChecks {
    private final JSONArray checks = new JSONArray();
    private int failures;
    private interface Check { void run() throws Exception; }

    public static JSONObject run() throws Exception {
        BattleProgressReportChecks test = new BattleProgressReportChecks();
        test.matrix();
        return new JSONObject().put("checks", test.checks).put("check_count", test.checks.length())
                .put("failure_count", test.failures).put("device_inputs", 0);
    }

    private void matrix() throws Exception {
        check("active_round_three_with_two_closed_rounds_is_not_complete", () -> {
            BattleProgressReport.RoundTotals totals = new BattleProgressReport.RoundTotals();
            totals.add(row(1, result(8), returned(), false));
            totals.add(row(2, result(3), returned(), false));
            JSONObject source = campaign(3, 2, true).put("reason", "capture");
            JSONObject progress = projected(source, totals);
            require(!progress.getBoolean("campaign_complete_verified"));
            require(progress.getInt("round_index") == 3 && progress.getInt("completed_matches") == 2);
            require(progress.getJSONObject("round_totals").getInt("unconfirmed_inputs") == 11);
            require(!progress.getJSONObject("round_totals").getBoolean("full_game_passed"));
            require(!progress.has("rounds"));
        });
        check("complete_three_uses_original_full_ledgers_and_keeps_unknown", () -> {
            BattleProgressReport.RoundTotals totals = completeTotals(3);
            JSONObject progress = projected(campaign(3, 3, false), totals);
            require(progress.getBoolean("campaign_complete_verified"));
            require(progress.getJSONObject("round_totals").getInt("unconfirmed_inputs") == 3);
            require(progress.getJSONObject("round_totals").getInt("unconfirmed_skipped") == 0);
            require(progress.getJSONObject("round_totals").getInt("engine_turns_seen") == 9);
            require(progress.getJSONObject("round_totals").getInt("actions_confirmed") == 0);
        });
        check("finite_target_does_not_trust_only_completed_matches", () ->
                require(!projected(campaign(3, 3, false), completeTotals(2)).getBoolean("campaign_complete_verified")));
        check("finite_target_does_not_accept_extra_closed_round", () ->
                require(!projected(campaign(2, 2, false), completeTotals(3)).getBoolean("campaign_complete_verified")));
        check("active_and_stopping_cannot_certify_complete", () -> {
            BattleProgressReport.RoundTotals totals = completeTotals(3);
            require(!projected(campaign(3, 3, true), totals).getBoolean("campaign_complete_verified"));
            require(!projected(campaign(3, 3, false).put("event", "stopping"), totals).getBoolean("campaign_complete_verified"));
        });
        check("cancel_reason_cannot_certify_complete", () ->
                require(!projected(campaign(3, 3, false).put("reason", "user_stop"), completeTotals(3))
                        .getBoolean("campaign_complete_verified")));
        check("native_uncertainty_cannot_certify_complete", () ->
                require(!projected(campaign(3, 3, false).put("input_status_uncertain", true), completeTotals(3))
                        .getBoolean("campaign_complete_verified")));
        check("string_target_is_not_a_verified_count", () ->
                require(!projected(campaign(3, 3, false).put("match_count", "3"), completeTotals(3))
                        .getBoolean("campaign_complete_verified")));
        check("string_completion_is_not_a_verified_count", () ->
                require(!projected(campaign(3, 3, false).put("completed_matches", "3"), completeTotals(3))
                        .getBoolean("campaign_complete_verified")));
        for (String defect : new String[]{"incomplete_touch", "missing_receipts", "missing_hooks", "mismatched_hook",
                "unfinished_end", "unverified_result", "unverified_return", "engine_exception", "round_uncertain",
                "out_of_sequence"}) check("original_gate_blocks_" + defect, () -> {
            JSONObject engine = result(1), settle = returned();
            boolean uncertain = false;
            int index = 1;
            if ("incomplete_touch".equals(defect)) engine.getJSONArray("inputs").getJSONObject(0)
                    .getJSONObject("reply").put("completed", false);
            if ("missing_receipts".equals(defect)) engine.remove("inputs");
            if ("missing_hooks".equals(defect)) engine.remove("hooks");
            if ("mismatched_hook".equals(defect)) engine.getJSONArray("hooks").getJSONObject(0).put("kind", "move_front");
            if ("unfinished_end".equals(defect)) engine.put("pending_end_turn_inputs", 1);
            if ("unverified_result".equals(defect)) engine.put("result_verified", false);
            if ("unverified_return".equals(defect)) settle.put("reason_after_return", "return_deadline");
            if ("engine_exception".equals(defect)) engine.put("exception", "Stop:unknown");
            if ("round_uncertain".equals(defect)) uncertain = true;
            if ("out_of_sequence".equals(defect)) index = 2;
            BattleProgressReport.RoundTotals totals = new BattleProgressReport.RoundTotals();
            totals.add(row(index, engine, settle, uncertain));
            require(!projected(campaign(1, 1, false), totals).getBoolean("campaign_complete_verified"));
        });
        check("diagnostics_and_complete_ledger_do_not_expand_status", () -> {
            String huge = repeat('\u6d4b', 300_000);
            JSONObject source = campaign(3, 3, false).put("reason", huge)
                    .put("directory", huge).put("entry", new JSONObject().put("diagnostics", huge))
                    .put("rounds", new JSONArray().put(new JSONObject().put("raw", huge)))
                    .put("engine", result(1).put("diagnostics", huge).put("exception", huge));
            String before = source.toString();
            String progressText = BattleProgressReport.project(source, completeTotals(3));
            JSONObject progress = new JSONObject(progressText);
            require(BattleProgressReport.utf16Bytes(progressText) <= BattleProgressReport.MAX_UTF16_BYTES);
            require(!progress.has("rounds") && !progress.has("entry"));
            require(!progress.getJSONObject("engine").has("inputs") && !progress.getJSONObject("engine").has("hooks"));
            require(progress.getJSONObject("engine").getString("exception").length() == 512);
            require(before.equals(source.toString()));
            require(!progress.getBoolean("campaign_complete_verified"));
        });
        check("unlimited_10000_rounds_has_constant_size_and_never_finite_complete", () -> {
            BattleProgressReport.RoundTotals totals = new BattleProgressReport.RoundTotals();
            for (int index = 1; index <= 10_000; index++) totals.add(row(index, result(1), returned(), false));
            String text = BattleProgressReport.project(campaign(0, 10_000, false), totals);
            JSONObject progress = new JSONObject(text);
            require(BattleProgressReport.utf16Bytes(text) <= BattleProgressReport.MAX_UTF16_BYTES);
            require(!progress.getBoolean("campaign_complete_verified"));
            require(progress.getJSONObject("round_totals").getLong("closed_round_count") == 10_000);
            require(progress.getJSONObject("round_totals").getLong("unconfirmed_inputs") == 10_000);
        });
        check("missing_counters_stay_unknown_instead_of_zero", () -> {
            BattleProgressReport.RoundTotals totals = new BattleProgressReport.RoundTotals();
            JSONObject engine = result(1);
            engine.remove("engine_turns_seen"); engine.remove("actions_confirmed"); engine.remove("unconfirmed_skipped");
            totals.add(row(1, engine, returned(), false));
            JSONObject summary = totals.snapshot();
            require(summary.isNull("engine_turns_seen") && summary.isNull("actions_confirmed")
                    && summary.isNull("unconfirmed_skipped") && summary.getLong("unconfirmed_inputs") == 1);
        });
        check("known_false_quality_survives_missing_other_quality", () -> {
            BattleProgressReport.RoundTotals totals = new BattleProgressReport.RoundTotals();
            totals.add(row(1, result(1), returned(), false));
            JSONObject engine = result(1); engine.remove("full_game_passed");
            totals.add(row(2, engine, returned(), false));
            require(!totals.snapshot().getBoolean("full_game_passed"));
        });
        check("live_capture_opponent_turn_and_think_turn_are_preserved", () -> {
            JSONObject source = campaign(3, 0, true).put("engine", new JSONObject().put("kind", "capture")
                    .put("value", new JSONObject().put("state", "opponent_turn").put("turn", 7)
                            .put("opponent_turn_label", new JSONObject().put("present", true).put("diagnostics", repeat('x', 5000)))));
            JSONObject engine = projected(source, new BattleProgressReport.RoundTotals()).getJSONObject("engine");
            require("capture".equals(engine.getString("kind")) && engine.getJSONObject("value").getInt("turn") == 7);
            require(engine.getJSONObject("value").getJSONObject("opponent_turn_label").getBoolean("present"));
            require(!engine.getJSONObject("value").getJSONObject("opponent_turn_label").has("diagnostics"));
        });
    }

    private static BattleProgressReport.RoundTotals completeTotals(int count) throws Exception {
        BattleProgressReport.RoundTotals totals = new BattleProgressReport.RoundTotals();
        for (int i = 1; i <= count; i++) totals.add(row(i, result(1), returned(), false));
        return totals;
    }

    private static JSONObject result(int unknown) throws Exception {
        JSONArray receipts = new JSONArray(), hooks = new JSONArray();
        for (int i = 0; i < unknown; i++) {
            receipts.put(new JSONObject().put("request", new JSONObject().put("context", "attack_hq"))
                    .put("reply", new JSONObject().put("accepted", true).put("completed", true)));
            hooks.put(new JSONObject().put("kind", "attack_hq").put("inputs", 1).put("terminated", false)
                    .put("verification", "unconfirmed"));
        }
        return new JSONObject().put("result_verified", true).put("stop_reason", "result_defeat")
                .put("exception", JSONObject.NULL).put("game_inputs", unknown).put("unconfirmed_inputs", unknown)
                .put("unconfirmed_skipped", 0).put("failed_inputs", 0).put("end_turns_confirmed", 0)
                .put("pending_end_turn_inputs", 0).put("end_turns_unconfirmed", 0)
                .put("engine_turns_seen", 3).put("actions_confirmed", 0).put("full_game_passed", false)
                .put("inputs", receipts).put("hooks", hooks);
    }

    private static JSONObject returned() throws Exception {
        return new JSONObject().put("final_state", "deck_ready").put("reason_after_return", "return_not_needed:deck_ready");
    }

    private static JSONObject row(int index, JSONObject engine, JSONObject settle, boolean uncertain) throws Exception {
        return new JSONObject().put("round_index", index).put("engine", engine).put("settle", settle)
                .put("input_status_uncertain", uncertain);
    }

    private static JSONObject campaign(int count, int done, boolean active) throws Exception {
        return new JSONObject().put("event", "finished").put("active", active).put("session_id", "1791502665433-9b8509a4")
                .put("directory", "/data/data/com.kards.mobilert/files/battle/1791502665433-9b8509a4")
                .put("elapsed_ms", 123456L).put("reason", "campaign_complete").put("match_mode", "casual")
                .put("stage", "battle").put("match_count", count).put("round_index", Math.max(1, count))
                .put("completed_matches", done).put("input_status_uncertain", false);
    }

    private static JSONObject projected(JSONObject source, BattleProgressReport.RoundTotals totals) throws Exception {
        String text = BattleProgressReport.project(source, totals);
        require(BattleProgressReport.utf16Bytes(text) <= BattleProgressReport.MAX_UTF16_BYTES);
        return new JSONObject(text);
    }

    private static String repeat(char value, int count) {
        char[] chars = new char[count]; java.util.Arrays.fill(chars, value); return new String(chars);
    }

    private void check(String name, Check action) throws Exception {
        JSONObject row = new JSONObject().put("name", name);
        try { action.run(); row.put("passed", true); }
        catch (Throwable error) { failures++; row.put("passed", false).put("error", error.toString()); }
        checks.put(row);
    }

    private static void require(boolean ok) { if (!ok) throw new AssertionError("failed"); }
}
