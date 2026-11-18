package com.kards.mobilert;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.content.pm.Signature;

import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/** Android discovery and a user-confirmed, signer-pinned target. No launch or input side effects. */
final class GamePackageDiscovery {
    private static final String PREFS = "game_target";
    private static final String PACKAGE = "package";
    private static final String SIGNERS = "signers_sha256";

    static final class Candidate {
        final String packageName, label, signers;
        Candidate(String packageName, String label, String signers) {
            this.packageName = packageName; this.label = label; this.signers = signers;
        }
        String displayName() { return label + "\n" + packageName; }
    }

    private GamePackageDiscovery() { }

    private static SharedPreferences preferences(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static void refresh(Context context) {
        SharedPreferences prefs = preferences(context);
        if (!prefs.contains(PACKAGE)) { GamePackages.configureSelection(null); return; }
        String selected = prefs.getString(PACKAGE, "");
        Candidate actual = inspect(context, selected);
        GamePackages.configureSelection(actual != null && GamePackages.matchesPinnedIdentity(selected,
                prefs.getString(SIGNERS, ""), actual.packageName, actual.signers) ? selected : "");
    }

    static String configuredPackage(Context context) { return preferences(context).getString(PACKAGE, ""); }

    static boolean selectionInvalid(Context context) {
        return preferences(context).contains(PACKAGE) && "".equals(GamePackages.selectedPackage());
    }

    static Intent findLaunchable(Context context) {
        refresh(context);
        return GamePackages.findLaunchable(context.getPackageManager()::getLaunchIntentForPackage);
    }

    static List<Candidate> candidates(Context context) {
        PackageManager manager = context.getPackageManager();
        Intent query = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        Set<String> packages = new HashSet<>();
        for (ResolveInfo result : manager.queryIntentActivities(query, 0)) {
            if (result.activityInfo != null) packages.add(result.activityInfo.packageName);
        }
        packages.add(GamePackages.DEFAULT); packages.add(GamePackages.APK);
        List<Candidate> candidates = new ArrayList<>();
        for (String packageName : packages) {
            Candidate candidate = inspect(context, packageName);
            if (candidate != null && manager.getLaunchIntentForPackage(packageName) != null) candidates.add(candidate);
        }
        candidates.sort((a, b) -> {
            int rank = Integer.compare(GamePackages.discoveryRank(a.packageName, a.label),
                    GamePackages.discoveryRank(b.packageName, b.label));
            if (rank != 0) return rank;
            int label = a.label.compareToIgnoreCase(b.label);
            return label != 0 ? label : a.packageName.compareTo(b.packageName);
        });
        return candidates;
    }

    static Candidate inspect(Context context, String packageName) {
        if (!GamePackages.isSelectable(packageName)) return null;
        try {
            PackageManager manager = context.getPackageManager();
            PackageInfo info = manager.getPackageInfo(packageName, PackageManager.GET_SIGNING_CERTIFICATES);
            ApplicationInfo app = info.applicationInfo;
            if (app == null || !app.enabled || (app.flags & ApplicationInfo.FLAG_SYSTEM) != 0) return null;
            String signers = signerFingerprint(info);
            if (signers.isEmpty()) return null;
            return new Candidate(packageName, manager.getApplicationLabel(app).toString(), signers);
        } catch (PackageManager.NameNotFoundException | RuntimeException error) { return null; }
    }

    static String signerFingerprint(PackageInfo info) {
        if (info == null || info.signingInfo == null) return "";
        Signature[] signatures = info.signingInfo.getApkContentsSigners();
        if (signatures == null || signatures.length == 0) return "";
        try {
            List<String> digests = new ArrayList<>();
            for (Signature signature : signatures) {
                byte[] hash = MessageDigest.getInstance("SHA-256").digest(signature.toByteArray());
                StringBuilder text = new StringBuilder();
                for (byte value : hash) text.append(String.format(Locale.ROOT, "%02x", value & 0xff));
                digests.add(text.toString());
            }
            Collections.sort(digests);
            return String.join(",", digests);
        } catch (java.security.NoSuchAlgorithmException error) { throw new IllegalStateException(error); }
    }

    static void select(Context context, Candidate confirmed) {
        requireIdle();
        Candidate actual = confirmed == null ? null : inspect(context, confirmed.packageName);
        if (actual == null || !GamePackages.matchesPinnedIdentity(confirmed.packageName, confirmed.signers,
                actual.packageName, actual.signers)) throw new IllegalStateException("game_identity_changed");
        if (!preferences(context).edit().putString(PACKAGE, actual.packageName)
                .putString(SIGNERS, actual.signers).commit()) throw new IllegalStateException("game_selection_not_saved");
        refresh(context);
    }

    static void useAutomatic(Context context) {
        requireIdle();
        if (!preferences(context).edit().clear().commit()) throw new IllegalStateException("game_selection_not_saved");
        refresh(context);
    }

    private static void requireIdle() {
        KardsAccessibilityService service = KardsAccessibilityService.instance();
        if (BattleWorkerLease.isOwned() || (service != null && service.targetSelectionLocked()))
            throw new IllegalStateException("game_selection_busy");
    }
}
