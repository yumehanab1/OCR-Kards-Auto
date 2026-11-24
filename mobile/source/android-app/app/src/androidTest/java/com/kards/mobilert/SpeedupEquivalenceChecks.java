package com.kards.mobilert;

import android.graphics.Bitmap;
import android.graphics.Rect;

import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.Random;

/** Synthetic CPU-only checks; main also runs with the host Bitmap adapter. */
public final class SpeedupEquivalenceChecks {
    private SpeedupEquivalenceChecks() { }

    public static void main(String[] args) throws Exception {
        checkMatcher();
        checkDecoys();
        checkColorRois();
        System.out.println("Speedup equivalence passed: luma, NCC, decoys and color ROIs");
    }

    private static void checkMatcher() {
        Random random = new Random(192);
        for (int i = 0; i < 96; i++) {
            int w = 63, h = 51, tw = 9 + i % 12, th = 13 + i % 11;
            int[] frame = random.ints(w * h).map(p -> p | 0xff000000).toArray();
            int[] glyph = random.ints(tw * th).map(p -> p | 0xff000000).toArray();
            if (i % 3 == 0) stamp(frame, w, glyph, tw, 20 + i % 11, 16);
            if (i % 3 == 1) Arrays.fill(frame, rgb(80));
            Rect roi = new Rect(i % 11 - 4, i % 13 - 5, w + 5 - i % 9, h + 7 - i % 11);
            compare(frame, w, h, glyph, tw, th, roi);
        }
        int w = 256, h = 192;
        int[] bright = random.ints(w * h, 230, 256).map(SpeedupEquivalenceChecks::rgb).toArray();
        require(Arrays.stream(bright).mapToLong(p -> (p & 255) * (p & 255)).sum()
                > Integer.MAX_VALUE, "fixture must exceed a 32-bit sum of squares");
        compare(bright, w, h, bright, w, h, new Rect(-2, -3, w + 2, h + 3));
        compare(bright, w, h, bright, w, h, new Rect(1, 0, w, h));
        compare(bright, w, h, bright, w, h, null);
    }

    private static void checkDecoys() {
        // Recreate the review's 32x32, eight-decoy geometry: every decoy
        // wins at step 8, and its full score can defeat the .85 fallback.
        int size = 32, w = 388, truth = 356;
        Random random = new Random(4);
        int[] glyph = random.ints(size * size, 0, 256).toArray();
        int[] frame = new int[w * size];
        double[] full = stats(glyph, size, size, 1), step8 = stats(glyph, size, size, 8);
        for (int i = 0; i < 8; i++) {
            int x = i * 40;
            int[] decoy = glyph.clone();
            for (int y = 0; y < size; y++) for (int j = 0; j < size; j++) {
                if ((y % 8 != 0 || j % 8 != 0) && random.nextDouble() < (i == 7 ? .13 : .19)) {
                    decoy[y * size + j] = random.nextInt(256);
                }
            }
            stamp(frame, w, decoy, size, x, 0);
            require(ncc(frame, w, glyph, size, size, x, 0, 8, step8) == 1.0, "step-8 decoy");
        }
        stamp(frame, w, glyph, size, truth, 0);
        double decoy = ncc(frame, w, glyph, size, size, 280, 0, 1, full);
        require(decoy > .85 && decoy < .94, "decoy must defeat fallback but not authorize: " + decoy);
        for (int x = 0; x <= truth; x += 8) {
            if (x > 280 || x % 40 != 0) {
                require(ncc(frame, w, glyph, size, size, x, 0, 8, step8) < 1.0, "unique step-8 seeds");
            }
        }
        // Every step-8 seed proposes only the decoy strip; even its best
        // step-4 basin can clear the rejected fallback without finding truth.
        TemplateMatcher.Match decoyOnly = reference(frame, w, size, glyph, size, size, new Rect(0, 0, 320, size));
        require(decoyOnly.bounds.left == 280 && decoyOnly.score == decoy, "decoy strip winner: "
                + decoyOnly.bounds.left + " @ " + decoyOnly.score);
        TemplateMatcher.Match match = compare(Arrays.stream(frame).map(SpeedupEquivalenceChecks::rgb).toArray(),
                w, size, Arrays.stream(glyph).map(SpeedupEquivalenceChecks::rgb).toArray(), size, size,
                new Rect(0, 0, w, size));
        require(match.bounds.left == truth && match.bounds.top == 0 && match.score == 1.0, "missed true match");
    }

