package com.kards.mobilert;

import android.content.Context;
import android.graphics.Bitmap;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

/**
 * Saved-frame replay boundary.  It intentionally consumes a decoded Bitmap,
 * normalizes only the known 16:9 device size, and writes read-only JSON into
 * the app-private files directory.  No input API is reachable from here.
 */
public final class FrameReplay {
    private static final int BASE_W = 1280;
    private static final int BASE_H = 720;

    private FrameReplay() { }

    /**
     * Analyze one decoded PNG.  The bitmap is consumed and recycled before
     * returning; callers should not use it afterwards.
     */
    public static String analyze(Bitmap bitmap, String source, MobileCore core) {
        if (bitmap == null || bitmap.isRecycled()) {
            return BoardObservationJson.replayJson(BoardObservation.unknown("PNG 解码为空"), source,
                    0, 0, 0, 0);
        }
        int sourceWidth = bitmap.getWidth();
        int sourceHeight = bitmap.getHeight();
        Bitmap normalized = normalize(bitmap);
        if (normalized == null) {
            String json = BoardObservationJson.replayJson(
                    BoardObservation.unknown("回放帧尺寸不支持；只接受 1280×720 或 1920×1080"),
                    source, sourceWidth, sourceHeight, 0, 0);
            recycle(bitmap);
            return json;
        }
        FrameSnapshot snapshot = new FrameSnapshot(normalized, System.currentTimeMillis(),
                sourceWidth, sourceHeight);
        try {
            BoardObservation observation = (core == null ? new ReadOnlyMobileCore() : core)
                    .observe(snapshot);
            return BoardObservationJson.replayJson(observation, source, sourceWidth, sourceHeight,
                    normalized.getWidth(), normalized.getHeight());
        } finally {
            snapshot.close();
            if (normalized != bitmap) {
                recycle(bitmap);
            }
        }
    }

    /** Save the most recent replay result without requesting storage access. */
    public static File writeResult(Context context, String json) throws IOException {
        if (context == null) throw new IOException("Context 为空");
        File directory = new File(context.getFilesDir(), "frame-replay");
        if (!directory.isDirectory() && !directory.mkdirs()) {
            throw new IOException("无法创建回放目录");
        }
        File result = new File(directory, "last-observation.json");
        try (FileOutputStream stream = new FileOutputStream(result, false)) {
            stream.write((json == null ? "{}" : json).getBytes(StandardCharsets.UTF_8));
        }
        return result;
    }

    private static Bitmap normalize(Bitmap bitmap) {
        if (bitmap.getWidth() == BASE_W && bitmap.getHeight() == BASE_H) return bitmap;
        if (FrameAspectProfile.supported(bitmap.getWidth(), bitmap.getHeight())) {
            return Bitmap.createScaledBitmap(bitmap, BASE_W, BASE_H, true);
        }
        return null;
    }

    private static void recycle(Bitmap bitmap) {
        if (bitmap != null && !bitmap.isRecycled()) bitmap.recycle();
    }
}
