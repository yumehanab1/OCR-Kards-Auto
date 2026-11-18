package com.kards.mobilert;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStreamReader;
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
 *   - If no versionCode line is present, the banner shows whenever
 *     the tag name differs from the installed versionName.
 */
final class UpdateChecker {

    private static final String API_URL =
            "https://api.github.com/repos/yumehanab1/OCR-Kards-Auto/releases/latest";

    static final class Result {
        final boolean available;
        final String versionName;   // tag_name from GitHub
        final String changelog;     // release body (trimmed)
        final String downloadUrl;   // first .apk asset URL, or release HTML URL
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
    private static final Handler main = new Handler(Looper.getMainLooper());
    private static final Pattern VERSION_CODE_PATTERN =
            Pattern.compile("(?im)^\\s*versionCode[:\\s]+([0-9]+)\\s*$");

    static void check(Context context, Callback callback) {
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
                conn.setConnectTimeout(10000);
                conn.setReadTimeout(10000);
                conn.setRequestProperty("Accept", "application/vnd.github+json");
                conn.setRequestProperty("User-Agent", "KARDS-Auto-Mobile/" + currentName);
                int status = conn.getResponseCode();
                if (status != 200) {
                    main.post(() -> callback.onError("GitHub API 返回 " + status));
                    return;
                }
                StringBuilder sb = new StringBuilder();
                try (BufferedReader r = new BufferedReader(
                        new InputStreamReader(conn.getInputStream(), "UTF-8"))) {
                    String line;
                    while ((line = r.readLine()) != null) sb.append(line);
                }
                JSONObject json = new JSONObject(sb.toString());
                String tagName  = json.optString("tag_name", "").trim();
                String body     = json.optString("body", "").trim();
                String htmlUrl  = json.optString("html_url", "");

                // Find first .apk asset download URL
                String apkUrl = htmlUrl;
                JSONArray assets = json.optJSONArray("assets");
                if (assets != null) {
                    for (int i = 0; i < assets.length(); i++) {
                        JSONObject asset = assets.optJSONObject(i);
                        if (asset != null) {
                            String name = asset.optString("name", "");
                            if (name.toLowerCase().endsWith(".apk")) {
                                apkUrl = asset.optString("browser_download_url", htmlUrl);
                                break;
                            }
                        }
                    }
                }

                // Determine if newer: prefer explicit versionCode in body
                boolean newer;
                Matcher m = VERSION_CODE_PATTERN.matcher(body);
                if (m.find()) {
                    int remoteCode = Integer.parseInt(m.group(1));
                    newer = remoteCode > currentCode;
                } else {
                    // Fallback: newer if tag differs from installed versionName
                    newer = !tagName.isEmpty() && !tagName.equals(currentName)
                            && !tagName.equals("v" + currentName);
                }

                // Trim body for display; strip the versionCode line
                String changelog = body.replaceAll("(?im)^\\s*versionCode[:\\s]+[0-9]+\\s*\\n?", "").trim();
                if (changelog.length() > 300) changelog = changelog.substring(0, 300) + "…";

                final boolean finalNewer = newer;
                final String finalTag    = tagName;
                final String finalLog    = changelog;
                final String finalUrl    = apkUrl;
                main.post(() -> callback.onResult(
                        new Result(finalNewer, finalTag, finalLog, finalUrl)));
            } catch (Exception e) {
                main.post(() -> callback.onError("检查更新失败：" + e.getMessage()));
            }
        });
    }
}
