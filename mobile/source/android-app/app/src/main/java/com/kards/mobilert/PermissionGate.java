package com.kards.mobilert;

import android.Manifest;
import android.app.Activity;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.projection.MediaProjectionManager;
import android.net.Uri;
import android.os.Build;
import android.os.PowerManager;
import android.provider.Settings;

import java.util.ArrayList;
import java.util.List;

final class PermissionGate {
    static final String ACCESSIBILITY = "accessibility";
    static final String CAPTURE = "capture";
    static final String BATTERY = "battery";
    static final String NOTIFICATION = "notification";
    static final String SCREEN = "screen";
    static final String GAME = "game";

    static final class Item {
        final String key, title, detail;
        final boolean ok, required, actionable;
        Item(String key, String title, String detail, boolean ok, boolean required, boolean actionable) {
            this.key = key;
            this.title = title;
            this.detail = detail;
            this.ok = ok;
            this.required = required;
            this.actionable = actionable;
        }
    }

    private PermissionGate() { }

    static boolean captureRequired() { return Build.VERSION.SDK_INT < 30; }

    static List<Item> check(Context context) {
        List<Item> items = new ArrayList<>();
        boolean connected = KardsAccessibilityService.instance() != null;
        items.add(new Item(ACCESSIBILITY, "无障碍权限",
                connected ? "已连接 · 可以识别和操作" : "未连接 · 点右侧开启",
                connected, true, true));

        if (Build.VERSION.SDK_INT >= 34) {
            items.add(new Item(CAPTURE, "画面读取", "系统窗口截图 · 无需授权", true, false, false));
        } else {
            boolean ready = CompatCaptureService.isReady();
            boolean required = captureRequired();
            String detail = ready ? "已启用" : required ? "Android 10 必需 · 点右侧授权" : "系统截图黑屏时才需要";
            items.add(new Item(CAPTURE, "屏幕共享授权", detail,
                    ready || !required, required, !ready));
        }

        PowerManager power = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
        boolean batteryOk = power == null || power.isIgnoringBatteryOptimizations(context.getPackageName());
        items.add(new Item(BATTERY, "后台运行",
                batteryOk ? "已忽略电池优化" : "未忽略 · 服务可能被系统停止",
                batteryOk, false, !batteryOk));

        boolean notifyOk;
        if (Build.VERSION.SDK_INT >= 33) {
            notifyOk = context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                    == PackageManager.PERMISSION_GRANTED;
        } else {
            NotificationManager manager =
                    (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            notifyOk = manager == null || manager.areNotificationsEnabled();
        }
        items.add(new Item(NOTIFICATION, "通知权限",
                notifyOk ? "已允许" : "未允许 · 前台服务需要通知",
                notifyOk, false, !notifyOk));

        int width = 0, height = 0;
        try {
            android.graphics.Rect bounds = DisplayBounds.get(
                    (android.view.WindowManager) context.getSystemService(Context.WINDOW_SERVICE));
            width = bounds.width();
            height = bounds.height();
        } catch (RuntimeException ignored) { }
        String profile = FrameAspectProfile.classify(width, height);
        boolean aspectOk = FrameAspectProfile.supported(width, height);
        String readable = "unsupported".equals(profile) ? "比例不支持"
                : "standard_16_9".equals(profile) ? "16:9"
                : "wide_18_9".equals(profile) ? "18:9"
                : "wide_19_9".equals(profile) ? "19.5:9" : "20:9";
        items.add(new Item(SCREEN, "画面比例",
                width + "×" + height + " · " + readable + (aspectOk ? " · 支持" : " · 需调整"),
                aspectOk, false, false));

        boolean gameOk = GamePackages.findLaunchable(
                context.getPackageManager()::getLaunchIntentForPackage) != null;
        items.add(new Item(GAME, "KARDS",
                gameOk ? "已安装" : "未检测到支持的包名",
                gameOk, false, false));
        return items;
    }

    static String firstMissing(Context context) {
        for (Item item : check(context)) if (item.required && !item.ok) return item.key;
        return "";
    }

    static boolean canStart(Context context) {
        return firstMissing(context).isEmpty();
    }

    static String missingMessage(Context context) {
        String key = firstMissing(context);
        if (ACCESSIBILITY.equals(key)) return "请先开启对战助手的无障碍权限。";
        if (CAPTURE.equals(key)) return "Android 10 需要屏幕共享授权才能读取画面，请在弹窗中确认。";
        return "还差一步准备，请完成上方必需授权。";
    }

    static void open(Activity activity, String key, int captureRequest, int notificationRequest) {
        try {
            switch (key) {
                case ACCESSIBILITY:
                    activity.startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS));
                    break;
                case CAPTURE:
                    if (Build.VERSION.SDK_INT >= 34) return;
                    MediaProjectionManager projection = activity.getSystemService(MediaProjectionManager.class);
                    if (projection != null)
                        activity.startActivityForResult(projection.createScreenCaptureIntent(), captureRequest);
                    break;
                case BATTERY:
                    try {
                        activity.startActivity(new Intent(
                                Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                                Uri.parse("package:" + activity.getPackageName())));
                    } catch (RuntimeException error) {
                        activity.startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
                    }
                    break;
                case NOTIFICATION:
                    if (Build.VERSION.SDK_INT >= 33) {
                        activity.requestPermissions(
                                new String[]{Manifest.permission.POST_NOTIFICATIONS}, notificationRequest);
                    } else {
                        Intent settings = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS);
                        settings.putExtra(Settings.EXTRA_APP_PACKAGE, activity.getPackageName());
                        activity.startActivity(settings);
                    }
                    break;
                default:
                    break;
            }
        } catch (RuntimeException ignored) { }
    }
}
