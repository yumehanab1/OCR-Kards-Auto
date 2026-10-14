package com.kards.mobilert;

import android.graphics.Bitmap;
import android.graphics.Rect;

import java.util.ArrayList;
import java.util.List;

/**
 * Small, dependency-free first pass for the Android board.
 *
 * <p>This intentionally does not attempt OCR, card identity, attack/defence
 * parsing, or suppression recognition.  It only looks for the stable mobile
 * layout anchors (the two orange credit panels and dark wooden play area) and
 * returns geometry candidates.  All coordinates are in the existing normalized
 * 1280x720 core space; other sizes are rejected instead of guessing a layout.
 * </p>
 */
public final class BitmapBoardRecognizer implements BoardRecognizer {
    private static final int BASE_W = 1280;
    private static final int BASE_H = 720;

    @Override
    public BoardObservation recognize(FrameSnapshot snapshot) {
        if (snapshot == null || !snapshot.isUsable()) {
            return BoardObservation.unknown("帧为空或已释放");
        }
        return recognize(snapshot.bitmap());
    }

    /** Public for offline Bitmap self-checks and future frame replay. */
    public BoardObservation recognize(Bitmap bitmap) {
        if (bitmap == null || bitmap.isRecycled()) {
            return BoardObservation.unknown("Bitmap 不可用");
        }
        if (bitmap.getWidth() != BASE_W || bitmap.getHeight() != BASE_H) {
            return BoardObservation.unknown("核心帧尺寸未归一化为 1280×720");
        }

        // These panels are present in the mobile game but absent on the KARDS
        // main menu.  Require both sides so a single orange card cannot open
        // the action path by accident.
        float topCredits = orangeRatio(bitmap, 20, 115, 115, 220);
        float bottomCredits = orangeRatio(bitmap, 20, 490, 115, 605);
        float boardDark = darkRatio(bitmap, 135, 90, 1085, 615);
        boolean credits = topCredits >= 0.025f && bottomCredits >= 0.025f;
        boolean woodBoard = boardDark >= 0.52f;
        boolean inGame = credits && woodBoard;

        if (!inGame) {
            // A bright central promo/deck panel is a safe non-game hint.  A
            // blank/black or permission frame remains UNKNOWN instead of
            // being mistaken for a menu.
            float centralLight = lightRatio(bitmap, 180, 100, 1100, 610);
            if (centralLight >= 0.045f) {
                return BoardObservation.recognized(BoardObservation.State.NON_GAME,
                        "未检测到对局资源栏；中心区域符合主界面/牌组页特征",
                        false, false, BoardObservation.FrontlineOwner.UNKNOWN,
                        new ArrayList<BoardObservation.Candidate>());
            }
            return BoardObservation.unknown("未达到对局锚点门槛（资源栏/木质棋盘）");
        }

        List<BoardObservation.Candidate> candidates = new ArrayList<>();
        // HQ cards shift horizontally as units are added or removed.  Do not
        // publish a stale fixed HQ rectangle; expose the two support bands as
        // low-confidence geometry until a dynamic shield/card detector exists.
        addIfTextured(bitmap, candidates, BoardObservation.Candidate.Kind.SUPPORT,
                rect(200, 70, 1120, 270), 180);
        addIfTextured(bitmap, candidates, BoardObservation.Candidate.Kind.SUPPORT,
                rect(200, 420, 1120, 610), 180);

        // Do not collapse these two rows into an owner claim.  The divider and
        // colour accents vary with animations; expose only candidates until a
        // calibrated owner detector is added.
        addIfTextured(bitmap, candidates, BoardObservation.Candidate.Kind.FRONTLINE,
                rect(420, 245, 1030, 420), 300);
        addIfTextured(bitmap, candidates, BoardObservation.Candidate.Kind.FRONTLINE,
                rect(420, 425, 1030, 590), 300);

        Rect endRect = rect(1068, 470, 1248, 535);
        float endLight = lightRatio(bitmap, endRect.left, endRect.top, endRect.right, endRect.bottom);
        float endOrange = orangeRatio(bitmap, endRect.left, endRect.top, endRect.right, endRect.bottom);
        // This is deliberately named a candidate: the same slot can render
        // “敌方” while the opponent is thinking.  OCR/template confirmation
        // must precede any future input implementation.
        boolean endCandidate = endLight >= 0.010f || endOrange >= 0.004f;
        if (endCandidate) {
            candidates.add(new BoardObservation.Candidate(
                    BoardObservation.Candidate.Kind.END_TURN, endRect,
                    endOrange >= 0.004f ? 450 : 250));
        }

        // A light button-shaped slot is not enough to call it our turn: the
        // opponent renders a related control in the same area.  Only the
        // orange variant is a tentative MY_TURN hint, and authorization is
        // still forced false by BoardObservation.recognized().
        BoardObservation.State state = endOrange >= 0.004f
                ? BoardObservation.State.MY_TURN : BoardObservation.State.IN_GAME;
        String reason = "已检测到移动端对局布局；HQ/前线仅输出候选，牌名与压制状态未知";
        if (endCandidate) reason += "；右侧回合按钮槽存在（需模板/OCR确认文字）";
        return BoardObservation.recognized(state, reason, true, endCandidate,
                BoardObservation.FrontlineOwner.UNKNOWN, candidates);
    }

