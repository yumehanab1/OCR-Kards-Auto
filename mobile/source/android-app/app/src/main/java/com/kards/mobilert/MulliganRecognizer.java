package com.kards.mobilert;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Rect;

import java.io.IOException;
import java.io.InputStream;

/**
 * Visual evidence for one keep-all opening confirmation, never a combat authorization.
 * Only inspect fresh normalized 1280x720 frames; the caller owns timing, foreground,
 * stability, dispatch, and stopping. Assets/provenance.json records exact source frames.
 */
public final class MulliganRecognizer {
    public enum Phase { MULLIGAN_CONFIRM, CONFIRMED_MY_TURN, CONFIRMED_OPPONENT_TURN,
        WAITING_OPPONENT_MULLIGAN, UNKNOWN }
    public static final String ASSET_DIRECTORY = "mulligan-one-shot/";
    public static final double MIN_SCORE = 0.94;

    public static final class Result {
        public final Phase phase;
        public final Rect targetBounds;
        public final double score;
        public final String reason;
        public final String templateId;
        public final double confirmScore, titleScore, endTurnScore;

        /** Public to permit device-independent session tests with injected evidence. */
        public Result(Phase phase, Rect targetBounds, double score, String reason, String templateId) {
            this(phase, targetBounds, score, reason, templateId, -1.0, -1.0, -1.0);
        }

        private Result(Phase phase, Rect targetBounds, double score, String reason,
                       String templateId, double confirmScore, double titleScore, double endTurnScore) {
            this.phase = phase == null ? Phase.UNKNOWN : phase;
            this.targetBounds = targetBounds == null ? null
                    : new Rect(targetBounds.left, targetBounds.top, targetBounds.right, targetBounds.bottom);
            this.score = score;
            this.reason = reason == null ? "unspecified" : reason;
            this.templateId = templateId == null ? "" : templateId;
            this.confirmScore = confirmScore; this.titleScore = titleScore; this.endTurnScore = endTurnScore;
        }
    }

    private TemplateMatcher confirm, title, compactConfirm, compactTitle, endOrange, endWhite;
    private String loadFailure;

    public MulliganRecognizer(Context context) {
        try {
            if (context == null) throw new IllegalArgumentException("context unavailable");
            confirm = load(context, "mulligan_ok_btn.png");
            title = load(context, "mulligan_title.png");
            compactConfirm = load(context, "mulligan_ok_btn_compact.png");
            compactTitle = load(context, "mulligan_title_compact.png");
            endOrange = load(context, "end_turn_btn.png");
            endWhite = load(context, "end_turn_btn_white.png");
        } catch (IOException | RuntimeException error) {
            loadFailure = "template_load_failed:" + error.getClass().getSimpleName();
        }
    }

    private static TemplateMatcher load(Context context, String name) throws IOException {
        Bitmap bitmap;
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inScaled = false;
        options.inPreferredConfig = Bitmap.Config.ARGB_8888;
        try (InputStream stream = context.getAssets().open(ASSET_DIRECTORY + name)) {
            bitmap = BitmapFactory.decodeStream(stream, null, options);
        }
        if (bitmap == null) throw new IOException("cannot decode " + name);
        try { return new TemplateMatcher(bitmap); }
        finally { bitmap.recycle(); }
    }

