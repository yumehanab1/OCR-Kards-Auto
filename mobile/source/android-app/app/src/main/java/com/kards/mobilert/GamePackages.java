package com.kards.mobilert;

import java.util.function.Function;

/** Exact supported identities shared by discovery, launch, windows and input checks. */
final class GamePackages {
    static final String DEFAULT = "com.android1939.kards";
    static final String APK = "com.android1939.kardsapk";

    private GamePackages() { }

    static boolean isGame(String packageName) {
        return DEFAULT.equals(packageName) || APK.equals(packageName);
    }

    /** Preserve the existing launch preference if both distributions are installed. */
    static <T> T findLaunchable(Function<String, T> lookup) {
        T original = lookup.apply(DEFAULT);
        return original != null ? original : lookup.apply(APK);
    }
}
