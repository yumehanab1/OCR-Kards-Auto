package com.kards.mobilert;

import android.graphics.Rect;
import android.os.Build;
import android.util.DisplayMetrics;
import android.view.WindowManager;

final class DisplayBounds {
    private DisplayBounds() { }

    static Rect get(WindowManager windows) {
        if (windows == null) throw new IllegalStateException("display_missing");
        if (Build.VERSION.SDK_INT >= 30) return Api30.bounds(windows);
        DisplayMetrics metrics = new DisplayMetrics();
        windows.getDefaultDisplay().getRealMetrics(metrics);
        if (metrics.widthPixels <= 0 || metrics.heightPixels <= 0)
            throw new IllegalStateException("display_geometry_invalid");
        return new Rect(0, 0, metrics.widthPixels, metrics.heightPixels);
    }

    @android.annotation.TargetApi(30)
    private static final class Api30 {
        static Rect bounds(WindowManager windows) {
            return new Rect(windows.getCurrentWindowMetrics().getBounds());
        }
    }
}