    public Result inspect(Bitmap bitmap) {
        if (loadFailure != null) return unknown(loadFailure, -1, -1, -1);
        if (bitmap == null || bitmap.isRecycled()
                || bitmap.getWidth() != 1280 || bitmap.getHeight() != 720) {
            return unknown("requires_normalized_1280x720", -1, -1, -1);
        }
        TemplateMatcher.Image image = new TemplateMatcher.Image(bitmap);
        TemplateMatcher.Match confirmMatch = confirm.match(image, new Rect(426, 557, 854, 720));
        TemplateMatcher.Match titleMatch = title.match(image, new Rect(425, 25, 870, 135));
        double c = confirmMatch.score, t = titleMatch.score;
        // A generic confirmation button is insufficient. Require the complete
        // opening instruction plus both game resource anchors, in their known ROIs.
        boolean resources = orangeRatio(bitmap, 20, 115, 115, 220) >= 0.025
                && orangeRatio(bitmap, 20, 490, 115, 605) >= 0.025;
        if (c >= MIN_SCORE && t >= MIN_SCORE && resources) {
            return new Result(Phase.MULLIGAN_CONFIRM, confirmMatch.bounds, Math.min(c, t),
                    "opening_title_and_confirm_with_resource_anchors", "mulligan_ok_btn", c, t, -1);
        }
        // The HUD can reflow after returning from another Activity while the
        // screenshot and card/board geometry stay unchanged. This is an explicit
        // second calibrated layout, never a free-scale search or mixed-profile pair.
        TemplateMatcher.Match compactConfirmMatch = compactConfirm.match(image,
                new Rect(489, 616, 791, 720));
        TemplateMatcher.Match compactTitleMatch = compactTitle.match(image,
                new Rect(482, 10, 801, 104));
        double cc = compactConfirmMatch.score, ct = compactTitleMatch.score;
        boolean compactResources = orangeRatio(bitmap, 20, 94, 79, 148) >= 0.025
                && orangeRatio(bitmap, 20, 566, 79, 621) >= 0.025;
        if (cc >= MIN_SCORE && ct >= MIN_SCORE && compactResources) {
            return new Result(Phase.MULLIGAN_CONFIRM, compactConfirmMatch.bounds, Math.min(cc, ct),
                    "compact_opening_title_and_confirm_with_resource_anchors",
                    "mulligan_ok_btn_compact", cc, ct, -1);
        }
        TemplateMatcher.Match orange = endOrange.match(image, new Rect(1017, 415, 1280, 590));
        TemplateMatcher.Match white = endWhite.match(image, new Rect(1017, 415, 1280, 590));
        TemplateMatcher.Match end = orange.score >= white.score ? orange : white;
        String endId = orange.score >= white.score ? "end_turn_btn" : "end_turn_btn_white";
        // Openings/transition frames and dimmed card previews are not post-action
        // success. Missing either anchor also rejects black screens and dialogs.
        boolean compactCloser = Math.min(cc, ct) > Math.min(c, t);
        double diagnosticConfirm = compactCloser ? cc : c;
        double diagnosticTitle = compactCloser ? ct : t;
        if (Math.max(c, cc) < 0.70 && Math.max(t, ct) < 0.70 && resources && end.score >= MIN_SCORE
                && darkRatio(image, 135, 90, 1085, 615) >= 0.52) {
            return new Result(Phase.CONFIRMED_MY_TURN, end.bounds, end.score,
                    "exact_end_turn_template_with_board_anchors", endId,
                    diagnosticConfirm, diagnosticTitle, end.score);
        }
        return unknown("unconfirmed_opening_or_turn_context", diagnosticConfirm, diagnosticTitle, end.score);
    }

    private static Result unknown(String reason, double c, double t, double end) {
        return new Result(Phase.UNKNOWN, null, Math.max(c, Math.max(t, end)), reason, "", c, t, end);
    }

    private static double orangeRatio(Bitmap bitmap, int l, int t, int r, int b) {
        int hit = 0, count = 0;
        for (int y = t; y < b; y += 2) for (int x = l; x < r; x += 2) {
            int p = bitmap.getPixel(x, y);
            int red = (p >>> 16) & 255, green = (p >>> 8) & 255, blue = p & 255;
            if (red > 120 && red > green * 1.25 && green > 35 && blue < 130) hit++;
            count++;
        }
        return hit / (double) count;
    }

    private static double darkRatio(TemplateMatcher.Image image, int l, int t, int r, int b) {
        int hit = 0, count = 0;
        for (int y = t; y < b; y += 4) for (int x = l; x < r; x += 4) {
            if (image.luma[y * image.width + x] <= 75) hit++;
            count++;
        }
        return hit / (double) count;
    }
}
