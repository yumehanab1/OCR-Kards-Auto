package com.kards.mobilert;

import android.content.ComponentName;
import android.content.Context;
import android.content.pm.InstrumentationInfo;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Rect;
import android.os.SystemClock;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

/**
 * Saved-frame Android Bitmap regression only. Call run(Instrumentation.getContext()).
 * PNG fixtures live only in the test APK. The recognizer reads the installed target
 * APK's real assets, whose hashes must match the fixture manifest before replay.
 * This class never captures a display, launches KARDS, or dispatches input.
 */
public final class MulliganRecognizerChecks {
    private static final String MANIFEST = "mulligan-replay/manifest.json";

    private MulliganRecognizerChecks() { }

    public static JSONObject run(Context testContext) throws Exception {
        JSONObject report = new JSONObject();
        JSONArray cases = new JSONArray();
        int failures = 0;
        long started = SystemClock.elapsedRealtime();
        report.put("suite", "mulligan-recognizer-saved-frame-v1");
        report.put("device_inputs", 0);
        report.put("live_capture_count", 0);
        report.put("live_game_action_verified", false);
        report.put("cases", cases);
        try {
            require(testContext != null, "Instrumentation test context required");
            InstrumentationInfo instrumentation = testContext.getPackageManager().getInstrumentationInfo(
                    new ComponentName(testContext.getPackageName(),
                            "com.kards.mobilert.DeviceRegressionInstrumentation"), 0);
            require(instrumentation.targetPackage != null, "Instrumentation target package missing");
            Context targetContext = testContext.createPackageContext(instrumentation.targetPackage, 0);
            report.put("test_package", testContext.getPackageName());
            report.put("target_package", targetContext.getPackageName());
            byte[] manifestBytes = readAsset(testContext, MANIFEST);
            report.put("manifest_sha256", sha256(manifestBytes));
            JSONObject manifest = new JSONObject(new String(manifestBytes, StandardCharsets.UTF_8));
            require(manifest.getInt("schema_version") == 1, "Unsupported fixture schema");
            JSONArray fixtures = manifest.getJSONArray("fixtures");
            require(fixtures.length() == 41 && manifest.getInt("expected_case_count") == 41,
                    "Expected exactly 41 saved-frame fixtures");
            JSONArray templates = manifest.getJSONArray("production_templates");
            require(templates.length() == 6, "Expected six production templates");
            JSONArray templateChecks = new JSONArray();
            report.put("production_template_checks", templateChecks);
            for (int index = 0; index < templates.length(); index++) {
                JSONObject expected = templates.getJSONObject(index);
                String asset = expected.getString("asset");
                String actual = sha256(readAsset(targetContext, asset));
                JSONObject check = new JSONObject();
                check.put("asset", asset);
                check.put("sha256", actual);
                check.put("expected_sha256", expected.getString("sha256"));
                templateChecks.put(check);
                require(actual.equals(expected.getString("sha256")),
                        "Production template SHA mismatch: " + asset);
                check.put("status", "passed");
            }
            MulliganRecognizer recognizer = new MulliganRecognizer(targetContext);
            for (int index = 0; index < fixtures.length(); index++) {
                JSONObject fixture = fixtures.getJSONObject(index);
                JSONObject item = new JSONObject();
                cases.put(item);
                long caseStarted = SystemClock.elapsedRealtime();
                Bitmap raw = null;
                Bitmap normalized = null;
                try {
                    item.put("label", fixture.getString("label"));
                    item.put("source", fixture.getString("path"));
                    item.put("evidence_group", fixture.getString("group"));
                    item.put("expected_phase", fixture.getString("expected"));
                    item.put("device_inputs", 0);
                    byte[] png = readAsset(testContext, fixture.getString("asset"));
                    String actualHash = sha256(png);
                    item.put("source_sha256", actualHash);
                    require(actualHash.equals(fixture.getString("sha256")), "Fixture SHA mismatch");
                    require(png.length == fixture.getInt("byte_length"), "Fixture byte length mismatch");
                    BitmapFactory.Options bounds = new BitmapFactory.Options();
                    bounds.inJustDecodeBounds = true;
                    BitmapFactory.decodeByteArray(png, 0, png.length, bounds);
                    require("image/png".equals(bounds.outMimeType), "Fixture is not PNG");
                    require(bounds.outWidth == fixture.getInt("width")
                            && bounds.outHeight == fixture.getInt("height"), "Fixture dimensions changed");
                    require((bounds.outWidth == 1280 && bounds.outHeight == 720)
                                    || (bounds.outWidth == 1920 && bounds.outHeight == 1080),
                            "Uncalibrated source dimensions");
                    BitmapFactory.Options options = new BitmapFactory.Options();
                    options.inScaled = false;
                    options.inPreferredConfig = Bitmap.Config.ARGB_8888;
                    raw = BitmapFactory.decodeByteArray(png, 0, png.length, options);
                    require(raw != null, "PNG decode failed");
                    item.put("source_width", raw.getWidth());
                    item.put("source_height", raw.getHeight());
                    if (raw.getWidth() != 1280 || raw.getHeight() != 720) {
                        require(recognizer.inspect(raw).phase == MulliganRecognizer.Phase.UNKNOWN,
                                "Raw unnormalized frame accepted");
                        normalized = Bitmap.createScaledBitmap(raw, 1280, 720, true);
                    } else {
                        normalized = raw;
                    }
                    long inspectStarted = SystemClock.elapsedRealtime();
                    MulliganRecognizer.Result first = recognizer.inspect(normalized);
                    item.put("inspect_duration_ms", SystemClock.elapsedRealtime() - inspectStarted);
                    long repeatStarted = SystemClock.elapsedRealtime();
                    MulliganRecognizer.Result second = recognizer.inspect(normalized);
                    item.put("repeat_inspect_duration_ms", SystemClock.elapsedRealtime() - repeatStarted);
                    item.put("actual_phase", first.phase.name());
                    item.put("score", first.score);
                    item.put("confirm_score", first.confirmScore);
                    item.put("title_score", first.titleScore);
                    item.put("end_turn_score", first.endTurnScore);
                    item.put("template_id", first.templateId);
                    item.put("reason", first.reason);
                    item.put("target_bounds", boundsJson(first.targetBounds));
                    require(first.phase.name().equals(fixture.getString("expected")), "Unexpected phase");
                    require(signature(first).equals(signature(second)), "Non-deterministic repeated replay");
                    if (first.phase == MulliganRecognizer.Phase.UNKNOWN) {
                        require(first.targetBounds == null, "UNKNOWN contains an input target");
                    } else {
                        require(Double.isFinite(first.score) && first.score >= MulliganRecognizer.MIN_SCORE
                                && first.score <= 1.0, "Invalid positive score");
                        Rect rect = first.targetBounds;
                        require(rect != null && rect.left >= 0 && rect.top >= 0
                                && rect.right <= 1280 && rect.bottom <= 720
                                && rect.width() > 0 && rect.height() > 0, "Invalid positive target");
                        require(!first.templateId.isEmpty(), "Missing positive template id");
                        if (fixture.getString("label").startsWith("compact_opening")) {
                            require(first.templateId.equals("mulligan_ok_btn_compact"),
                                    "Compact opening did not use its distinct layout identity");
                        } else if (first.phase == MulliganRecognizer.Phase.MULLIGAN_CONFIRM) {
                            require(first.templateId.equals("mulligan_ok_btn"),
                                    "Standard opening layout identity changed");
                        }
                    }
                    item.put("status", "passed");
                } catch (Throwable error) {
                    failures++;
                    item.put("status", "failed");
                    item.put("error", error.toString());
                } finally {
                    if (normalized != null && normalized != raw && !normalized.isRecycled()) normalized.recycle();
                    if (raw != null && !raw.isRecycled()) raw.recycle();
                    item.put("duration_ms", SystemClock.elapsedRealtime() - caseStarted);
                }
            }
        } catch (Throwable error) {
            failures++;
            report.put("setup_error", error.toString());
        }
        report.put("status", failures == 0 && cases.length() == 41 ? "passed" : "failed");
        report.put("failure_count", failures);
        report.put("case_count", cases.length());
        report.put("duration_ms", SystemClock.elapsedRealtime() - started);
        return report;
    }

    private static JSONObject boundsJson(Rect rect) throws Exception {
        if (rect == null) return null;
        JSONObject value = new JSONObject();
        value.put("left", rect.left); value.put("top", rect.top);
        value.put("right", rect.right); value.put("bottom", rect.bottom);
        return value;
    }

    private static String signature(MulliganRecognizer.Result result) {
        Rect rect = result.targetBounds;
        return result.phase + "|" + result.templateId + "|" + result.score + "|"
                + result.confirmScore + "|" + result.titleScore + "|" + result.endTurnScore + "|"
                + (rect == null ? "null" : rect.left + "," + rect.top + "," + rect.right + "," + rect.bottom);
    }

    private static byte[] readAsset(Context context, String path) throws Exception {
        try (InputStream stream = context.getAssets().open(path);
             ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[16 * 1024];
            int length;
            while ((length = stream.read(buffer)) != -1) bytes.write(buffer, 0, length);
            return bytes.toByteArray();
        }
    }

    private static String sha256(byte[] bytes) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);
        StringBuilder output = new StringBuilder(digest.length * 2);
        for (byte value : digest) output.append(String.format(Locale.ROOT, "%02x", value & 255));
        return output.toString();
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
