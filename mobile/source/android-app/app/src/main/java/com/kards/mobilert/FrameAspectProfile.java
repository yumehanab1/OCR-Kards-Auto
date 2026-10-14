package com.kards.mobilert;

/** Supported landscape capture aspect profiles selected from source metadata. */
final class FrameAspectProfile {
    private FrameAspectProfile() { }

    static String classify(int width, int height) {
        if (width <= 0 || height <= 0) return "unsupported";
        double ratio = width / (double) height;
        if (ratio < 1.70 || ratio > 2.30) return "unsupported";
        if (ratio < 1.90) return "standard_16_9";
        if (ratio < 2.05) return "wide_18_9";
        if (ratio < 2.17) return "wide_19_9";
        return "wide_20_9";
    }

    static boolean supported(int width, int height) {
        return !"unsupported".equals(classify(width, height));
    }
}
