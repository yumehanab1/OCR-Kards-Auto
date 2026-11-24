package com.kards.mobilert;

import android.accessibilityservice.AccessibilityService;
import android.annotation.TargetApi;
import android.graphics.Bitmap;
import android.hardware.HardwareBuffer;
import android.view.Display;

import java.util.concurrent.Executor;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

/** Adapts the API 30 display screenshot without exposing platform callback types to API 29. */
@TargetApi(30)
final class SystemScreenshotApi30 {
    interface PixelsCallback {
        /** Takes ownership of the software bitmap. */
        void onPixels(Bitmap pixels, long timestampMs);
        void onFailure(String reason);
    }

    private SystemScreenshotApi30() { }

    static void capture(AccessibilityService service, Executor executor, PixelsCallback callback) {
        capture(receiver -> service.takeScreenshot(Display.DEFAULT_DISPLAY, executor, receiver), callback);
    }

    /** Both platform paths use this receiver and the same terminal delivery contract. */
    static void capture(Consumer<AccessibilityService.TakeScreenshotCallback> request, PixelsCallback callback) {
        Terminal terminal = new Terminal(callback::onFailure);
        terminal.request(() -> request.accept(new AccessibilityService.TakeScreenshotCallback() {
            @Override public void onSuccess(AccessibilityService.ScreenshotResult screenshot) {
                Bitmap software = null;
                long timestampMs = -1;
                String failure = null;
                try (HardwareBuffer buffer = screenshot.getHardwareBuffer()) {
                    if (buffer == null) {
                        failure = "截图能力：系统返回空 HardwareBuffer。";
                    } else {
                        Bitmap hardware = Bitmap.wrapHardwareBuffer(buffer, screenshot.getColorSpace());
                        if (hardware == null) {
                            failure = "截图能力：无法包装 HardwareBuffer。";
                        } else {
                            try {
                                software = hardware.copy(Bitmap.Config.ARGB_8888, false);
                                if (software == null) failure = "截图能力：无法复制为软件 Bitmap。";
                                timestampMs = screenshot.getTimestamp();
                            } finally {
                                hardware.recycle();
                            }
                        }
                    }
                } catch (RuntimeException error) {
                    failure = "截图能力：Bitmap 转换失败，" + error.getClass().getSimpleName();
                }
                // Buffer and wrapped bitmap are gone before downstream code can run.
                if (failure != null) {
                    if (software != null) software.recycle();
                    terminal.failure(failure);
                } else {
                    final Bitmap pixels = software;
                    final long timestamp = timestampMs;
                    terminal.success(() -> callback.onPixels(pixels, timestamp), pixels::recycle);
                }
            }

            @Override public void onFailure(int errorCode) {
                if (errorCode == AccessibilityService.ERROR_TAKE_SCREENSHOT_INTERNAL_ERROR
                        || errorCode == AccessibilityService.ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT) {
                    terminal.failure("temporary_window_capture_error");
                } else {
                    terminal.failure("截图能力：失败，错误码 " + errorCode + "；可尝试兼容截图。");
                }
            }
        }));
    }

    static final class Terminal {
        private final AtomicBoolean delivered = new AtomicBoolean();
        private final Consumer<String> onFailure;

        Terminal(Consumer<String> onFailure) { this.onFailure = onFailure; }

        void request(Runnable start) {
            try {
                start.run();
            } catch (RuntimeException error) {
                // A synchronous consumer may throw after delivery has already been committed.
                if (!delivered.compareAndSet(false, true)) throw error;
                onFailure.accept("截图能力：请求失败，" + error.getClass().getSimpleName());
            }
        }

        void success(Runnable deliver, Runnable discard) {
            if (delivered.compareAndSet(false, true)) deliver.run();
            else discard.run();
        }

        void failure(String reason) {
            if (delivered.compareAndSet(false, true)) onFailure.accept(reason);
        }
    }
}
