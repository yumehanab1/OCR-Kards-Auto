package com.kards.mobilert;

import android.accessibilityservice.AccessibilityService;
import android.annotation.TargetApi;

import java.util.concurrent.Executor;

/** The window-scoped platform call was introduced separately in Android 14. */
@TargetApi(34)
final class WindowScreenshotApi34 {
    private WindowScreenshotApi34() { }

    static void capture(AccessibilityService service, int windowId, Executor executor,
                        SystemScreenshotApi30.PixelsCallback callback) {
        SystemScreenshotApi30.capture(receiver -> service.takeScreenshotOfWindow(windowId, executor, receiver),
                callback);
    }
}
