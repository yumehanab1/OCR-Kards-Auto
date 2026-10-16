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
        check("bootstrap_same_game_startup_windows_rebind", () -> {
            GameEntryGate gate = bootstrap();
            equal(GameEntryGate.WAITING, gate.check("com.kards.mobilert", 5, 12));
            equal(null, gate.check(GAME, 6, 12));
            equal(GameEntryGate.WAITING, gate.check("", 7, 12));
            require(gate.isAdmitted() && gate.admittedGeneration() == 6, "Gap lost prior admission");
            equal(null, gate.check(GAME, 8, 12));
            equal(null, gate.check(GAME, 9, 12));
            require(gate.admittedGeneration() == 9, "Final game window was not admitted");
            equal(null, gate.checkCapture(1001, 9));
            require(gate.evidence().getInt("bootstrap_rebindings") == 2, "Missing window rebindings");
        });
        check("bootstrap_null_window_waits_without_invalidating", () -> {
            GameEntryGate gate = bootstrap();
            equal(GameEntryGate.WAITING, gate.check(null, 6, 12));
            equal(GameEntryGate.RECAPTURE, gate.checkCapture(1001, 6));
            equal(null, gate.check(GAME, 7, 12));
            equal(null, gate.checkCapture(1001, 7));
        });
        check("bootstrap_still_requires_new_game_entry", () -> {
            GameEntryGate gate = new GameEntryGate(GameEntryGate.LAUNCH_GAME, GAME, 5, 1000);
            gate.enableBootstrap(12);
            equal(GameEntryGate.WAITING, gate.check(GAME, 5, 12));
            require(!gate.isAdmitted(), "Original game window incorrectly admitted");
            equal(null, gate.check(GAME, 6, 12));
        });
        check("bootstrap_retired_capture_is_discarded_without_poisoning_entry", () -> {
            GameEntryGate gate = bootstrap();
            equal(null, gate.check(GAME, 6, 12));
            equal(null, gate.check(GAME, 8, 12));
            equal(GameEntryGate.RECAPTURE, gate.checkCapture(1001, 6));
            equal(null, gate.check(GAME, 8, 12));
            equal(null, gate.checkCapture(1002, 8));
            require(!gate.evidence().getBoolean("invalidated"), "Old callback invalidated current window");
        });
        check("bootstrap_never_admitted_capture_is_not_a_retired_window", () -> {
            GameEntryGate gate = bootstrap();
            equal(null, gate.check(GAME, 6, 12));
            equal(null, gate.check(GAME, 8, 12));
            equal("foreground_changed", gate.checkCapture(1001, 7));
            equal("foreground_changed", gate.checkCapture(1001, 9));
            equal(null, gate.checkCapture(1001, 8));
        });
        check("bootstrap_departure_and_return_cannot_rebind", () -> {
            GameEntryGate gate = bootstrap();
            equal(null, gate.check(GAME, 6, 12));
            equal("foreground_changed", gate.check(GAME, 8, 13));
            equal("foreground_changed", gate.check(GAME, 9, 12));
            equal("foreground_changed", gate.checkCapture(1001, 6));
        });
        check("bootstrap_departure_during_window_gap_invalidates", () -> {
            GameEntryGate gate = bootstrap();
            equal(null, gate.check(GAME, 6, 12));
            equal("foreground_changed", gate.check("", 7, 13));
            equal("foreground_changed", gate.check(GAME, 8, 13));
        });
        check("bootstrap_departure_before_first_game_invalidates", () -> {
            GameEntryGate gate = bootstrap();
            equal("foreground_changed", gate.check("", 6, 13));
            equal("foreground_changed", gate.check(GAME, 7, 12));
        });
        for (String foreground : new String[]{"launcher", "com.example.other", "com.kards.mobilert"}) {
            check("bootstrap_explicit_other_foreground_rejects_" + foreground, () -> {
                GameEntryGate gate = bootstrap();
                equal(null, gate.check(GAME, 6, 12));
                equal("foreground_changed", gate.check(foreground, 7, 12));
                equal("foreground_changed", gate.check(GAME, 8, 12));
            });
        }
        check("bootstrap_before_admission_only_allows_armed_package_to_wait", () -> {
            GameEntryGate gate = bootstrap();
            equal("foreground_changed", gate.check("com.example.other", 6, 12));
            equal("foreground_changed", gate.check(GAME, 7, 12));
        });
        check("bootstrap_cannot_move_generation_backwards", () -> {
            GameEntryGate gate = bootstrap();
            equal(null, gate.check(GAME, 8, 12));
            equal("foreground_changed", gate.check(GAME, 6, 12));
            equal("foreground_changed", gate.check(GAME, 9, 12));
        });
        check("bootstrap_seal_locks_current_window", () -> {
            GameEntryGate gate = bootstrap();
            equal(null, gate.check(GAME, 6, 12));
            equal(null, gate.check(GAME, 8, 12));
            gate.sealBootstrap();
            equal(null, gate.check(GAME, 8, 12));
            equal("foreground_changed", gate.check(GAME, 9, 12));
            equal("foreground_changed", gate.check(GAME, 8, 12));
            require(gate.evidence().getBoolean("bootstrap_sealed"), "First input did not seal bootstrap");
        });
        check("bootstrap_sealed_old_callback_still_requires_recapture", () -> {
            GameEntryGate gate = bootstrap();
            equal(null, gate.check(GAME, 6, 12));
            equal(null, gate.check(GAME, 8, 12));
            gate.sealBootstrap();
            equal(GameEntryGate.RECAPTURE, gate.checkCapture(1001, 6));
            equal(null, gate.checkCapture(1001, 8));
            equal(null, gate.check(GAME, 8, 12));
        });
        check("bootstrap_sealed_window_gap_uses_original_protection", () -> {
            GameEntryGate gate = bootstrap();
            equal(null, gate.check(GAME, 6, 12));
            gate.sealBootstrap();
            equal("foreground_changed", gate.check("", 7, 12));
            equal("foreground_changed", gate.check(GAME, 8, 12));
        });
        check("bootstrap_capture_before_arming_still_rejected", () -> {
            GameEntryGate gate = bootstrap();
            equal(null, gate.check(GAME, 6, 12));
            equal("capture_before_arming", gate.checkCapture(999, 6));
        });
        check("bootstrap_two_argument_check_stays_strict", () -> {
            GameEntryGate gate = bootstrap();
            equal(null, gate.check(GAME, 6, 12));
            equal("foreground_changed", gate.check(GAME, 8));
            equal("foreground_changed", gate.check(GAME, 9, 12));
        });
        check("three_argument_check_does_not_enable_bootstrap", () -> {
            GameEntryGate gate = new GameEntryGate(GameEntryGate.LAUNCH_GAME, "launcher", 5, 1000);
            equal(null, gate.check(GAME, 6, 12));
            equal("foreground_changed", gate.check(GAME, 8, 12));
        });
        check("current_game_cannot_enable_bootstrap", () -> {
            try { current().enableBootstrap(12); }
            catch (IllegalStateException expected) { return; }
            throw new AssertionError("Current-game mode enabled startup rebinding");
        });
        check("current_game_three_argument_check_stays_strict", () -> {
            GameEntryGate gate = current();
            equal(null, gate.check(GAME, 5, 12));
            equal("foreground_changed", gate.check(GAME, 6, 12));
        });
        check("bootstrap_epoch_cannot_be_reset", () -> {
            GameEntryGate gate = bootstrap();
            try { gate.enableBootstrap(13); }
            catch (IllegalStateException expected) {
                equal("foreground_changed", gate.check(GAME, 6, 13));
                return;
            }
            throw new AssertionError("Bootstrap departure proof was reset");
        });
        check("bootstrap_cannot_enable_after_admission", () -> {
            GameEntryGate gate = new GameEntryGate(GameEntryGate.LAUNCH_GAME, "launcher", 5, 1000);
            equal(null, gate.check(GAME, 6));
            try { gate.enableBootstrap(12); }
            catch (IllegalStateException expected) { return; }
            throw new AssertionError("Already-admitted launch enabled bootstrap");
        });
        check("bootstrap_negative_epoch_rejected", () -> {
            GameEntryGate gate = new GameEntryGate(GameEntryGate.LAUNCH_GAME, "launcher", 5, 1000);
            try { gate.enableBootstrap(-1); }
            catch (IllegalArgumentException expected) { return; }
            throw new AssertionError("Negative departure epoch accepted");
        });
        for (String failure : new String[]{"game_window_missing", "game_window_changed"}) {
            check("bootstrap_capture_failure_rebinds_" + failure, () -> {
                GameEntryGate gate = bootstrap();
                equal(null, gate.check(GAME, 6, 12));
                equal(GameEntryGate.RECAPTURE, gate.captureFailureReason(failure, GAME, 8, 12));
                equal(GameEntryGate.RECAPTURE, gate.checkCapture(1001, 6));
                equal(null, gate.checkCapture(1001, 8));
            });
            check("bootstrap_capture_failure_waits_in_gap_" + failure, () -> {
                GameEntryGate gate = bootstrap();
                equal(null, gate.check(GAME, 6, 12));
                equal(GameEntryGate.RECAPTURE, gate.captureFailureReason(failure, "", 7, 12));
                equal(null, gate.check(GAME, 8, 12));
            });
            check("bootstrap_capture_failure_rejects_real_departure_" + failure, () -> {
                GameEntryGate gate = bootstrap();
                equal(null, gate.check(GAME, 6, 12));
                equal("foreground_changed", gate.captureFailureReason(failure, GAME, 8, 13));
                equal("foreground_changed", gate.check(GAME, 9, 12));
            });
            check("bootstrap_capture_failure_rejects_explicit_external_" + failure, () -> {
                GameEntryGate gate = bootstrap();
                equal(null, gate.check(GAME, 6, 12));
                equal("foreground_changed", gate.captureFailureReason(failure, "com.example.other", 7, 12));
            });
            check("sealed_bootstrap_does_not_retry_capture_failure_" + failure, () -> {
                GameEntryGate gate = bootstrap();
                equal(null, gate.check(GAME, 6, 12));
                gate.sealBootstrap();
                equal(failure, gate.captureFailureReason(failure, GAME, 6, 12));
                equal("foreground_changed", gate.captureFailureReason(failure, GAME, 8, 12));
            });
            check("current_game_does_not_retry_startup_failure_" + failure, () -> {
                equal(failure, current().captureFailureReason(failure, GAME, 5, 12));
                equal("foreground_changed", current().captureFailureReason(failure, GAME, 6, 12));
            });
            check("strict_launch_does_not_retry_startup_failure_" + failure, () -> {
                GameEntryGate gate = new GameEntryGate(GameEntryGate.LAUNCH_GAME, "launcher", 5, 1000);
                equal(null, gate.check(GAME, 6));
                equal(failure, gate.captureFailureReason(failure, GAME, 6, 12));
            });
        }
        for (String failure : new String[]{"capture_timeout", "temporary_window_capture_error",
                "game_window_geometry_unconfirmed", "decode_failed"}) {
            check("bootstrap_keeps_unrelated_capture_failure_" + failure, () -> {
                GameEntryGate gate = bootstrap();
                equal(null, gate.check(GAME, 6, 12));
                equal(failure, gate.captureFailureReason(failure, GAME, 8, 12));
                equal(failure, gate.captureFailureReason(failure, "", 9, 12));
            });
        }
        check("bootstrap_capture_failure_checks_departure_even_for_unrelated_error", () -> {
            GameEntryGate gate = bootstrap();
            equal(null, gate.check(GAME, 6, 12));
            equal("foreground_changed", gate.captureFailureReason("decode_failed", GAME, 8, 13));
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
    private static GameEntryGate bootstrap() {
        GameEntryGate gate = new GameEntryGate(GameEntryGate.LAUNCH_GAME, "com.kards.mobilert", 5, 1000);
        gate.enableBootstrap(12);
        return gate;
    }
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
