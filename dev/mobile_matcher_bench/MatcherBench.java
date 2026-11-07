package com.kards.mobilert;

import android.graphics.Bitmap;
import android.graphics.Rect;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class MatcherBench {
    private static final int WARMUP = 3;
    private static final int REPEAT = 15;

    private static final class Raw {
        final int width, height;
        final int[] pixels;
        Raw(int width, int height, int[] pixels) {
            this.width = width; this.height = height; this.pixels = pixels;
        }
        Bitmap bitmap() { return new Bitmap(width, height, pixels); }
    }

    private static Raw read(String path) throws IOException {
        ByteBuffer buffer = ByteBuffer.wrap(Files.readAllBytes(Paths.get(path))).order(ByteOrder.LITTLE_ENDIAN);
        int width = buffer.getInt(), height = buffer.getInt();
        int[] pixels = new int[width * height];
        for (int i = 0; i < pixels.length; i++) pixels[i] = buffer.getInt();
        return new Raw(width, height, pixels);
    }

    private static int[] luma(Raw raw) {
        int[] out = new int[raw.pixels.length];
        for (int i = 0; i < out.length; i++) {
            int p = raw.pixels[i];
            out[i] = (((p >>> 16) & 255) * 30 + ((p >>> 8) & 255) * 59 + (p & 255) * 11) / 100;
        }
        return out;
    }

    public static void main(String[] args) throws Exception {
        String root = args[0];
        List<String> lines = Files.readAllLines(Paths.get(root, "cases.txt"));
        Map<String, TemplateMatcher> matchers = new HashMap<>();
        Map<String, BaselineMatcher> baselines = new HashMap<>();
        List<Long> fastTimes = new ArrayList<>(), baseTimes = new ArrayList<>();
        List<Long> fastMatched = new ArrayList<>(), baseMatched = new ArrayList<>();
        int mismatches = 0, fallbackCases = 0, regressions = 0, improvements = 0;
        int fastExpected = 0, baseExpected = 0;
        double maxScoreDelta = 0;
        for (String line : lines) {
            String[] f = line.split("\\|");
            String label = f[0], templatePath = Paths.get(root, f[1]).toString();
            Raw frame = read(Paths.get(root, f[2]).toString());
            int l = Integer.parseInt(f[3]), t = Integer.parseInt(f[4]);
            int r = Integer.parseInt(f[5]), b = Integer.parseInt(f[6]);
            int ex = Integer.parseInt(f[7]), ey = Integer.parseInt(f[8]);
            TemplateMatcher matcher = matchers.get(templatePath);
            BaselineMatcher baseline = baselines.get(templatePath);
            if (matcher == null) {
                Raw template = read(templatePath);
                matcher = new TemplateMatcher(template.bitmap());
                baseline = new BaselineMatcher(luma(template), template.width, template.height);
                matchers.put(templatePath, matcher);
                baselines.put(templatePath, baseline);
            }
            TemplateMatcher.Image image = new TemplateMatcher.Image(frame.bitmap());
            Rect roi = new Rect(l, t, r, b);
            int[] fl = luma(frame);
            for (int i = 0; i < WARMUP; i++) { matcher.match(image, roi); baseline.match(fl, frame.width, frame.height, l, t, r, b); }
            long start = System.nanoTime();
            TemplateMatcher.Match fast = null;
            for (int i = 0; i < REPEAT; i++) fast = matcher.match(image, roi);
            long fastNs = System.nanoTime() - start;
            start = System.nanoTime();
            double[] base = null;
            for (int i = 0; i < REPEAT; i++) base = baseline.match(fl, frame.width, frame.height, l, t, r, b);
            long baseNs = System.nanoTime() - start;
            double delta = Math.abs(fast.score - base[0]);
            maxScoreDelta = Math.max(maxScoreDelta, delta);
            boolean positionMatch = fast.bounds.left == (int) base[1] && fast.bounds.top == (int) base[2];
            if (!positionMatch) mismatches++;
            boolean expectedMatch = fast.bounds.left == ex && fast.bounds.top == ey;
            boolean baseExpectedMatch = (int) base[1] == ex && (int) base[2] == ey;
            if (expectedMatch) fastExpected++;
            if (baseExpectedMatch) baseExpected++;
            if (fast.score < 0.90) fallbackCases++;
            if (fast.score < base[0] - 1e-6) regressions++;
            if (fast.score > base[0] + 1e-6) improvements++;
            fastTimes.add(fastNs / REPEAT);
            baseTimes.add(baseNs / REPEAT);
            if (ex >= 0) { fastMatched.add(fastNs / REPEAT); baseMatched.add(baseNs / REPEAT); }
            System.out.printf("%s|%.6f|%.6f|%.6f|%.6f|%d|%d|%d|%d|%d|%d|%b%n",
                    label, fastNs / 1e6 / REPEAT, baseNs / 1e6 / REPEAT,
                    fast.score, base[0], fast.bounds.left, fast.bounds.top,
                    (int) base[1], (int) base[2], ex, ey, expectedMatch);
        }
        double fastSum = 0, baseSum = 0, fastMatchSum = 0, baseMatchSum = 0;
        for (long v : fastTimes) fastSum += v;
        for (long v : baseTimes) baseSum += v;
        for (long v : fastMatched) fastMatchSum += v;
        for (long v : baseMatched) baseMatchSum += v;
        System.out.printf("SUMMARY|cases=%d|fast_avg_ns=%.0f|base_avg_ns=%.0f|ratio=%.3f|matched_cases=%d|matched_ratio=%.3f|mismatches=%d|regressions=%d|improvements=%d|max_score_delta=%.8f|fallback_cases=%d|fast_expected=%d|base_expected=%d%n",
                lines.size(), fastSum / lines.size(), baseSum / lines.size(),
                baseSum / fastSum, fastMatched.size(), baseMatchSum / fastMatchSum,
                mismatches, regressions, improvements, maxScoreDelta, fallbackCases,
                fastExpected, baseExpected);
    }
}
