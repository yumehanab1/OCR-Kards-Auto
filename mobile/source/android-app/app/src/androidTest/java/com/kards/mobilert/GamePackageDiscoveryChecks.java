package com.kards.mobilert;

import android.content.Context;
import android.content.ContextWrapper;
import android.content.SharedPreferences;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

/** Real PackageManager and isolated preferences; no game launch, screenshot or gesture. */
final class GamePackageDiscoveryChecks {
    static JSONObject run(Context target, Context testPackage) throws Exception {
        String isolated = "game-target-checks-" + System.nanoTime();
        Context context = new ContextWrapper(target) {
            @Override public SharedPreferences getSharedPreferences(String name, int mode) {
                return target.getSharedPreferences(isolated, mode);
            }
        };
        String previous = GamePackages.selectedPackage();
        JSONArray checks = new JSONArray();
        try {
            require(checks, "idle_before_test", !BattleWorkerLease.isOwned());
            GamePackageDiscovery.useAutomatic(context);
            require(checks, "automatic_uses_legacy_policy", GamePackages.selectedPackage() == null);
            List<GamePackageDiscovery.Candidate> candidates = GamePackageDiscovery.candidates(context);
            Set<String> seen = new HashSet<>();
            for (GamePackageDiscovery.Candidate item : candidates) {
                require(checks, "unique_candidate_" + item.packageName, seen.add(item.packageName));
                require(checks, "candidate_launchable_" + item.packageName,
                        target.getPackageManager().getLaunchIntentForPackage(item.packageName) != null);
                require(checks, "candidate_has_signer_" + item.packageName, item.signers.matches("[0-9a-f]{64}(,[0-9a-f]{64})*"));
            }
            require(checks, "picker_excludes_own_app", !seen.contains(target.getPackageName()));
            GamePackageDiscovery.Candidate known = GamePackageDiscovery.inspect(context, GamePackages.DEFAULT);
            require(checks, "real_game_identity_readable", known != null);
            GamePackageDiscovery.select(context, known);
            require(checks, "selected_package_persisted", known.packageName.equals(GamePackageDiscovery.configuredPackage(context)));
            require(checks, "selected_package_exact", GamePackages.isGame(known.packageName) && !GamePackages.isGame(GamePackages.APK));
            GamePackages.configureSelection(null);
            GamePackageDiscovery.refresh(context);
            require(checks, "process_policy_restored_from_preferences", known.packageName.equals(GamePackages.selectedPackage()));
            context.getSharedPreferences("ignored", 0).edit().putString("signers_sha256", "0000000000000000000000000000000000000000000000000000000000000000").commit();
            GamePackageDiscovery.refresh(context);
            require(checks, "changed_signer_blocks_without_fallback", GamePackageDiscovery.selectionInvalid(context)
                    && !GamePackages.isGame(GamePackages.DEFAULT) && GamePackageDiscovery.findLaunchable(context) == null);
            boolean rejected = false;
            try { GamePackageDiscovery.select(context, new GamePackageDiscovery.Candidate(known.packageName, known.label, "wrong")); }
            catch (IllegalStateException expected) { rejected = true; }
            require(checks, "stale_confirmation_refused", rejected);
            GamePackageDiscovery.Candidate fixture = GamePackageDiscovery.inspect(context, testPackage.getPackageName());
            require(checks, "unknown_test_package_has_real_signer", fixture != null && !GamePackages.isKnown(fixture.packageName));
            GamePackageDiscovery.select(context, fixture);
            require(checks, "unknown_selected_package_admitted", GamePackages.isGame(fixture.packageName)
                    && !GamePackages.isGame(known.packageName));
            require(checks, "no_launcher_identity_still_valid_for_manual_entry", !GamePackageDiscovery.selectionInvalid(context));
            Object token = new Object();
            require(checks, "claim_fake_busy_lease", BattleWorkerLease.tryClaim(token));
            try {
                rejected = false;
                try { GamePackageDiscovery.useAutomatic(context); } catch (IllegalStateException expected) { rejected = true; }
                require(checks, "busy_cannot_reset_target", rejected && GamePackages.isGame(fixture.packageName));
                rejected = false;
                try { GamePackageDiscovery.select(context, known); } catch (IllegalStateException expected) { rejected = true; }
                require(checks, "busy_cannot_change_target", rejected && GamePackages.isGame(fixture.packageName));
            } finally { BattleWorkerLease.release(token); }
            GamePackageDiscovery.useAutomatic(context);
            require(checks, "explicit_reset_restores_automatic", GamePackages.selectedPackage() == null);
            return new JSONObject().put("passed", true).put("checks", checks).put("check_count", checks.length())
                    .put("failure_count", 0).put("device_inputs", 0).put("game_launches", 0)
                    .put("unknown_package_fixture", fixture.packageName).put("real_alternative_game_apk_tested", false);
        } finally {
            target.deleteSharedPreferences(isolated);
            GamePackages.configureSelection(previous);
        }
    }

    private static void require(JSONArray checks, String name, boolean passed) throws Exception {
        if (!passed) throw new AssertionError(name);
        checks.put(new JSONObject().put("name", name).put("passed", true));
    }
}
