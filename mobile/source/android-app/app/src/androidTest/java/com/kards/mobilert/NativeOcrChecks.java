package com.kards.mobilert;

import android.content.Context;
import android.os.SystemClock;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

/** Saved long-screen pixels only; no capture, input or game launch. */
final class NativeOcrChecks {
    static JSONObject run(Context test, Context target) throws Exception {
        JSONArray manifest;
        try (InputStream in = test.getAssets().open("native-ocr-probe/manifest.json")) {
            manifest = new JSONArray(new String(in.readAllBytes(), StandardCharsets.UTF_8));
        }
        JSONArray frames = new JSONArray();
        File directory = new File(target.getFilesDir(), "native-ocr-probe");
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IllegalStateException("native_probe_directory");
        if (!Python.isStarted()) Python.start(new AndroidPlatform(target));
        NativeOnnxModels engine = NativeOnnxModels.get(target);
        String characters;
        try (InputStream in = target.getAssets().open("native-ocr/characters.json")) {
            characters = new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
        {
            for (int index = 0; index < manifest.length(); index++) {
                JSONObject item = manifest.getJSONObject(index);
                byte[] bytes;
                try (InputStream in = test.getAssets().open("native-ocr-probe/" + item.getString("file"))) {
                    bytes = in.readAllBytes();
                }
                StringBuilder digest = new StringBuilder();
                for (byte b : MessageDigest.getInstance("SHA-256").digest(bytes)) digest.append(String.format("%02x", b & 255));
                if (!digest.toString().equals(item.getString("sha256"))) throw new IllegalStateException("native_probe_hash_mismatch");
                File png = new File(directory, item.getString("file"));
                try (FileOutputStream out = new FileOutputStream(png)) { out.write(bytes); }
                long started = SystemClock.elapsedRealtime();
                JSONObject result = new JSONObject(Python.getInstance().getModule("apk_native.onnx_ocr")
                        .callAttr("inspect_saved", png.getAbsolutePath(), engine, characters).toString());
                if (result.getInt("width") != 1839 || result.getInt("height") != 822)
                    throw new IllegalStateException("native_ocr_resampled_geometry");
                frames.put(result.put("elapsed_ms", SystemClock.elapsedRealtime() - started)
                        .put("file", item.getString("file")).put("expected_state", item.getString("expected_state"))
                        .put("source_sha256", item.getString("sha256")));
            }
        }
        return new JSONObject().put("frames", frames).put("frame_count", frames.length())
                .put("device_inputs", 0).put("game_launches", 0).put("capture_count", 0)
                .put("scope", "saved_long_screen_ocr_probe_not_live_match");
    }
}
