package com.kards.mobilert;

import android.graphics.Rect;
import java.util.Arrays;
import java.util.Collections;
import java.util.Objects;
import org.json.JSONArray;
import org.json.JSONObject;

/** Fake package/window facts only. Never launches applications or dispatches gestures. */
final class GamePackageChecks {
    private final JSONArray checks = new JSONArray();
    private interface Check { void run() throws Exception; }

    static JSONObject run() throws Exception {
        GamePackageChecks test = new GamePackageChecks();
        test.matrix();
        return new JSONObject().put("passed", true).put("checks", test.checks)
                .put("check_count", test.checks.length()).put("failure_count", 0)
                .put("device_inputs", 0).put("game_launches", 0);
    }

    private void check(String name, Check body) throws Exception {
        body.run();
        checks.put(new JSONObject().put("name", name).put("passed", true));
    }
    private static void equal(Object expected, Object actual) {
        if (!Objects.equals(expected, actual)) throw new AssertionError("Expected " + expected + ", got " + actual);
    }
    private static GameWindowState.Window window(int id, String owner, int type) {
        return new GameWindowState.Window(id, type, id, owner, new Rect(0, 0, 1280, 720), true, true, false);
    }
    private static JSONObject frame() throws Exception {
        return new JSONObject().put("frame_id", 3).put("captured_elapsed_ms", 1000)
                .put("foreground_generation", 5).put("source_width", 1280).put("source_height", 720)
                .put("width", 1280).put("height", 720);
    }
    private static JSONObject plan() throws Exception {
        return new JSONObject(frame().toString()).put("kind", "tap").put("duration_ms", 60)
                .put("from", new JSONArray().put(200).put(150)).put("to", new JSONArray().put(200).put(150));
    }
    private static String guard(int kind, String owner, long generation, long now, boolean cancelled) throws Exception {
        JSONObject p = plan(), f = frame();
        if (kind == 0) {
            p.put("state", "home").put("context", "menu_home_start").put("mode", "casual")
                    .put("first_deck_selected", true).put("target_bounds", new JSONArray().put(150).put(125).put(100).put(50));
            return MenuDispatchGuard.validate(p, f, 0, cancelled, false, now, 100000, 0, "menu", "casual", owner, generation);
        }
        if (kind == 1) {
            p.put("context", "end_turn");
            return BattleDispatchGuard.validate(p, f, 0, cancelled, false, now, 100000, 0, 3, owner, generation);
        }
        p.put("context", "settle");
        return SettleDispatchGuard.validate(p, f, 0, cancelled, false, now, 100000, 0, 18, new int[0][], owner, generation);
    }

