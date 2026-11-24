package com.kards.mobilert;

import android.annotation.TargetApi;
import android.graphics.Rect;
import android.os.Build;
import android.util.DisplayMetrics;
import android.view.WindowManager;

import java.util.function.Supplier;

/** Bounds in display pixels, including the system-bar and cutout areas. */
final class DisplayBounds {
    private DisplayBounds() { }

    static Rect get(WindowManager windows) {
        if (windows == null) throw new IllegalStateException("display_missing");
        return select(Build.VERSION.SDK_INT, () -> realDisplayBounds(windows), () -> Api30.bounds(windows));
    }

    static Rect select(int sdk, Supplier<Rect> realDisplay, Supplier<Rect> windowMetrics) {
        return (sdk >= Build.VERSION_CODES.R ? windowMetrics : realDisplay).get();
    }

    @SuppressWarnings("deprecation")
    private static Rect realDisplayBounds(WindowManager windows) {
        DisplayMetrics metrics = new DisplayMetrics();
        windows.getDefaultDisplay().getRealMetrics(metrics);
        if (metrics.widthPixels <= 0 || metrics.heightPixels <= 0)
            throw new IllegalStateException("display_geometry_invalid");
        return new Rect(0, 0, metrics.widthPixels, metrics.heightPixels);
    }

    @TargetApi(30)
    private static final class Api30 {
        static Rect bounds(WindowManager windows) {
            return new Rect(windows.getCurrentWindowMetrics().getBounds());
        }
    }
}
