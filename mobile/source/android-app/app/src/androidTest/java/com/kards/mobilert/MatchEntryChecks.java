package com.kards.mobilert;

import android.content.Context;
import android.os.SystemClock;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/** Device CPython/OpenCV menu replay using packaged images and fake input only. */
public final class MatchEntryChecks {
    private MatchEntryChecks() { }

    public static JSONObject run(Context testContext, Context targetContext) throws Exception {
        long started = SystemClock.elapsedRealtime();
        JSONObject report = new JSONObject().put("suite", "android-match-entry-saved-frame-v1")
                .put("device_inputs", 0).put("live_capture_count", 0).put("kards_launch_count", 0)
                .put("live_match_verified", false);
        File root = new File(targetContext.getFilesDir(), "device-tests/match-entry-" + System.nanoTime());
        Object owner = new Object();
        boolean lease = false;
        int failures = 0;
        try {
            lease = BattleWorkerLease.tryClaim(owner);
            require(lease, "A battle worker is still active; saved-frame tests cannot share its interpreter");
            require(root.mkdirs(), "Cannot create private menu replay directory");
            File assets = new File(root, "assets"), fixtures = new File(root, "fixtures");
            int assetCount = copyTree(targetContext, "match-entry", assets, assets);
            int fixtureCount = copyTree(testContext, "match-entry-replay", fixtures, fixtures);
            require(new File(assets, "manifest.json").isFile(), "Packaged menu manifest missing");
            require(new File(fixtures, "manifest.json").isFile(), "Packaged menu fixture manifest missing");
            report.put("evidence_root", root.getAbsolutePath()).put("production_asset_files", assetCount)
                    .put("fixture_files", fixtureCount);
            if (!Python.isStarted()) Python.start(new AndroidPlatform(targetContext.getApplicationContext()));
            JSONObject checks = new JSONObject(Python.getInstance().getModule("apk_match_entry_test")
                    .callAttr("self_check", assets.getAbsolutePath(), fixtures.getAbsolutePath()).toString());
            report.put("checks", checks);
            require(Boolean.TRUE.equals(checks.opt("passed")), "Embedded menu self-check failed");
            JSONObject nativeChecks = new JSONObject(Python.getInstance().getModule("apk_native_menu_test")
                    .callAttr("self_check").toString());
            report.put("native_popup_checks", nativeChecks);
            require(nativeChecks.getBoolean("passed"), "Native popup negative checks failed");
            require(checks.opt("device_inputs") instanceof Number && checks.getDouble("device_inputs") == 0,
                    "Menu self-check did not confirm zero device inputs");
        } catch (Throwable failure) {
            failures++;
            report.put("error", failure.toString());
        } finally {
            if (lease) BattleWorkerLease.release(owner);
        }
        report.put("passed", failures == 0).put("status", failures == 0 ? "passed" : "failed")
                .put("failure_count", failures).put("elapsed_ms", SystemClock.elapsedRealtime() - started);
        File result = new File(targetContext.getFilesDir(), "device-tests/match-entry-checks.json");
        File parent = result.getParentFile();
        require(parent != null && (parent.isDirectory() || parent.mkdirs()), "Cannot save menu replay report");
        try (FileOutputStream output = new FileOutputStream(result)) {
            output.write(report.toString(2).getBytes(StandardCharsets.UTF_8));
        }
        return report;
    }

    private static int copyTree(Context source, String assetPath, File target, File root) throws Exception {
        String rootPath = root.getCanonicalPath(), targetPath = target.getCanonicalPath();
        require(targetPath.equals(rootPath) || targetPath.startsWith(rootPath + File.separator),
                "Asset destination escaped replay directory");
        String[] children = source.getAssets().list(assetPath);
        if (children != null && children.length > 0) {
            require(target.isDirectory() || target.mkdirs(), "Cannot create asset copy directory");
            Arrays.sort(children);
            int copied = 0;
            for (String child : children) {
                require(!child.contains("/") && !child.contains("\\") && !"..".equals(child), "Invalid packaged asset name");
                copied += copyTree(source, assetPath + "/" + child, new File(target, child), root);
            }
            return copied;
        }
        File parent = target.getParentFile();
        require(parent != null && (parent.isDirectory() || parent.mkdirs()), "Cannot create asset parent");
        try (InputStream input = source.getAssets().open(assetPath); FileOutputStream output = new FileOutputStream(target)) {
            byte[] buffer = new byte[16384]; int count;
            while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
        }
        return 1;
    }

    private static void require(boolean valid, String reason) {
        if (!valid) throw new AssertionError(reason);
    }
}