    private static void checkColorRois() throws Exception {
        int w = 31, h = 23;
        int[] colors = {0xff783800, 0xff793800, 0xff963800, 0xff962300,
                0xff962481, 0xff962482, 0xff966400, 0xff7d6400, 0xff7e6400};
        int[] frame = new Random(3).ints(w * h, 0, colors.length).map(i -> colors[i]).toArray();
        Bitmap bitmap = Bitmap.createBitmap(frame, w, h, Bitmap.Config.ARGB_8888);
        try {
            Method bulk = MulliganRecognizer.class.getDeclaredMethod("orangeRatio",
                    Bitmap.class, int.class, int.class, int.class, int.class);
            bulk.setAccessible(true);
            for (int[] roi : new int[][]{{0, 0, w, h}, {0, 0, w+1, h+1}, {0, 0, 1, 1}, {w-1, h-1, w, h},
                    {3, 5, w, h}, {7, 9, 18, 14}, {8, 10, 18, 14}, {4, 6, 4, 10}}) {
                double actual = (double) bulk.invoke(null, bitmap, roi[0], roi[1], roi[2], roi[3]);
                int hits = 0, count = 0;
                for (int y = roi[1]; y < roi[3]; y += 2) for (int x = roi[0]; x < roi[2]; x += 2) {
                    int p = bitmap.getPixel(x, y), r = (p >>> 16) & 255, g = (p >>> 8) & 255, b = p & 255;
                    if (r > 120 && r > g * 1.25 && g > 35 && b < 130) hits++;
                    count++;
                }
                require(Double.compare(actual, (double) hits / count) == 0, "ROI " + Arrays.toString(roi));
            }
        } finally {
            bitmap.recycle();
        }
    }

    private static TemplateMatcher.Match compare(int[] frame, int w, int h, int[] glyph, int tw, int th, Rect roi) {
        Bitmap template = Bitmap.createBitmap(glyph, tw, th, Bitmap.Config.ARGB_8888);
        Bitmap bitmap = Bitmap.createBitmap(frame, w, h, Bitmap.Config.ARGB_8888);
        try {
            int[] source = luma(frame), needle = luma(glyph);
            require(Arrays.equals(new TemplateMatcher.Image(bitmap).luma, source), "luma mismatch");
            TemplateMatcher.Match actual = new TemplateMatcher(template).match(bitmap, roi);
            TemplateMatcher.Match expected = reference(source, w, h, needle, tw, th, roi);
            Rect a = actual.bounds, e = expected.bounds;
            require(e == null ? a == null : a != null && a.left == e.left && a.top == e.top
                    && a.right == e.right && a.bottom == e.bottom, "NCC bounds mismatch");
            require(Double.compare(actual.score, expected.score) == 0, "NCC score mismatch");
            return actual;
        } finally {
            template.recycle();
            bitmap.recycle();
        }
    }

    private static int[] luma(int[] argb) {
        return Arrays.stream(argb)
                .map(p -> (((p >>> 16) & 255) * 30 + ((p >>> 8) & 255) * 59 + (p & 255) * 11) / 100)
                .toArray();
    }

    private static TemplateMatcher.Match reference(int[] frame, int w, int h, int[] glyph, int tw, int th, Rect roi) {
        if (roi == null) return new TemplateMatcher.Match(-1, null);
        int left = Math.max(0, roi.left), top = Math.max(0, roi.top);
        int right = Math.min(w, roi.right) - tw, bottom = Math.min(h, roi.bottom) - th;
        if (left > right || top > bottom) return new TemplateMatcher.Match(-1, null);
        int bx = left, by = top;
        double best = -2;
        for (int step : new int[]{4, 1}) {
            double[] stats = stats(glyph, tw, th, step);
            int l = step == 4 ? left : Math.max(left, bx - 4), t = step == 4 ? top : Math.max(top, by - 4);
            int r = step == 4 ? right : Math.min(right, bx + 4), b = step == 4 ? bottom : Math.min(bottom, by + 4);
            best = -2;
            for (int y = t; y <= b; y += step) for (int x = l; x <= r; x += step) {
                double score = ncc(frame, w, glyph, tw, th, x, y, step, stats);
                if (score > best) { best = score; bx = x; by = y; }
            }
        }
        return new TemplateMatcher.Match(Math.max(-1.0, Math.min(1.0, best)), new Rect(bx, by, bx+tw, by+th));
    }

    private static double[] stats(int[] glyph, int w, int h, int step) {
        double sum = 0, sq = 0, count = 0;
        for (int y = 0; y < h; y += step) for (int x = 0; x < w; x += step) {
            double v = glyph[y*w+x];
            sum += v; sq += v*v; count++;
        }
        return new double[]{count, sum, sq-sum*sum/count};
    }

    private static double ncc(int[] frame, int w, int[] glyph, int tw, int th, int x, int y, int step, double[] stats) {
        double sum = 0, sq = 0, dot = 0;
        for (int j = 0; j < th; j += step) for (int i = 0; i < tw; i += step) {
            double v = frame[(y+j)*w+x+i];
            sum += v; sq += v*v; dot += v*glyph[j*tw+i];
        }
        double variance = sq-sum*sum/stats[0];
        return variance < 1 ? -1 : (dot-sum*stats[1]/stats[0])/Math.sqrt(variance*stats[2]);
    }

    private static void stamp(int[] frame, int w, int[] glyph, int tw, int x, int y) {
        for (int row = 0; row < glyph.length / tw; row++) {
            System.arraycopy(glyph, row*tw, frame, (y+row)*w+x, tw);
        }
    }

    private static int rgb(int v) { return 0xff000000 | v * 0x010101; }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
