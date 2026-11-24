package com.kards.mobilert;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.InputStream;
import java.io.IOException;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Checks for a newer APK via GitHub Releases API.
 * Repo: https://github.com/yumehanab1/OCR-Kards-Auto
 *
 * Convention for release creators:
 *   - Add a line "versionCode: NNN" anywhere in the release body.
 *   - Attach the APK as a release asset.
 *   - Without versionCode, only strictly newer numeric dotted versions qualify.
 *   - Every update must have an APK download asset.
 */
final class UpdateChecker {

    private static final String API_URL =
            "https://api.github.com/repos/yumehanab1/OCR-Kards-Auto/releases/latest";

    static final class Result {
        final boolean available;
        final String versionName;   // tag_name from GitHub
        final String changelog;     // release body (trimmed)
        final String downloadUrl;   // first non-empty .apk asset URL
        Result(boolean available, String versionName, String changelog, String downloadUrl) {
            this.available = available;
            this.versionName = versionName;
            this.changelog = changelog;
            this.downloadUrl = downloadUrl;
        }
    }

    interface Callback {
        void onResult(Result result);
        default void onError(String message) {}
    }

    private static final ExecutorService executor = Executors.newSingleThreadExecutor();
    private static final class MainThread {
        static final Handler main = new Handler(Looper.getMainLooper());
    }
    private static final Pattern VERSION_CODE_PATTERN =
            Pattern.compile("(?im)^\\s*versionCode[:\\s]+([0-9]+)\\s*$");

    static void check(Context context, Callback callback) {
        Handler main = MainThread.main;
        final int currentCode;
        final String currentName;
        try {
            android.content.pm.PackageInfo info =
                    context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
            currentCode = info.versionCode;
            currentName = info.versionName != null ? info.versionName : "";
        } catch (Exception e) {
            main.post(() -> callback.onError("无法读取当前版本号"));
            return;
        }
        executor.execute(() -> {
            try {
                HttpURLConnection conn = (HttpURLConnection) new URL(API_URL).openConnection();
                Result result = parseRelease(new JSONObject(readResponse(conn, currentName)), currentCode, currentName);
                main.post(() -> callback.onResult(result));
            } catch (Exception e) {
                main.post(() -> callback.onError("检查更新失败：" + e.getMessage()));
            }
        });
    }

    static String readResponse(HttpURLConnection conn, String currentName) throws IOException {
        try {
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(10000);
            conn.setRequestProperty("Accept", "application/vnd.github+json");
            conn.setRequestProperty("User-Agent", "KARDS-Auto-Mobile/" + currentName);
            int status = conn.getResponseCode();
            try (InputStream stream = status == 200 ? conn.getInputStream() : conn.getErrorStream()) {
                if (status != 200) throw new IOException("GitHub API 返回 " + status);
                if (stream == null) throw new IOException("GitHub API 返回空响应");
                StringBuilder text = new StringBuilder();
                BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8));
                String line;
                while ((line = reader.readLine()) != null) text.append(line).append('\n');
                return text.toString();
            }
        } finally {
            conn.disconnect();
        }
    }

    static Result parseRelease(JSONObject json, long currentCode, String currentName) {
        String tagName  = json.optString("tag_name", "").trim();
        String body     = json.optString("body", "").trim();

        // Find first .apk asset download URL
        String apkUrl = "";
        JSONArray assets = json.optJSONArray("assets");
        if (assets != null) {
            for (int i = 0; i < assets.length(); i++) {
                JSONObject asset = assets.optJSONObject(i);
                if (asset != null) {
                    String name = asset.optString("name", "");
                    if (name.toLowerCase(Locale.ROOT).endsWith(".apk")) {
                        Object url = asset.opt("browser_download_url");
                        if (url instanceof String && !((String) url).trim().isEmpty()) {
                            apkUrl = ((String) url).trim();
                            break;
                        }
                    }
                }
            }
        }

        // Determine if newer: prefer explicit versionCode in body
        boolean newer;
        Matcher m = VERSION_CODE_PATTERN.matcher(body);
        if (m.find()) {
            newer = new BigInteger(m.group(1)).compareTo(BigInteger.valueOf(currentCode)) > 0;
        } else {
            newer = newerNumericVersion(tagName, currentName);
        }

        // Trim body for display; strip the versionCode line
        String changelog = body.replaceAll("(?im)^\\s*versionCode[:\\s]+[0-9]+\\s*\\n?", "").trim();
        if (changelog.length() > 300) changelog = changelog.substring(0, 300) + "…";

        return new Result(newer && !apkUrl.isEmpty(), tagName, changelog, apkUrl);
    }

    static boolean newerNumericVersion(String remote, String current) {
        if (remote == null || current == null) return false;
        String pattern = "v?[0-9]+\\.[0-9]+\\.[0-9]+";
        if (!remote.matches(pattern) || !current.matches(pattern)) return false;
        String[] a = remote.replaceFirst("^v", "").split("\\.");
        String[] b = current.replaceFirst("^v", "").split("\\.");
        for (int i = 0; i < a.length; i++) {
            int order = new BigInteger(a[i]).compareTo(new BigInteger(b[i]));
            if (order != 0) return order > 0;
        }
        return false;
    }
}
