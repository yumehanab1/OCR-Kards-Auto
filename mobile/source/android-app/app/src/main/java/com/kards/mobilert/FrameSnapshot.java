package com.kards.mobilert;

import android.graphics.Bitmap;

/**
 * Immutable metadata wrapper for one screenshot delivered to the mobile core.
 *
 * <p>The bitmap is an ARGB_8888 software copy.  The caller owns the snapshot
 * and must close it when the observation is complete; this keeps the native
 * pixel buffer bounded while the APK is polling the foreground game.</p>
 */
public final class FrameSnapshot implements AutoCloseable {
    private final Bitmap bitmap;
    private final long capturedAtMillis;
    private final int sourceWidth;
    private final int sourceHeight;

    public FrameSnapshot(Bitmap bitmap, long capturedAtMillis) {
        this(bitmap, capturedAtMillis, bitmap == null ? 0 : bitmap.getWidth(),
                bitmap == null ? 0 : bitmap.getHeight());
    }

    public FrameSnapshot(Bitmap bitmap, long capturedAtMillis, int sourceWidth, int sourceHeight) {
        if (bitmap == null) {
            throw new IllegalArgumentException("bitmap must not be null");
        }
        if (bitmap.isRecycled()) {
            throw new IllegalArgumentException("bitmap must not be recycled");
        }
        this.bitmap = bitmap;
        this.capturedAtMillis = capturedAtMillis;
        this.sourceWidth = sourceWidth;
        this.sourceHeight = sourceHeight;
    }

    public Bitmap bitmap() {
        return bitmap;
    }

    public int width() {
        return bitmap.getWidth();
    }

    public int height() {
        return bitmap.getHeight();
    }

    public long capturedAtMillis() {
        return capturedAtMillis;
    }

    public int sourceWidth() {
        return sourceWidth;
    }

    public int sourceHeight() {
        return sourceHeight;
    }

    public boolean isUsable() {
        return !bitmap.isRecycled() && bitmap.getWidth() > 0 && bitmap.getHeight() > 0;
    }

    @Override
    public void close() {
        if (!bitmap.isRecycled()) {
            bitmap.recycle();
        }
    }
}
