package com.kards.mobilert;

import org.json.JSONArray;
import org.json.JSONObject;

/** Fake foreground facts only: no screenshot, launch, or input APIs. */
final class GameEntryGateChecks {
    private static final String GAME = "com.android1939.kards";
    private final JSONArray checks = new JSONArray();
    private int failures;
    private interface Check { void run() throws Exception; }

    static JSONObject run() throws Exception {
        GameEntryGateChecks tests = new GameEntryGateChecks();
        tests.matrix();
        return new JSONObject().put("checks", tests.checks).put("check_count", tests.checks.length())
                .put("failure_count", tests.failures).put("device_inputs", 0).put("activity_launches", 0);
    }

    private void matrix() throws Exception {
        check("missing_mode_preserves_launch_default", () -> equal(GameEntryGate.LAUNCH_GAME,
                GameEntryGate.parseMode(new JSONObject())));
        for (Object value : new Object[]{"", "auto", "CURRENT_GAME", 1, true, JSONObject.NULL}) {
            check("invalid_mode_" + value, () -> {
                try { GameEntryGate.parseMode(new JSONObject().put("entry_mode", value)); }
                catch (IllegalArgumentException expected) { return; }
                throw new AssertionError("Unsupported mode accepted");
            });
        }
        check("default_already_game_requires_new_entry", () -> {
            GameEntryGate gate = new GameEntryGate(GameEntryGate.LAUNCH_GAME, GAME, 5, 1000);
            equal(GameEntryGate.WAITING, gate.check(GAME, 5));
            equal(GameEntryGate.WAITING, gate.check("launcher", 6));
            equal(null, gate.check(GAME, 7));
            require(gate.admittedGeneration() == 7, "First new game entry must be locked");
        });
        check("current_game_admits_same_generation", () -> {
            GameEntryGate gate = current();
            require(gate.isAdmitted(), "Current game must be admitted at arming");
            equal(null, gate.check(GAME, 5));
            equal(null, gate.checkCapture(1000, 5));
        });
        for (String foreground : new String[]{"launcher", "com.kards.mobilert", "", null}) {
            check("current_game_rejects_" + foreground, () -> {
                try { new GameEntryGate(GameEntryGate.CURRENT_GAME, foreground, 5, 1000); }
                catch (IllegalArgumentException expected) { equal("current_game_not_foreground", expected.getMessage()); return; }
                throw new AssertionError("Non-game entry accepted");
            });
        }
        check("new_request_required_after_arming", () -> equal("capture_before_arming", current().checkCapture(999, 5)));
        check("request_generation_must_match_entry", () -> equal("foreground_changed", current().checkCapture(1001, 6)));
        check("unadmitted_launch_cannot_supply_frame", () -> equal("foreground_changed",
                new GameEntryGate(GameEntryGate.LAUNCH_GAME, "launcher", 5, 1000).checkCapture(1001, 5)));
        check("leave_and_return_between_checks_is_rejected", () -> equal("foreground_changed", current().check(GAME, 7)));
        check("invalidated_token_cannot_rebind", () -> {
            GameEntryGate gate = current();
            equal("foreground_changed", gate.check("launcher", 6));
            equal("foreground_changed", gate.check(GAME, 7));
            equal("foreground_changed", gate.check(GAME, 5));
            equal("foreground_changed", gate.checkCapture(1001, 5));
        });
        check("launch_entry_locks_after_first_admission", () -> {
            GameEntryGate gate = new GameEntryGate(GameEntryGate.LAUNCH_GAME, "launcher", 5, 1000);
            equal(null, gate.check(GAME, 6));
            equal("foreground_changed", gate.check(GAME, 8));
        });
        check("opening_handoff_retains_same_token", () -> {
            GameEntryGate campaign = current();
            GameEntryGate opening = campaign;
            equal(null, opening.check(GAME, 5));
            equal(null, campaign.check(GAME, 5));
            equal("foreground_changed", opening.check("launcher", 6));
            equal("foreground_changed", campaign.check(GAME, 7));
        });
        check("java_only_options_do_not_reach_python", () -> {
            JSONObject input = new JSONObject().put("entry_mode", "current_game")
                    .put("start_with_opening", true).put("max_inputs", 1).put("read_only", true);
            JSONObject runtime = ApkBattleSession.runtimeOptions(input);
            require(!runtime.has("entry_mode") && !runtime.has("start_with_opening"), "Java options leaked");
            require(runtime.getInt("max_inputs") == 1 && runtime.getBoolean("read_only"), "Runtime limits changed");
            require(input.has("entry_mode") && input.has("start_with_opening"), "Evidence options mutated");
        });
    }

    private static GameEntryGate current() { return new GameEntryGate(GameEntryGate.CURRENT_GAME, GAME, 5, 1000); }
    private static void require(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
    private static void equal(String expected, String actual) {
        require(java.util.Objects.equals(expected, actual), "Expected " + expected + ", got " + actual);
    }
    private void check(String name, Check action) throws Exception {
        JSONObject row = new JSONObject().put("name", name);
        try { action.run(); row.put("passed", true); }
        catch (Throwable error) { failures++; row.put("passed", false).put("error", error.toString()); }
        checks.put(row);
    }
}
