package com.kards.mobilert;

import android.app.Activity;
import android.app.ActivityOptions;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Display;
import android.view.WindowManager;

/** A short-lived layout request on the projection's OWN display, before mirroring. */
public final class CaptureLayoutActivity extends Activity {
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static long nextToken;
    private static Pending pending;
    private long token;

    private static final class Pending {
        final long token;
        final int displayId;
        final Runnable done;
        Activity activity;
        Pending(long token, int displayId, Runnable done) {
            this.token = token; this.displayId = displayId; this.done = done;
        }
    }

    static boolean admits(int target, int actual, long expected, long supplied) {
        return target > Display.DEFAULT_DISPLAY && actual == target
                && expected > 0 && supplied == expected;
    }

    static long request(Context context, Display display, Runnable done) {
        if (Looper.myLooper() != Looper.getMainLooper()) throw new IllegalStateException("main_required");
        if (pending != null || display == null || display.getDisplayId() <= Display.DEFAULT_DISPLAY) {
            done.run(); return 0;
        }
        long id = ++nextToken;
        pending = new Pending(id, display.getDisplayId(), done);
        Intent intent = new Intent(context, CaptureLayoutActivity.class)
                .putExtra("layout_token", id)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_MULTIPLE_TASK
                        | Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS | Intent.FLAG_ACTIVITY_NO_ANIMATION);
        ActivityOptions options = ActivityOptions.makeBasic();
        options.setLaunchDisplayId(display.getDisplayId());
        // The deadline also handles launch denial, missing lifecycle callbacks and cancellation.
        MAIN.postDelayed(() -> complete(id), 900L);
        try { context.startActivity(intent, options.toBundle()); }
        catch (RuntimeException error) {
            android.util.Log.w("KardsCompatCapture", "geometry_layout_launch_rejected", error);
            complete(id);
        }
        return id;
    }

    static void cancel(long id) { MAIN.post(() -> complete(id)); }

    private static void complete(long id) {
        Pending current = pending;
        if (current == null || current.token != id) return;
        pending = null;
        if (current.activity != null) current.activity.finishAndRemoveTask();
        // Let WM remove the activity before reattaching the mirror surface.
        MAIN.postDelayed(current.done, 120L);
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        token = getIntent().getLongExtra("layout_token", 0);
        Pending current = pending;
        Display actual = getDisplay();
        if (current == null || actual == null
                || !admits(current.displayId, actual.getDisplayId(), current.token, token)) {
            finishAndRemoveTask(); return;
        }
        current.activity = this;
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
                | WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE);
        // Never request orientation until the OS confirms the secondary display identity.
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE);
        MAIN.postDelayed(() -> complete(token), 250L);
    }

    @Override public void onDestroy() {
        super.onDestroy();
        complete(token);
    }
}
