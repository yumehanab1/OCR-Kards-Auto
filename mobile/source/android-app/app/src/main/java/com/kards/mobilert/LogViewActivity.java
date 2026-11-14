package com.kards.mobilert;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

public final class LogViewActivity extends Activity {
    private TextView body, meta;
    private ScrollView scroll;
    private Button follow;
    private boolean autoScroll = true;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            render();
            handler.postDelayed(this, 1000);
        }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        DebugLog.init(this);
        DebugLog.log("LOG", "调试日志面板已打开");
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(18, 24, 21));
        root.setPadding(12, 12, 12, 12);

        meta = new TextView(this);
        meta.setTextColor(Color.rgb(150, 200, 160));
        meta.setTextSize(11);
        root.addView(meta);

        LinearLayout buttons = new LinearLayout(this);
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        buttons.addView(action("复制全部", v -> copy()));
        buttons.addView(action("文件路径", v -> showPath()));
        follow = action("跟随：开", v -> {
            autoScroll = !autoScroll;
            follow.setText(autoScroll ? "跟随：开" : "跟随：关");
        });
        buttons.addView(follow);
        buttons.addView(action("清空", v -> { DebugLog.clear(); render(); }));
        root.addView(buttons);

        scroll = new ScrollView(this);
        body = new TextView(this);
        body.setTypeface(Typeface.MONOSPACE);
        body.setTextSize(10);
        body.setTextColor(Color.rgb(210, 225, 210));
        body.setTextIsSelectable(true);
        scroll.addView(body);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);
        render();
    }

    private Button action(String label, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextSize(11);
        button.setAllCaps(false);
        button.setMinHeight(0);
        button.setMinimumHeight(0);
        button.setOnClickListener(listener);
        button.setLayoutParams(new LinearLayout.LayoutParams(0, -2, 1));
        return button;
    }

    private void render() {
        String text = DebugLog.fileText();
        body.setText(text);
        meta.setText("行数 " + DebugLog.count() + " · " + DebugLog.path());
        if (autoScroll) scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
    }

    private void copy() {
        ClipboardManager manager = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        if (manager != null) {
            manager.setPrimaryClip(ClipData.newPlainText("kards-log", DebugLog.fileText()));
            Toast.makeText(this, "日志已复制到剪贴板", Toast.LENGTH_SHORT).show();
        }
    }

    private void showPath() {
        Toast.makeText(this, DebugLog.path(), Toast.LENGTH_LONG).show();
    }

    @Override protected void onResume() {
        super.onResume();
        handler.post(refresh);
    }

    @Override protected void onPause() {
        super.onPause();
        handler.removeCallbacks(refresh);
    }
}
