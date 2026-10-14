package com.kards.mobilert;

import android.content.Context;
import android.os.SystemClock;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

/** Real Android CPython/NumPy/OpenCV + packaged core; saved pixels and fake I/O only. */
public final class EmbeddedCoreChecks {
    private EmbeddedCoreChecks() { }

    public static JSONObject run(Context testContext, Context targetContext) throws Exception {
        long started = SystemClock.elapsedRealtime();
        JSONObject report = new JSONObject();
        JSONArray cases = new JSONArray();
        report.put("suite", "android-embedded-core-saved-frame-v1");
        report.put("device_inputs", 0).put("live_capture_count", 0).put("kards_launch_count", 0);
        report.put("live_game_action_verified", false).put("cases", cases);
        int failures = 0;
        try {
            if (!Python.isStarted()) Python.start(new AndroidPlatform(targetContext.getApplicationContext()));
            Python python = Python.getInstance();
            byte[] coreManifestBytes = readAsset(targetContext, "mobile-core/manifest.json");
            String coreHash = sha256(coreManifestBytes);
            JSONObject coreManifest = new JSONObject(new String(coreManifestBytes, StandardCharsets.UTF_8));
            // Same immutable content-key path as ApkBattleSession.prepareCore.
            File core = new File(targetContext.getFilesDir(), "embedded-core/" + coreHash);
            require(core.isDirectory() || core.mkdirs(), "Cannot create core directory");
            JSONArray coreFiles = coreManifest.getJSONArray("files");
            for (int index = 0; index < coreFiles.length(); index++) {
                JSONObject entry = coreFiles.getJSONObject(index);
                String relative = entry.getString("path");
                require(!relative.contains("..") && !relative.startsWith("/"), "Unsafe core path");
                byte[] bytes = readAsset(targetContext, "mobile-core/" + relative);
                require(bytes.length == entry.getLong("size") && sha256(bytes).equals(entry.getString("sha256")),
                        "Packaged core hash mismatch: " + relative);
                File destination = new File(core, relative);
                require(destination.getCanonicalPath().startsWith(core.getCanonicalPath() + File.separator),
                        "Core destination escaped root");
                writeBytes(destination, bytes);
            }
            writeBytes(new File(core, "manifest.json"), coreManifestBytes);
            report.put("core_manifest_sha256", coreHash).put("verified_core_files", coreFiles.length());
            report.put("core_content_sha256", coreManifest.getString("content_sha256"));

            // Pixel regressions use verified pure core helpers. Prepare their
            // import directory before guard checks, without capture or input.
            JSONObject guards = new JSONObject(python.getModule("apk_battle_runtime_test")
                    .callAttr("self_check", core.getAbsolutePath()).toString());
            report.put("guard_checks", guards);
            require(guards.getBoolean("passed") && guards.getInt("tests_run") >= 19,
                    "Fake bridge guard checks failed");
            require(guards.getInt("device_inputs") == 0, "Guard checks reported device inputs");

            JSONObject fixtures = new JSONObject(new String(readAsset(testContext,
                    "embedded-core-replay/manifest.json"), StandardCharsets.UTF_8));
            require(fixtures.getInt("schema_version") == 1, "Unknown embedded fixture schema");
            JSONArray inputs = fixtures.getJSONArray("fixtures");
            require(inputs.length() == 26 && fixtures.getInt("repetitions") == 2,
                    "Expected twenty-six fixtures replayed twice");
            File root = new File(targetContext.getFilesDir(), "device-tests/embedded-" + System.nanoTime());
            require(root.mkdirs(), "Cannot create embedded replay evidence");
            report.put("evidence_root", root.getAbsolutePath());
            for (int repetition = 0; repetition < 2; repetition++) {
                for (int index = 0; index < inputs.length(); index++) {
                    JSONObject fixture = inputs.getJSONObject(index);
                    JSONObject item = new JSONObject().put("fixture", fixture.getString("id"))
                            .put("repetition", repetition);
                    cases.put(item);
                    try {
                        byte[] png = readAsset(testContext, fixture.getString("asset"));
                        require(sha256(png).equals(fixture.getString("sha256")), "Fixture hash mismatch");
                        File output = new File(root, repetition + "-" + fixture.getString("id"));
                        require(output.mkdirs(), "Cannot create case directory");
                        SavedFrameBridge bridge = new SavedFrameBridge(png, output);
                        JSONObject summary = new JSONObject(python.getModule("apk_battle_runtime")
                                .callAttr("run", bridge, core.getAbsolutePath(), output.getAbsolutePath(),
                                        "{\"read_only\":true,\"max_inputs\":1,\"max_seconds\":120}")
                                .toString());
                        require("inspection_complete".equals(summary.getString("stop_reason")),
                                "Embedded replay failed: " + summary);
                        require(summary.isNull("exception"), "Embedded replay exception");
                        require(summary.getInt("game_inputs") == 0 && bridge.dispatchCalls == 0,
                                "Saved-frame replay attempted input");
                        require(bridge.captureCalls == 1, "Expected exactly one read-only capture");
                        require(bridge.observation != null && bridge.inspection != null, "Missing core observations");
                        if (fixture.has("expected_state") && fixture.isNull("expected_state")) {
                            require(bridge.observation.isNull("state"), "Enemy/unknown frame became our turn");
                        } else if (fixture.has("expected_state")) {
                            require(fixture.getString("expected_state").equals(bridge.observation.getString("state")),
                                    "Game/result state changed");
                        }
                        if (fixture.has("expected_layout")) {
                            JSONObject kredits = bridge.inspection.getJSONObject("kredits");
                            require(fixture.getString("expected_layout").equals(kredits.getJSONObject("hud").getString("layout")),
                                    "HUD layout mismatch");
                            if (fixture.isNull("expected_kredits")) {
                                require(kredits.isNull("value"), "Unknown credits became a number");
                            } else {
                                require(kredits.getInt("value") == fixture.getInt("expected_kredits"), "Credits mismatch");
                            }
                        }
                        if (fixture.has("expected_enemy_hp")) {
                            require(bridge.inspection.getJSONObject("enemy_hq").getInt("hp") == fixture.getInt("expected_enemy_hp"),
                                    "Enemy HQ mismatch");
                            require(bridge.inspection.getJSONObject("our_hq").getInt("hp") == fixture.getInt("expected_our_hp"),
                                    "Our HQ mismatch");
                        }
                        if (fixture.has("expected_frontline")) {
                            require(bridge.inspection.getJSONObject("frontline").getString("owner")
                                    .equals(fixture.getString("expected_frontline")), "Frontline mismatch");
                        }
                        if (fixture.has("expected_transition_reason")) {
                            require(bridge.observation.getString("transition_reason")
                                    .equals(fixture.getString("expected_transition_reason")), "Scene transition mismatch");
                        }
                        if (fixture.has("expected_drop_point")) {
                            JSONArray point = bridge.inspection.getJSONObject("deployment_landing").getJSONArray("point");
                            JSONArray expectedPoint = fixture.getJSONArray("expected_drop_point");
                            require(point.length() == 2 && point.getInt(0) == expectedPoint.getInt(0)
                                    && point.getInt(1) == expectedPoint.getInt(1), "Clear deployment point mismatch");
                        }
                        if (fixture.has("expected_hand_costs")) {
                            File handPng = new File(output, "hand-fixture.png");
                            writeBytes(handPng, png);
                            JSONObject hand = new JSONObject(python.getModule("apk_battle_runtime_test")
                                    .callAttr("inspect_fixture_hand_json", handPng.getAbsolutePath(),
                                            bridge.inspection.getJSONArray("hand").toString()).toString());
                            JSONArray units = hand.getJSONArray("units");
                            JSONArray costs = fixture.getJSONArray("expected_hand_costs");
                            JSONArray points = fixture.getJSONArray("expected_hand_points");
                            require(units.length() == costs.length(), "Accepted hand count mismatch");
                            for (int unitIndex = 0; unitIndex < units.length(); unitIndex++) {
                                JSONObject availability = units.getJSONObject(unitIndex).getJSONObject("apk_availability");
                                require(costs.isNull(unitIndex) ? availability.isNull("cost")
                                                : !availability.isNull("cost") && availability.getInt("cost") == costs.getInt(unitIndex),
                                        "Accepted hand cost mismatch");
                                require(availability.getBoolean("allowed")
                                                && "orange_unit_geometry_v1".equals(availability.getString("basis")),
                                        "Accepted hand action geometry missing");
                                require(units.getJSONObject(unitIndex).getJSONArray("apk_grab_point").toString()
                                                .equals(points.getJSONArray(unitIndex).toString()),
                                        "Accepted hand grab point mismatch");
                            }
                            item.put("hand_availability", hand);
                        }
                        item.put("status", "passed").put("summary", summary)
                                .put("observation", bridge.observation).put("inspection", bridge.inspection);
                    } catch (Throwable failure) {
                        failures++;
                        item.put("status", "failed").put("error", failure.toString());
                    }
                }
            }
        } catch (Throwable failure) {
            failures++;
            report.put("suite_error", failure.toString());
        }
        report.put("failure_count", failures).put("case_count", cases.length());
        report.put("elapsed_ms", SystemClock.elapsedRealtime() - started);
        report.put("status", failures == 0 ? "passed" : "failed");
        writeBytes(new File(targetContext.getFilesDir(), "device-tests/embedded-core-checks.json"),
                report.toString(2).getBytes(StandardCharsets.UTF_8));
        return report;
    }