    private static void addIfTextured(Bitmap bitmap, List<BoardObservation.Candidate> out,
                                      BoardObservation.Candidate.Kind kind, Rect r,
                                      int confidence) {
        if (texture(bitmap, r.left, r.top, r.right, r.bottom) >= 0.015f) {
            out.add(new BoardObservation.Candidate(kind, r, confidence));
        }
    }

    private static Rect rect(int l, int t, int r, int b) {
        return new Rect(l, t, r, b);
    }

    private static float orangeRatio(Bitmap b, int l, int t, int r, int bottom) {
        int[] c = stats(b, l, t, r, bottom);
        return c[1] == 0 ? 0f : c[0] / (float) c[1];
    }

    private static float lightRatio(Bitmap b, int l, int t, int r, int bottom) {
        int[] c = stats(b, l, t, r, bottom);
        return c[2] == 0 ? 0f : c[3] / (float) c[2];
    }

    private static float darkRatio(Bitmap b, int l, int t, int r, int bottom) {
        int[] c = stats(b, l, t, r, bottom);
        return c[2] == 0 ? 0f : c[4] / (float) c[2];
    }

    /** Texture fraction catches card edges/art while ignoring flat wood. */
    private static float texture(Bitmap b, int l, int t, int r, int bottom) {
        int w = b.getWidth(), h = b.getHeight();
        int x0 = clamp(Math.round(l * w / (float) BASE_W), 0, w - 1);
        int y0 = clamp(Math.round(t * h / (float) BASE_H), 0, h - 1);
        int x1 = clamp(Math.round(r * w / (float) BASE_W), x0 + 1, w);
        int y1 = clamp(Math.round(bottom * h / (float) BASE_H), y0 + 1, h);
        int count = 0, textured = 0;
        int stepX = Math.max(2, (x1 - x0) / 32);
        int stepY = Math.max(2, (y1 - y0) / 20);
        for (int y = y0 + 1; y < y1 - 1; y += stepY) {
            for (int x = x0 + 1; x < x1 - 1; x += stepX) {
                int p = b.getPixel(x, y);
                int luma = luma(p);
                int dx = Math.abs(luma - luma(b.getPixel(x - 1, y)));
                int dy = Math.abs(luma - luma(b.getPixel(x, y - 1)));
                if (dx + dy >= 35) textured++;
                count++;
            }
        }
        return count == 0 ? 0f : textured / (float) count;
    }

    /** Returns orange, count, count, light, dark. */
    private static int[] stats(Bitmap b, int l, int t, int r, int bottom) {
        int w = b.getWidth(), h = b.getHeight();
        int x0 = clamp(Math.round(l * w / (float) BASE_W), 0, w - 1);
        int y0 = clamp(Math.round(t * h / (float) BASE_H), 0, h - 1);
        int x1 = clamp(Math.round(r * w / (float) BASE_W), x0 + 1, w);
        int y1 = clamp(Math.round(bottom * h / (float) BASE_H), y0 + 1, h);
        int orange = 0, light = 0, dark = 0, count = 0;
        int stepX = Math.max(1, (x1 - x0) / 64);
        int stepY = Math.max(1, (y1 - y0) / 36);
        for (int y = y0; y < y1; y += stepY) {
            for (int x = x0; x < x1; x += stepX) {
                int p = b.getPixel(x, y);
                int red = (p >>> 16) & 255, green = (p >>> 8) & 255, blue = p & 255;
                int lum = (red * 30 + green * 59 + blue * 11) / 100;
                if (red > 120 && red > green * 1.25f && green > 35 && blue < 130) orange++;
                if (lum >= 170) light++;
                if (lum <= 75) dark++;
                count++;
            }
        }
        return new int[]{orange, count, count, light, dark};
    }

    private static int luma(int p) {
        return (((p >>> 16) & 255) * 30 + ((p >>> 8) & 255) * 59 + (p & 255) * 11) / 100;
    }

    private static int clamp(int v, int min, int max) {
        return Math.max(min, Math.min(max, v));
    }
}
