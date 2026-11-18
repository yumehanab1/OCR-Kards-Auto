package com.kards.mobilert;

import android.graphics.Bitmap;
import android.graphics.Matrix;
import android.view.Surface;

/** Natural device geometry and lossless quarter-turn back to source-display coordinates. */
final class ProjectionGeometry {
    // Stable Android DisplayManager flag since API 21; hidden from older SDK stubs.
    // It couples the virtual output to the logical display orientation, without privileged flags.
    static final int ROTATES_WITH_CONTENT = 1 << 7;

    private ProjectionGeometry() { }

    static boolean swapsAxes(int rotation) {
        if (rotation < Surface.ROTATION_0 || rotation > Surface.ROTATION_270)
            throw new IllegalArgumentException("invalid_display_rotation");
        return rotation == Surface.ROTATION_90 || rotation == Surface.ROTATION_270;
    }

    static int bufferWidth(int width, int height, int rotation) {
        return swapsAxes(rotation) ? height : width;
    }

    static int bufferHeight(int width, int height, int rotation) {
        return swapsAxes(rotation) ? width : height;
    }

    static Bitmap toLogical(Bitmap source, int rotation) {
        swapsAxes(rotation); // Reject invalid rotations even for a null/recycled caller.
        if (source == null || source.isRecycled()) throw new IllegalArgumentException("invalid_source_bitmap");
        if (rotation == Surface.ROTATION_0) return source;
        Matrix inverse = new Matrix();
        inverse.setRotate(-90f * rotation);
        return Bitmap.createBitmap(source, 0, 0, source.getWidth(), source.getHeight(), inverse, false);
    }

}
