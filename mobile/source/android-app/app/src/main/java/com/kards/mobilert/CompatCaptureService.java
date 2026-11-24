package com.kards.mobilert;

import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

/** Foreground lifetime for user-authorized, optional MediaProjection capture. */
public final class CompatCaptureService extends Service {
    public static final String ACTION_STOP = "com.kards.mobilert.STOP_COMPAT_CAPTURE";
    private static final String CHANNEL = "kards_compat_capture";
    private static final int NOTIFICATION_ID = 16448;
    private static volatile CompatCaptureSource activeSource;
    private static volatile String lastStatus = "兼容截图未开启（compat_capture_off）";
    private CompatCaptureSource ownedSource;
    private CompatCaptureSource retiringSource;
    private Runnable pendingReplacement;

    /** A consent-owned source may be initializing; do not silently bypass it. */
    public static boolean hasSource() { return activeSource != null; }

    public static boolean isReady() {
        CompatCaptureSource source = activeSource;
        return source != null && source.isReady();
    }

    public static String status() {
        CompatCaptureSource source = activeSource;
        return source == null ? lastStatus : source.status();
    }

    /** Returns source-display pixels; all callbacks run on the main thread. */
    public static void requestFrame(FrameSource.Callback callback, long requestedAtMillis) {
        if (callback == null) return;
        CompatCaptureSource source = activeSource;
        if (source == null) {
            new Handler(Looper.getMainLooper()).post(() -> callback.onFailure(lastStatus));
            return;
        }
        source.requestFrame(callback, requestedAtMillis);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            lastStatus = "兼容截图已关闭（compat_capture_stopped）";
            shutdown(lastStatus);
            stopSelf();
            return START_NOT_STICKY;
        }
        try {
            startForeground(NOTIFICATION_ID, notification(),
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
            int resultCode = intent == null ? Activity.RESULT_CANCELED
                    : intent.getIntExtra("result_code", Activity.RESULT_CANCELED);
            Intent resultData = intent == null ? null : intent.getParcelableExtra("result_data");
            if (resultCode != Activity.RESULT_OK || resultData == null) {
                if (ownedSource != null || retiringSource != null) return START_NOT_STICKY;
                lastStatus = "兼容截图未获得屏幕共享授权（compat_capture_consent_missing）";
                stopSelf();
                return START_NOT_STICKY;
            }
            pendingReplacement = () -> initializeSource(resultCode, resultData);
            if (ownedSource != null) {
                retiringSource = ownedSource;
                ownedSource = null;
                retiringSource.close("兼容截图重新授权中（compat_capture_replacing）");
            } else if (retiringSource == null) {
                Runnable replacement = pendingReplacement;
                pendingReplacement = null;
                replacement.run();
            }
        } catch (RuntimeException error) {
            startupFailed(error);
        }
        // A process restart must never recreate a projection without fresh user consent.
        return START_NOT_STICKY;
    }

    private void initializeSource(int resultCode, Intent resultData) {
        try {
            MediaProjectionManager manager = getSystemService(MediaProjectionManager.class);
            if (manager == null) throw new IllegalStateException("projection_manager_missing");
            MediaProjection projection = manager.getMediaProjection(resultCode, resultData);
            if (projection == null) throw new IllegalStateException("projection_missing");
            ownedSource = new CompatCaptureSource(this, projection, this::sourceStopped);
            activeSource = ownedSource;
            lastStatus = ownedSource.status();
        } catch (RuntimeException error) {
            startupFailed(error);
        }
    }

    void sourceStopped(CompatCaptureSource stopped, String reason) {
        if (retiringSource == stopped) {
            if (activeSource == stopped) activeSource = null;
            retiringSource = null;
            Runnable replacement = pendingReplacement;
            pendingReplacement = null;
            if (replacement != null) replacement.run();
            return;
        }
        if (ownedSource != stopped) return;
        lastStatus = reason;
        if (activeSource == stopped) activeSource = null;
        ownedSource = null;
        stopSelf();
    }

    private void startupFailed(RuntimeException error) {
        lastStatus = "兼容截图启动失败（compat_capture_service_"
                + error.getClass().getSimpleName() + "）";
        shutdown(lastStatus);
        stopSelf();
    }

    @Override public void onDestroy() {
        if (ownedSource != null)
            lastStatus = "兼容截图服务已关闭（compat_capture_closed）";
        shutdown(lastStatus);
        stopForeground(STOP_FOREGROUND_REMOVE);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) {
        return null;
    }

    private void shutdown(String reason) {
        pendingReplacement = null;
        if (activeSource == retiringSource) activeSource = null;
        retiringSource = null; // Its already-queued close may finish after stop or destruction.
        CompatCaptureSource source = ownedSource;
        ownedSource = null;
        if (activeSource == source) activeSource = null;
        if (source != null) source.close(reason);
    }

    private Notification notification() {
        NotificationManager notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(CHANNEL, "兼容屏幕截图",
                NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(this, 0,
                new Intent(this, MainActivity.class), PendingIntent.FLAG_UPDATE_CURRENT
                        | PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop = PendingIntent.getService(this, 0,
                new Intent(this, CompatCaptureService.class).setAction(ACTION_STOP),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL)
                .setSmallIcon(android.R.drawable.ic_menu_camera)
                .setContentTitle("KARDS 兼容截图已开启")
                .setContentText("仅在助手请求时读取屏幕；可随时停止")
                .setContentIntent(open)
                .setOngoing(true)
                .addAction(new Notification.Action.Builder(null, "停止兼容截图", stop).build())
                .build();
    }
}
