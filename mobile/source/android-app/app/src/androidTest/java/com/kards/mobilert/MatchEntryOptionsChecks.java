package com.kards.mobilert;

import org.json.JSONArray;
import org.json.JSONObject;

/** Menu-option and handoff facts only; no service or worker is created. */
public final class MatchEntryOptionsChecks {
    private final JSONArray checks = new JSONArray();
    private int failures;
    private interface Check { void run() throws Exception; }

    public static JSONObject run() throws Exception {
        MatchEntryOptionsChecks test = new MatchEntryOptionsChecks();
        test.matrix();
        return new JSONObject().put("checks", test.checks).put("check_count", test.checks.length())
                .put("failure_count", test.failures).put("device_inputs", 0);
    }

    private void matrix() throws Exception {
        check("retention_option_does_not_reach_python_runtime", () -> {
            JSONObject source=new JSONObject().put("retain_full_evidence",false).put("max_inputs",120);
            JSONObject runtime=MatchEntryOptions.runtimeOptions(source);
            require(!runtime.has("retain_full_evidence") && source.has("retain_full_evidence") && runtime.getInt("max_inputs")==120);
        });
        check("missing_match_mode_preserves_training", () -> equal("training", MatchEntryOptions.parseMode(new JSONObject())));
        for (String mode : new String[]{"training", "casual", "ranked"}) {
            check("explicit_mode_" + mode, () -> equal(mode,
                    MatchEntryOptions.parseMode(new JSONObject().put("match_mode", mode).put("read_only", false))));
        }
        for (Object invalid : new Object[]{"", "Casual", "auto", 1, true, JSONObject.NULL}) {
            check("invalid_mode_" + invalid, () -> reject(new JSONObject().put("match_mode", invalid), "invalid_match_mode"));
        }
        check("training_read_only_is_preserved", () -> equal("training",
                MatchEntryOptions.parseMode(new JSONObject().put("read_only", true))));
        for (String mode : new String[]{"casual", "ranked"}) {
            check("read_only_cannot_match_" + mode, () -> reject(new JSONObject().put("match_mode", mode)
                    .put("read_only", true), "read_only_match_entry_forbidden"));
        }
        check("match_read_only_flag_is_not_coerced", () -> reject(new JSONObject().put("match_mode", "casual")
                .put("read_only", "false"), "invalid_read_only"));
        for (String mode : new String[]{"casual", "ranked"}) {
            check("handoff_accepts_owned_verified_match_" + mode, () -> require(MatchEntryOptions.isMenuReady(ready(mode), mode)));
        }
        check("handoff_requires_exact_mulligan_reason", () -> {
            require(!MatchEntryOptions.isMenuReady(ready("casual").put("reason", "matching"), "casual"));
            require(!MatchEntryOptions.isMenuReady(ready("casual").put("reason", "MULLIGAN_READY"), "casual"));
            JSONObject missing = ready("casual"); missing.remove("reason");
            require(!MatchEntryOptions.isMenuReady(missing, "casual"));
            require(!MatchEntryOptions.isMenuReady(null, "casual"));
        });
        for (String flag : new String[]{"verified", "queue_requested", "first_deck_selected"}) {
            check("handoff_requires_explicit_" + flag, () -> {
                JSONObject result = ready("casual"); result.remove(flag);
                require(!MatchEntryOptions.isMenuReady(result, "casual"));
            });
            Object[] invalidFlags = {false, "true", "false", 1, 0, JSONObject.NULL, new JSONArray(), new JSONObject()};
            for (int i = 0; i < invalidFlags.length; i++) {
                final Object value = invalidFlags[i];
                check("handoff_rejects_nontrue_boolean_" + flag + "_" + i,
                        () -> require(!MatchEntryOptions.isMenuReady(ready("casual").put(flag, value), "casual")));
            }
        }
        check("casual_summary_cannot_enter_ranked_campaign", () -> require(!MatchEntryOptions.isMenuReady(ready("casual"), "ranked")));
        check("ranked_summary_cannot_enter_casual_campaign", () -> require(!MatchEntryOptions.isMenuReady(ready("ranked"), "casual")));
        check("handoff_requires_explicit_result_mode", () -> {
            JSONObject result = ready("casual"); result.remove("mode");
            require(!MatchEntryOptions.isMenuReady(result, "casual"));
        });
        Object[] invalidModes = {"training", "Casual", "", "auto", 1, true, JSONObject.NULL};
        for (int i = 0; i < invalidModes.length; i++) {
            final Object value = invalidModes[i];
            check("handoff_rejects_wrong_result_mode_" + i,
                    () -> require(!MatchEntryOptions.isMenuReady(ready("casual").put("mode", value), "casual")));
        }
        for (String invalidMode : new String[]{"training", "Casual", "", "auto", null}) {
            check("handoff_never_authorizes_nonmatch_campaign_" + invalidMode,
                    () -> require(!MatchEntryOptions.isMenuReady(ready(invalidMode), invalidMode)));
        }
        check("settlement_keys_never_reach_the_embedded_engine", () -> {
            // The engine accepts only its own option names and refuses anything
            // else, so a campaign-only key must be stripped here. Regression:
            // adding the settlement keys without stripping them turned every
            // match into "unsupported_runtime_options" at battle start.
            JSONObject source = new JSONObject().put("match_mode", "casual").put("entry_mode", "launch_game")
                    .put("read_only", false).put("max_inputs", 120)
                    .put("post_match_settle", true)
                    .put("settle_points", new JSONArray().put(new JSONArray().put(640).put(501)));
            JSONObject runtime = MatchEntryOptions.runtimeOptions(source);
            require(!runtime.has("post_match_settle") && !runtime.has("settle_points"));
            require(runtime.getInt("max_inputs") == 120);
            require(source.has("post_match_settle") && source.has("settle_points"));
        });
        check("campaign_count_never_reaches_strict_python_options", () -> {
            JSONObject source = new JSONObject().put("match_count",2).put("max_inputs",200);
            JSONObject result = MatchEntryOptions.runtimeOptions(source);
            require(!result.has("match_count") && result.getInt("max_inputs")==200 && source.getInt("match_count")==2);
        });
        check("only_java_owned_options_are_removed_without_mutating_evidence", () -> {
            JSONObject source = new JSONObject().put("match_mode", "ranked").put("entry_mode", "current_game")
                    .put("start_with_opening", true).put("read_only", false).put("max_inputs", 120)
                    .put("unknown_option_must_still_fail_in_python", true);
            String original = source.toString();
            JSONObject runtime = MatchEntryOptions.runtimeOptions(source);
            require(!runtime.has("match_mode") && !runtime.has("entry_mode") && !runtime.has("start_with_opening"));
            require(runtime.getInt("max_inputs") == 120 && !runtime.getBoolean("read_only"));
            require(runtime.has("unknown_option_must_still_fail_in_python") && original.equals(source.toString()));
        });
    }

    private static JSONObject ready(String mode) throws Exception {
        return new JSONObject().put("verified", true).put("queue_requested", true)
                .put("first_deck_selected", true).put("mode", mode).put("reason", "mulligan_ready");
    }

    private static void reject(JSONObject options, String expected) {
        try { MatchEntryOptions.parseMode(options); }
        catch (IllegalArgumentException failure) { equal(expected, failure.getMessage()); return; }
        throw new AssertionError("Invalid options accepted");
    }

    private static void equal(String expected, String actual) { require(expected.equals(actual)); }
    private static void require(boolean ok) { if (!ok) throw new AssertionError("Check failed"); }
    private void check(String name, Check action) throws Exception {
        JSONObject result = new JSONObject().put("name", name);
        try { action.run(); result.put("passed", true); }
        catch (Throwable failure) { failures++; result.put("passed", false).put("error", failure.toString()); }
        checks.put(result);
    }
}