    /** Java/Python bridge contract exercised without Accessibility or device APIs. */
    public static final class SavedFrameBridge {
        private final byte[] png;
        private final File output;
        int captureCalls;
        int dispatchCalls;
        JSONObject observation;
        JSONObject inspection;

        public SavedFrameBridge(byte[] png, File output) { this.png = png; this.output = output; }
        public long elapsedRealtime() { return SystemClock.elapsedRealtime(); }
        public boolean isCancelled() { return false; }
        public String capture() throws Exception {
            long captured = SystemClock.elapsedRealtime();
            captureCalls++;
            File file = new File(output, "frames/" + captureCalls + ".png");
            writeBytes(file, png);
            return new JSONObject().put("ok", true).put("frame_id", captureCalls)
                    .put("captured_elapsed_ms", captured).put("foreground_generation", 1)
                    .put("source_width", 1920).put("source_height", 1080)
                    .put("png_path", file.getAbsolutePath()).toString();
        }
        public String dispatch(String request) {
            dispatchCalls++;
            throw new AssertionError("Saved-frame bridge forbids all input: " + request);
        }
        public void emit(String encoded) throws Exception {
            JSONObject event = new JSONObject(encoded);
            if ("capture".equals(event.getString("kind"))) observation = event.getJSONObject("value");
            if ("inspection".equals(event.getString("kind"))) inspection = event.getJSONObject("value");
        }
    }

    private static byte[] readAsset(Context context, String path) throws Exception {
        try (InputStream input = context.getAssets().open(path); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[16384]; int count;
            while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
            return output.toByteArray();
        }
    }
    private static void writeBytes(File file, byte[] bytes) throws Exception {
        File parent = file.getParentFile();
        require(parent != null && (parent.isDirectory() || parent.mkdirs()), "Cannot create evidence parent");
        try (FileOutputStream output = new FileOutputStream(file)) { output.write(bytes); }
    }
    private static String sha256(byte[] bytes) throws Exception {
        StringBuilder result = new StringBuilder();
        for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes))
            result.append(String.format(Locale.ROOT, "%02x", value & 255));
        return result.toString();
    }
    private static void require(boolean valid, String reason) {
        if (!valid) throw new AssertionError(reason);
    }
}
