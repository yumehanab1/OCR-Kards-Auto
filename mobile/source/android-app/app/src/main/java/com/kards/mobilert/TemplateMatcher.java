package com.kards.mobilert;

import android.graphics.Bitmap;
import android.graphics.Rect;

/** Small luminance NCC matcher. No device access, native library, or mutable global state. */
public final class TemplateMatcher {
    public static final class Match {
        public final double score;
        public final Rect bounds;
        Match(double score, Rect bounds) { this.score = score; this.bounds = bounds; }
    }

    static final class Image {
        final int width, height;
        final int[] luma;
        Image(Bitmap bitmap) {
            width = bitmap.getWidth(); height = bitmap.getHeight();
            int[] pixels = new int[width * height];
            bitmap.getPixels(pixels, 0, width, 0, 0, width, height);
            luma = new int[pixels.length];
            for (int i = 0; i < pixels.length; i++) {
                int p = pixels[i];
                luma[i] = (((p >>> 16) & 255) * 30 + ((p >>> 8) & 255) * 59
                        + (p & 255) * 11) / 100;
            }
        }
    }

    private final Image template;
    private final double[] fullStats;
    private final double[] coarseStats;

    public TemplateMatcher(Bitmap templateBitmap) {
        if (templateBitmap == null || templateBitmap.isRecycled()) {
            throw new IllegalArgumentException("template unavailable");
        }
        template = new Image(templateBitmap);
        fullStats = templateStats(1);
        coarseStats = templateStats(4);
        if (fullStats[2] < 1.0 || coarseStats[2] < 1.0) {
            throw new IllegalArgumentException("template lacks texture");
        }
    }

    public Match match(Bitmap frame, Rect searchRegion) {
        if (frame == null || frame.isRecycled()) return new Match(-1.0, null);
        return match(new Image(frame), searchRegion);
    }

    Match match(Image frame, Rect searchRegion) {
        if (searchRegion == null) return new Match(-1.0, null);
        int left = Math.max(0, searchRegion.left);
        int top = Math.max(0, searchRegion.top);
        int right = Math.min(frame.width, searchRegion.right) - template.width;
        int bottom = Math.min(frame.height, searchRegion.bottom) - template.height;
        if (left > right || top > bottom) return new Match(-1.0, null);
        double best = -2.0;
        int bestX = left, bestY = top;
        // Coarse position/pixel sampling limits work to a small fixed ROI. A full
        // pixel refinement produces the reported score; coarse scores never authorize.
        for (int y = top; y <= bottom; y += 4) {
            for (int x = left; x <= right; x += 4) {
                double score = correlation(frame, x, y, 4, coarseStats);
                if (score > best) { best = score; bestX = x; bestY = y; }
            }
        }
        int coarseX = bestX, coarseY = bestY;
        best = -2.0;
        for (int y = Math.max(top, coarseY - 4); y <= Math.min(bottom, coarseY + 4); y++) {
            for (int x = Math.max(left, coarseX - 4); x <= Math.min(right, coarseX + 4); x++) {
                double score = correlation(frame, x, y, 1, fullStats);
                if (score > best) { best = score; bestX = x; bestY = y; }
            }
        }
        return new Match(Math.max(-1.0, Math.min(1.0, best)),
                new Rect(bestX, bestY, bestX + template.width, bestY + template.height));
    }

    private double[] templateStats(int step) {
        double sum = 0, squared = 0, count = 0;
        for (int y = 0; y < template.height; y += step) {
            for (int x = 0; x < template.width; x += step) {
                int value = template.luma[y * template.width + x];
                sum += value; squared += value * value; count++;
            }
        }
        return new double[]{count, sum, squared - sum * sum / count};
    }

    private double correlation(Image frame, int left, int top, int step, double[] stats) {
        double sum = 0, squared = 0, product = 0;
        for (int y = 0; y < template.height; y += step) {
            int frameOffset = (top + y) * frame.width + left;
            int templateOffset = y * template.width;
            for (int x = 0; x < template.width; x += step) {
                int value = frame.luma[frameOffset + x];
                sum += value; squared += value * value;
                product += value * template.luma[templateOffset + x];
            }
        }
        double variance = squared - sum * sum / stats[0];
        if (variance < 1.0) return -1.0;
        return (product - sum * stats[1] / stats[0]) / Math.sqrt(variance * stats[2]);
    }
}
