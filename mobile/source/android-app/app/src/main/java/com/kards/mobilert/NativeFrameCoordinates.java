package com.kards.mobilert;

/** Pure source-pixel contract for the dynamic pipeline, without image resampling. */
final class NativeFrameCoordinates {
    private NativeFrameCoordinates() { }

    static boolean valid(int width, int height, int sourceWidth, int sourceHeight) {
        return width == sourceWidth && height == sourceHeight
                && FrameAspectProfile.supported(sourceWidth, sourceHeight);
    }

    static boolean point(double x, double y, int width, int height) {
        return Double.isFinite(x) && Double.isFinite(y)
                && x > 0 && x < width && y > 0 && y < height;
    }

    static double[] physical(double x, double y, int width, int height,
                             int sourceWidth, int sourceHeight) {
        if (!valid(width, height, sourceWidth, sourceHeight)
                || !point(x, y, width, height)) throw new IllegalArgumentException("invalid_native_point");
        return new double[]{x, y};
    }
}