    private void matrix() throws Exception {
        String[] valid = {"com.android1939.kards", "com.android1939.kardsapk"};
        String[] invalid = {null, "", "KARDS", "com.kards.mobilert", "com.android1939.kards.fake",
                "com.android1939.kardsapk.fake", "com.android1939.kardsap", "COM.ANDROID1939.KARDSAPK"};
        for (String owner : invalid) {
            check("exact_identity_rejects_" + owner, () -> equal(false, GamePackages.isGame(owner)));
            for (int i = 0; i < 3; i++) {
                final int kind = i;
                check("guard_" + kind + "_rejects_" + owner, () -> equal("foreground_changed", guard(kind, owner, 5, 1500, false)));
            }
        }
        check("neither_installed", () -> equal(null, GamePackages.findLaunchable(p -> null)));
        check("original_only", () -> equal(valid[0], GamePackages.findLaunchable(p -> valid[0].equals(p) ? p : null)));
        check("apk_only", () -> equal(valid[1], GamePackages.findLaunchable(p -> valid[1].equals(p) ? p : null)));
        check("both_keep_original_preference", () -> equal(valid[0], GamePackages.findLaunchable(p -> p)));
        check("fallback_after_original_has_no_launcher", () -> {
            java.util.List<String> calls = new java.util.ArrayList<>();
            equal(valid[1], GamePackages.findLaunchable(p -> { calls.add(p); return valid[1].equals(p) ? p : null; }));
            equal(Arrays.asList(valid), calls);
        });
        for (String owner : valid) {
            String other = owner.equals(valid[0]) ? valid[1] : valid[0];
            check("exact_identity_accepts_" + owner, () -> equal(true, GamePackages.isGame(owner)));
            check("current_entry_" + owner, () -> {
                GameEntryGate gate = new GameEntryGate("current_game", owner, 5, 1000);
                equal(null, gate.check(owner, 5));
                equal(owner, gate.evidence().getString("admitted_package"));
                equal("foreground_changed", gate.check(other, 5));
                equal("foreground_changed", gate.check(owner, 5));
            });
            check("launch_entry_" + owner, () -> {
                GameEntryGate gate = new GameEntryGate("launch_game", "helper", 5, 1000);
                equal(GameEntryGate.WAITING, gate.check(owner, 5));
                equal(null, gate.check(owner, 6));
                equal(owner, gate.evidence().getString("admitted_package"));
                equal("foreground_changed", gate.check(other, 7));
            });
            check("bootstrap_same_package_only_" + owner, () -> {
                GameEntryGate gate = new GameEntryGate("launch_game", "helper", 5, 1000);
                gate.enableBootstrap(1);
                equal(null, gate.check(owner, 6, 1));
                equal(null, gate.check(owner, 7, 1));
                equal(GameEntryGate.RECAPTURE, gate.checkCapture(1001, 6));
                equal(null, gate.checkCapture(1001, 7));
                equal("foreground_changed", gate.check(other, 8, 1));
                equal("foreground_changed", gate.check(owner, 9, 1));
            });
            check("bootstrap_sealed_generation_" + owner, () -> {
                GameEntryGate gate = new GameEntryGate("launch_game", "helper", 5, 1000);
                gate.enableBootstrap(1);
                equal(null, gate.check(owner, 6, 1));
                gate.sealBootstrap();
                equal("foreground_changed", gate.check(owner, 7, 1));
            });
            check("bootstrap_external_departure_" + owner, () -> {
                GameEntryGate gate = new GameEntryGate("launch_game", "helper", 5, 1000);
                gate.enableBootstrap(1);
                equal(null, gate.check(owner, 6, 1));
                equal("foreground_changed", gate.check(owner, 7, 2));
            });
            check("window_keeps_real_owner_" + owner, () -> {
                GameWindowState.Window game = window(1, owner, 1);
                GameWindowState state = GameWindowState.inspect(Arrays.asList(game), false);
                equal(owner, state.foreground);
                equal(owner, state.game.owner);
                equal(false, state.occluded);
                GameWindowState shade = GameWindowState.inspect(Arrays.asList(window(2, "com.android.systemui", 1)), false, game);
                equal(owner, shade.foreground);
                equal(true, shade.occluded);
                equal(true, shade.blocksPath(new float[][]{{100, 100}}));
                equal(null, GameWindowState.inspect(Collections.emptyList(), false, game).game);
                equal(null, GameWindowState.inspect(Arrays.asList(game), true).game);
                equal(null, GameWindowState.inspect(Arrays.asList(game, window(3, "other.app", 1)), false).game);
            });
            check("departure_tracker_" + owner, () -> {
                ForegroundDepartureTracker tracker = new ForegroundDepartureTracker();
                equal(0L, tracker.observe(Arrays.asList(window(1, owner, 1)), false));
                equal(1L, tracker.observe(Arrays.asList(window(2, "helper", 1)), false));
                equal(1L, tracker.observe(Arrays.asList(window(3, owner, 1)), false));
                equal(2L, tracker.observe(Arrays.asList(window(4, "helper", 1)), false));
            });
            for (int i = 0; i < 3; i++) {
                final int kind = i;
                check("guard_" + kind + "_accepts_" + owner, () -> equal(null, guard(kind, owner, 5, 1500, false)));
                check("guard_" + kind + "_generation_" + owner, () -> equal("foreground_changed", guard(kind, owner, 6, 1500, false)));
                check("guard_" + kind + "_stale_" + owner, () -> equal("frame_age_expired", guard(kind, owner, 5, 5001, false)));
                check("guard_" + kind + "_cancelled_" + owner, () -> equal("cancelled", guard(kind, owner, 5, 1500, true)));
            }
        }
    }
}
