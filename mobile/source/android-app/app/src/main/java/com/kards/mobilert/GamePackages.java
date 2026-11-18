package com.kards.mobilert;

import java.util.function.Function;

/** Discovery hints are not input authority: only known or explicitly pinned identities qualify. */
final class GamePackages {
    static final String DEFAULT = "com.android1939.kards";
    static final String APK = "com.android1939.kardsapk";
    // null = legacy automatic discovery; empty = an explicit selection failed validation.
    private static volatile String selectedPackage;

    private GamePackages() { }

    static boolean isKnown(String packageName) {
        return DEFAULT.equals(packageName) || APK.equals(packageName);
    }

    static boolean isGame(String packageName) {
        String selected = selectedPackage;
        return selected == null ? isKnown(packageName)
                : !selected.isEmpty() && selected.equals(packageName);
    }

    static String selectedPackage() { return selectedPackage; }

    static void configureSelection(String trustedPackage) {
        if (trustedPackage != null && !trustedPackage.isEmpty() && !isSelectable(trustedPackage))
            throw new IllegalArgumentException("invalid_game_package");
        selectedPackage = trustedPackage;
    }

    static boolean isSelectable(String packageName) {
        return packageName != null && packageName.length() <= 255
                && packageName.matches("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*)+")
                && !"com.kards.mobilert".equals(packageName)
                && !"com.android.systemui".equals(packageName);
    }

    static boolean matchesPinnedIdentity(String expectedPackage, String expectedSigners,
                                         String actualPackage, String actualSigners) {
        return isSelectable(expectedPackage) && expectedPackage.equals(actualPackage)
                && expectedSigners != null && expectedSigners.matches("[0-9a-f]{64}(,[0-9a-f]{64})*")
                && expectedSigners.equals(actualSigners);
    }

    /** Name similarity only sorts a picker. It never changes isGame or selects a package. */
    static int discoveryRank(String packageName, String label) {
        if (isKnown(packageName)) return 0;
        String text = (String.valueOf(packageName) + " " + String.valueOf(label)).toLowerCase(java.util.Locale.ROOT);
        return text.contains("kards") ? 1 : 2;
    }

    /** Explicit selection never silently falls back to a different installed distribution. */
    static <T> T findLaunchable(Function<String, T> lookup) {
        String selected = selectedPackage;
        if (selected != null) return selected.isEmpty() ? null : lookup.apply(selected);
        T original = lookup.apply(DEFAULT);
        return original != null ? original : lookup.apply(APK);
    }
}
