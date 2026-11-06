package com.kards.mobilert;

import android.accessibilityservice.AccessibilityService;
import android.graphics.Bitmap;
import android.hardware.HardwareBuffer;
import android.view.Display;

import java.util.concurrent.Executor;

final class SystemScreenshot {
    interface Result {
        void onBitmap(Bitmap bitmap);
        void onFailure(String reason);
    }

    private SystemScreenshot() { }

    @android.annotation.TargetApi(34)
    static void capture(KardsAccessibilityService service, Executor executor,
                        boolean windowCapture, int windowId, Result result) {
        AccessibilityService.TakeScreenshotCallback receiver =
                new AccessibilityService.TakeScreenshotCallback() {
            @Override
            public void onSuccess(AccessibilityService.ScreenshotResult screenshot) {
                HardwareBuffer buffer = screenshot.getHardwareBuffer();
                if (buffer == null) {
                    result.onFailure("截图能力：系统返回空 HardwareBuffer。");
                    return;
                }
                Bitmap hardware = null;
                try {
                    hardware = Bitmap.wrapHardwareBuffer(buffer, screenshot.getColorSpace());
                    if (hardware == null) {
                        result.onFailure("截图能力：无法包装 HardwareBuffer。");
                        return;
                    }
                    Bitmap software = hardware.copy(Bitmap.Config.ARGB_8888, false);
                    if (software == null) {
                        result.onFailure("截图能力：无法复制为软件 Bitmap。");
                        return;
                    }
                    result.onBitmap(software);
                } catch (RuntimeException error) {
                    result.onFailure("截图能力：Bitmap 转换失败：" + error.getClass().getSimpleName());
                } finally {
                    if (hardware != null && !hardware.isRecycled()) hardware.recycle();
                    buffer.close();
                }
            }

            @Override
            public void onFailure(int errorCode) {
                if (errorCode == AccessibilityService.ERROR_TAKE_SCREENSHOT_INTERNAL_ERROR
                        || errorCode == AccessibilityService.ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT) {
                    result.onFailure("temporary_window_capture_error");
                    return;
                }
                result.onFailure("截图能力：失败，错误码=" + errorCode + "；后续接入 MediaProjection 备用通道。");
            }
        };
        if (windowCapture) service.takeScreenshotOfWindow(windowId, executor, receiver);
        else service.takeScreenshot(Display.DEFAULT_DISPLAY, executor, receiver);
    }
}
