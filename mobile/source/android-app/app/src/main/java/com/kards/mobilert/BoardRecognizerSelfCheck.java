package com.kards.mobilert;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;

/**
 * Tiny offline smoke check that needs no JUnit/AndroidX dependency.  It is
 * useful from an instrumentation shell or a temporary Activity button while
 * the real KARDS frame corpus is being connected.
 */
public final class BoardRecognizerSelfCheck {
    private BoardRecognizerSelfCheck() { }

    public static String run() {
        Bitmap game = Bitmap.createBitmap(1280, 720, Bitmap.Config.ARGB_8888);
        Canvas gc = new Canvas(game);
        gc.drawColor(Color.rgb(52, 38, 26));
        Paint p = new Paint();
        p.setColor(Color.rgb(220, 125, 18));
        gc.drawRect(20, 120, 115, 220, p);
        gc.drawRect(20, 490, 115, 605, p);
        p.setColor(Color.rgb(150, 135, 115));
        p.setStyle(Paint.Style.STROKE);
        p.setStrokeWidth(6f);
        gc.drawRect(285, 80, 445, 278, p);
        gc.drawRect(285, 422, 445, 620, p);
        gc.drawRect(420, 245, 1030, 420, p);
        gc.drawRect(420, 425, 1030, 590, p);
        p.setColor(Color.WHITE);
        p.setStyle(Paint.Style.FILL);
        gc.drawRect(1068, 470, 1248, 535, p);

        Bitmap menu = Bitmap.createBitmap(1280, 720, Bitmap.Config.ARGB_8888);
        Canvas mc = new Canvas(menu);
        mc.drawColor(Color.rgb(115, 90, 65));
        p.setColor(Color.rgb(230, 210, 180));
        mc.drawRect(200, 120, 1080, 600, p);

        BitmapBoardRecognizer recognizer = new BitmapBoardRecognizer();
        BoardObservation gameResult = recognizer.recognize(game);
        BoardObservation menuResult = recognizer.recognize(menu);
        game.recycle();
        menu.recycle();
        if (!gameResult.isGameScreen() || gameResult.state() == BoardObservation.State.UNKNOWN) {
            return "FAIL: synthetic game was not recognized (" + gameResult.reason() + ")";
        }
        if (gameResult.isActionAuthorized()) {
            return "FAIL: recognizer authorized an action";
        }
        ActionResult action = new ReadOnlyActionExecutor().execute(
                ActionRequest.tap(640f, 360f), gameResult);
        if (action.didSendInput() || action.status() != ActionResult.Status.REJECTED) {
            return "FAIL: read-only executor sent input";
        }
        if (menuResult.state() != BoardObservation.State.NON_GAME) {
            return "FAIL: synthetic menu was not rejected (" + menuResult.displayState() + ")";
        }
        return "PASS: game=" + gameResult.displayState()
                + ", candidates=" + gameResult.candidates().size()
                + ", actionAuthorized=false; menu=NON_GAME";
    }
}
