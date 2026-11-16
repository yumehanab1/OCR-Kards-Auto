package com.kards.mobilert;

import android.graphics.Bitmap;
import android.graphics.Rect;

/** Small luminance NCC matcher. No device access, native library, or mutable global state. */
public final class TemplateMatcher {
    private static final int TOP = 8;
    private static final double FALLBACK_SCORE = 0.85;

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
            luma = new int[width * height];
            bitmap.getPixels(luma, 0, width, 0, 0, width, height);
            for (int i = 0; i < luma.length; i++) {
                int p = luma[i];
                luma[i] = (((p >>> 16) & 255) * 30 + ((p >>> 8) & 255) * 59
                        + (p & 255) * 11) / 100;
            }
        }
    }

    private final Image template;
    private final double[] fullStats;
    private final double[] coarseStats;
    private final double[] step8Stats;
    private final double[] step2Stats;
    private final boolean useStep8;

    public TemplateMatcher(Bitmap templateBitmap) {
        if (templateBitmap == null || templateBitmap.isRecycled()) {
            throw new IllegalArgumentException("template unavailable");
        }
        template = new Image(templateBitmap);
        fullStats = templateStats(1);
        step2Stats = templateStats(2);
        coarseStats = templateStats(4);
        step8Stats = templateStats(8);
        if (fullStats[2] < 1.0 || coarseStats[2] < 1.0) {
            throw new IllegalArgumentException("template lacks texture");
        }
        useStep8 = step8Stats[0] >= 16 && step8Stats[2] >= 1.0;
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
        Match fast = useStep8 ? matchPyramid(frame, left, top, right, bottom)
                : matchFull(frame, left, top, right, bottom);
        if (fast.score < FALLBACK_SCORE) return matchFull(frame, left, top, right, bottom);
        return fast;
    }

    private Match matchPyramid(Image frame, int left, int top, int right, int bottom) {
        double[] scores = new double[TOP];
        int[] xs = new int[TOP], ys = new int[TOP];
        for (int i = 0; i < TOP; i++) scores[i] = -2.0;
        for (int y = top; y <= bottom; y += 8) {
            for (int x = left; x <= right; x += 8) {
                double score = correlation(frame, x, y, 8, step8Stats);
                if (score > scores[TOP - 1]) {
                    int at = TOP - 1;
                    while (at > 0 && score > scores[at - 1]) {
                        scores[at] = scores[at - 1]; xs[at] = xs[at - 1]; ys[at] = ys[at - 1]; at--;
                    }
                    scores[at] = score; xs[at] = x; ys[at] = y;
                }
            }
        }
        double best4 = -2.0;
        int best4X = left, best4Y = top;
        for (int i = 0; i < TOP; i++) {
            if (scores[i] < -1.5) continue;
            for (int y = Math.max(top, ys[i] - 8); y <= Math.min(bottom, ys[i] + 8); y += 4) {
                for (int x = Math.max(left, xs[i] - 8); x <= Math.min(right, xs[i] + 8); x += 4) {
                    double score = correlation(frame, x, y, 4, coarseStats);
                    if (score > best4) { best4 = score; best4X = x; best4Y = y; }
                }
            }
        }
        double best2 = -2.0;
        int best2X = best4X, best2Y = best4Y;
        for (int y = Math.max(top, best4Y - 4); y <= Math.min(bottom, best4Y + 4); y += 2) {
            for (int x = Math.max(left, best4X - 4); x <= Math.min(right, best4X + 4); x += 2) {
                double score = correlation(frame, x, y, 2, step2Stats);
                if (score > best2) { best2 = score; best2X = x; best2Y = y; }
            }
        }
        double best = -2.0;
        int bestX = best2X, bestY = best2Y;
        for (int y = Math.max(top, best2Y - 2); y <= Math.min(bottom, best2Y + 2); y++) {
            for (int x = Math.max(left, best2X - 2); x <= Math.min(right, best2X + 2); x++) {
                double score = correlation(frame, x, y, 1, fullStats);
                if (score > best) { best = score; bestX = x; bestY = y; }
            }
        }
        return result(best, bestX, bestY);
    }

    private Match matchFull(Image frame, int left, int top, int right, int bottom) {
        double best = -2.0;
        int bestX = left, bestY = top;
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
        return result(best, bestX, bestY);
    }

    private Match result(double best, int bestX, int bestY) {
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
        long sum = 0, squared = 0, product = 0;
        final int[] tl = template.luma, fl = frame.luma;
        final int tw = template.width, th = template.height, fw = frame.width;
        for (int y = 0; y < th; y += step) {
            int frameOffset = (top + y) * fw + left;
            int templateOffset = y * tw;
            for (int x = 0; x < tw; x += step) {
                int value = fl[frameOffset + x];
                sum += value;
                squared += (long) value * value;
                product += (long) value * tl[templateOffset + x];
            }
        }
        double variance = (double) squared - (double) sum * sum / stats[0];
        if (variance < 1.0) return -1.0;
        return ((double) product - (double) sum * stats[1] / stats[0])
                / Math.sqrt(variance * stats[2]);
    }
}
