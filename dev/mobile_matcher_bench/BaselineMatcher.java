package com.kards.mobilert;

final class BaselineMatcher {
    private final int tw, th;
    private final int[] tl;
    private final double[] fullStats, coarseStats;

    BaselineMatcher(int[] luma, int width, int height) {
        tw = width; th = height; tl = luma;
        fullStats = stats(1); coarseStats = stats(4);
    }

    double[] match(int[] frame, int fw, int fh, int left, int top, int right, int bottom) {
        int r = Math.min(fw, right) - tw, b = Math.min(fh, bottom) - th;
        double best = -2.0;
        int bx = Math.max(0, left), by = Math.max(0, top);
        for (int y = Math.max(0, top); y <= b; y += 4)
            for (int x = Math.max(0, left); x <= r; x += 4) {
                double score = correlation(frame, fw, x, y, 4, coarseStats);
                if (score > best) { best = score; bx = x; by = y; }
            }
        int cx = bx, cy = by;
        best = -2.0;
        for (int y = Math.max(Math.max(0, top), cy - 4); y <= Math.min(b, cy + 4); y++)
            for (int x = Math.max(Math.max(0, left), cx - 4); x <= Math.min(r, cx + 4); x++) {
                double score = correlation(frame, fw, x, y, 1, fullStats);
                if (score > best) { best = score; bx = x; by = y; }
            }
        return new double[]{Math.max(-1.0, Math.min(1.0, best)), bx, by};
    }

    private double[] stats(int step) {
        double sum = 0, squared = 0, count = 0;
        for (int y = 0; y < th; y += step)
            for (int x = 0; x < tw; x += step) {
                int v = tl[y * tw + x];
                sum += v; squared += v * v; count++;
            }
        return new double[]{count, sum, squared - sum * sum / count};
    }

    private double correlation(int[] fl, int fw, int left, int top, int step, double[] st) {
        double sum = 0, squared = 0, product = 0;
        for (int y = 0; y < th; y += step) {
            int fo = (top + y) * fw + left, to = y * tw;
            for (int x = 0; x < tw; x += step) {
                int v = fl[fo + x];
                sum += v; squared += v * v; product += v * tl[to + x];
            }
        }
        double variance = squared - sum * sum / st[0];
        if (variance < 1.0) return -1.0;
        return (product - sum * st[1] / st[0]) / Math.sqrt(variance * st[2]);
    }
}
