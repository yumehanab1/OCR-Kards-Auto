package com.kards.mobilert;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.InputStream;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.text.SimpleDateFormat;
import java.util.Arrays;
import java.util.Comparator;
import java.util.Date;
import java.util.Locale;
import java.util.function.Consumer;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** User control panel. Observing the panel never starts or resumes game input. */
public final class MainActivity extends Activity {
    private static final int REQUEST_REPLAY_PNG = 4101;
    private static final int REQUEST_COMPAT_CAPTURE = 4102;
    private static final String LAST_RESULT = "last_result";
    private static final String PANEL_PREFERENCES = "battle_panel";
    private static final String SELECTED_MODE = "selected_mode";
    private static final String SELECTED_MATCH_COUNT = "selected_match_count";
    private TextView status;
    private TrainingDashboard dashboard;
    private boolean gameInstalled;
    private String savedReport = "{}";
    private String shownReport = "";
    private boolean shownConnected, shownBusy, shownInstalled;
    private TrainingPanelState panelState = TrainingPanelState.from("{}");
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService historyReader = Executors.newSingleThreadExecutor();
    private int historyGeneration;
    private boolean visible;
    private long messageUntil;
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            if (!visible) return;
            refreshDashboard();
            main.postDelayed(this, 1000);
        }
    };
    private final MobileCore mobileCore = new ReadOnlyMobileCore();
    private ReadOnlyObservationLoop observationLoop;
    private Button monitorButton;
    private Button compatCaptureButton;
    private final Consumer<Boolean> connectionListener = connected -> refreshDashboard();

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setDecorFitsSystemWindows(false);
        getWindow().setStatusBarColor(Color.TRANSPARENT);
        getWindow().setNavigationBarColor(Color.TRANSPARENT);
        String version = "0.6.1";
        try { version = getPackageManager().getPackageInfo(getPackageName(), 0).versionName; }
        catch (Exception ignored) { }
        dashboard = new TrainingDashboard(this, new TrainingDashboard.Actions() {
            @Override public void start(String mode, boolean openGame, int matchCount) { launchBattle(false, mode, openGame, matchCount); }
            @Override public void modeChanged(String mode) {
                getSharedPreferences(PANEL_PREFERENCES, MODE_PRIVATE).edit().putString(SELECTED_MODE, mode).apply();
            }
            @Override public void matchCountChanged(int count) {
                getSharedPreferences(PANEL_PREFERENCES, MODE_PRIVATE).edit().putInt(SELECTED_MATCH_COUNT, count).apply();
            }
            @Override public void stop() {
                KardsAccessibilityService service = KardsAccessibilityService.instance();
                if (service != null) service.cancelBattle();
                if (observationLoop != null) observationLoop.stop();
                refreshDashboard();
            }
            @Override public void permissions() { openPermissions(); }
            @Override public void details() { showTrainingDetails(); }
        }, version);
        dashboard.setSelectedMode(getSharedPreferences(PANEL_PREFERENCES, MODE_PRIVATE)
                .getString(SELECTED_MODE, "casual"));
        dashboard.restoreMatchCountText(state != null && state.containsKey("match_count_input")
                ? state.getString("match_count_input", "")
                : Integer.toString(getSharedPreferences(PANEL_PREFERENCES, MODE_PRIVATE).getInt(SELECTED_MATCH_COUNT, 1)));
        LinearLayout root = dashboard.diagnostics;
        status = new TextView(this);
        status.setId(android.R.id.message);
        status.setText(state == null ? "选择下方工具查看诊断。打开此区域不会开始对局操作。"
                : state.getString(LAST_RESULT, "选择下方工具查看诊断。"));
        status.setTextSize(13);
        status.setTextColor(Color.rgb(76, 89, 76));
        status.setTextIsSelectable(true);
        status.setPadding(0, 8, 0, 20);
        root.addView(status, new LinearLayout.LayoutParams(-1, -2));

        TextView trainingHint = new TextView(this);
        trainingHint.setText("训练模式仅用于调试。先在 KARDS 中进入训练起手或对局，再返回这里启动。不会自动匹配休闲或排位。");
        trainingHint.setTextSize(13);
        trainingHint.setTextColor(Color.rgb(76, 89, 76));
        root.addView(trainingHint, new LinearLayout.LayoutParams(-1, -2));
        Button training = new Button(this);
        training.setId(R.id.panel_training_debug_start);
        training.setText("训练模式调试 · 开始辅助");
        training.setOnClickListener(v -> launchBattle(false, "training", true));
        root.addView(training, new LinearLayout.LayoutParams(-1, -2));

        Button inspect = new Button(this);
        inspect.setText("只观察当前对局");
        inspect.setOnClickListener(v -> launchBattle(true, "training", true));
        root.addView(inspect, new LinearLayout.LayoutParams(-1, -2));

        Button rawReport = new Button(this);
        rawReport.setText("查看完整运行记录");
        rawReport.setOnClickListener(v -> status.setText(currentReport()));
        root.addView(rawReport, new LinearLayout.LayoutParams(-1, -2));

        compatCaptureButton = new Button(this);
        compatCaptureButton.setText("启用兼容截图（系统截图黑屏时使用）");
        compatCaptureButton.setOnClickListener(v -> {
            if(BattleWorkerLease.isOwned()) {status.setText("请先停止辅助，再切换截图通道。");return;}
            if(CompatCaptureService.isReady()) {
                startService(new Intent(this,CompatCaptureService.class).setAction(CompatCaptureService.ACTION_STOP));
                status.setText("兼容截图已关闭。");
            } else requestCompatCapture();
        });
        root.addView(compatCaptureButton,new LinearLayout.LayoutParams(-1,-2));

        Button screenshot = new Button(this);
        screenshot.setText("测试截图能力");
        screenshot.setOnClickListener(v -> {
            KardsAccessibilityService service = KardsAccessibilityService.instance();
            if (service == null) {
                status.setText("状态：服务未启用，请先打开无障碍设置。\n本次没有游戏输入。");
                return;
            }
            service.requestScreenshot(result -> status.setText(result));
        });
        root.addView(screenshot, new LinearLayout.LayoutParams(-1, -2));

        Button coreFrame = new Button(this);
        coreFrame.setText("读取核心帧（只读）");
        coreFrame.setOnClickListener(v -> {
            KardsAccessibilityService service = KardsAccessibilityService.instance();
            if (service == null) {
                status.setText("状态：服务未启用，请先打开无障碍设置。\n核心帧：未读取；动作授权：否");
                return;
            }
            status.setText("状态：正在读取核心帧…");
            service.requestFrame(new FrameSource.Callback() {
                @Override
                public void onFrame(FrameSnapshot snapshot) {
                    try {
                        BoardObservation observation = mobileCore.observe(snapshot);
                        status.setText(String.format(Locale.ROOT,
                                "核心帧：%d×%d → %d×%d\n状态：%s\n游戏画面：%s\n结束回合槽：%s\n前线归属：%s\n候选数：%d\n动作授权：%s\n说明：%s",
                                snapshot.sourceWidth(), snapshot.sourceHeight(), snapshot.width(),
                                snapshot.height(), observation.displayState(),
                                observation.isGameScreen() ? "是" : "否",
                                observation.isEndTurnVisible() ? "存在（仅候选）" : "未确认",
                                observation.frontlineOwner().name(), observation.candidates().size(),
                                observation.isActionAuthorized() ? "是" : "否", observation.reason()));
                    } finally {
                        snapshot.close();
                    }
                }

                @Override
                public void onFailure(String message) {
                    status.setText(String.format(Locale.ROOT, "%s\n核心帧：不可用；动作授权：否", message));
                }
            });
        });
        root.addView(coreFrame, new LinearLayout.LayoutParams(-1, -2));

        Button selfCheck = new Button(this);
        selfCheck.setText("运行板面识别离线自检");
        selfCheck.setOnClickListener(v -> status.setText(BoardRecognizerSelfCheck.run()));
        root.addView(selfCheck, new LinearLayout.LayoutParams(-1, -2));

        Button replay = new Button(this);
        replay.setText(R.string.replay_png);
        replay.setOnClickListener(v -> {
            Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("image/png");
            startActivityForResult(intent, REQUEST_REPLAY_PNG);
        });
        root.addView(replay, new LinearLayout.LayoutParams(-1, -2));

        monitorButton = new Button(this);
        monitorButton.setText("开始只读观察回路");
        monitorButton.setOnClickListener(v -> {
            if (observationLoop != null && observationLoop.isRunning()) {
                observationLoop.stop();
                monitorButton.setText("开始只读观察回路");
                status.setText("只读观察已停止；动作授权：否");
                return;
            }
            KardsAccessibilityService service = KardsAccessibilityService.instance();
            if (service == null) {
                status.setText("状态：服务未启用，请先打开无障碍设置。\n观察回路未启动；动作授权：否");
                return;
            }
            observationLoop = new ReadOnlyObservationLoop(service, mobileCore,
                    json -> {
                        String stateText = json.contains("\"state\":\"MY_TURN\"")
                                ? "MY_TURN" : json.contains("\"state\":\"IN_GAME\"")
                                ? "IN_GAME" : json.contains("\"state\":\"NON_GAME\"")
                                ? "NON_GAME" : "UNKNOWN";
                        status.setText(getString(R.string.observation_running, stateText));
                    }, message -> status.setText(getString(R.string.readonly_failure, message)));
            observationLoop.start();
            monitorButton.setText("停止只读观察回路");
        });
        root.addView(monitorButton, new LinearLayout.LayoutParams(-1, -2));

        Button confirmOpening = new Button(this);
        confirmOpening.setText("起手确认测试（最多点击一次）");
        confirmOpening.setOnClickListener(v -> {
            KardsAccessibilityService service = KardsAccessibilityService.instance();
            Intent game = getPackageManager().getLaunchIntentForPackage("com.android1939.kards");
            if (service == null || game == null) {
                status.setText(R.string.mulligan_unavailable);
                return;
            }
            if (observationLoop != null) observationLoop.stop();
            if (!service.startMulliganOnce()) {
                status.setText(getString(R.string.mulligan_start_failed, service.lastSessionReport()));
                return;
            }
            status.setText("已启动单次起手确认测试；仅在确认起手画面时点击。\n最多一次输入，返回本应用可停止。");
            try {
                startActivity(game);
            } catch (RuntimeException error) {
                service.cancelMulligan();
                status.setText(R.string.mulligan_launch_failed);
            }
        });
        root.addView(confirmOpening, new LinearLayout.LayoutParams(-1, -2));

        Button cancelOpening = new Button(this);
        cancelOpening.setText("停止单次测试并查看结果");
        cancelOpening.setOnClickListener(v -> {
            KardsAccessibilityService service = KardsAccessibilityService.instance();
            if (service == null) { status.setText("无障碍服务未连接，单次测试不可用。"); return; }
            service.cancelMulligan();
            String report = service.lastSessionReport();
            status.setText(report == null ? "没有正在进行的单次测试。" : report);
        });
        root.addView(cancelOpening, new LinearLayout.LayoutParams(-1, -2));

        Button gesture = new Button(this);
        gesture.setText("测试手势能力（仅原型）");
        gesture.setOnClickListener(v -> {
            KardsAccessibilityService service = KardsAccessibilityService.instance();
            if (service == null) {
                status.setText("状态：服务未启用，请先打开无障碍设置。\n本次没有游戏输入。");
                return;
            }
            service.probeGesture(result -> status.setText(result));
        });
        root.addView(gesture, new LinearLayout.LayoutParams(-1, -2));

        for (int i = 0; i < root.getChildCount(); i++) {
            if (root.getChildAt(i) instanceof Button) dashboard.styleDiagnosticsButton((Button) root.getChildAt(i));
        }
        if (state != null) dashboard.setDiagnosticsOpen(state.getBoolean("diagnostics_open", false));
        setContentView(dashboard.view());
        if((getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE)!=0
                && getIntent().getBooleanExtra("show_compat_capture",false))
            main.post(this::requestCompatCapture);
    }

    private void requestCompatCapture() {
        if(BattleWorkerLease.isOwned()) {status.setText("请先停止辅助，再启用兼容截图。");return;}
        if(android.os.Build.VERSION.SDK_INT>=34) {status.setText("当前系统使用游戏窗口截图，无需此旧系统兼容通道。");return;}
        try {
            android.media.projection.MediaProjectionManager manager=getSystemService(android.media.projection.MediaProjectionManager.class);
            status.setText("请在安卓系统弹窗中确认屏幕录制授权。启用截图不会开始对局或触控。");
            startActivityForResult(manager.createScreenCaptureIntent(),REQUEST_COMPAT_CAPTURE);
        } catch(RuntimeException error){status.setText("无法打开兼容截图授权，请稍后重试。");}
    }

    private void openPermissions() {
        try { startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)); }
        catch (RuntimeException error) { panelMessage("无法打开系统设置", "请在系统设置中找到无障碍，开启 KARDS 对战助手。"); }
    }

    private void panelMessage(String title, String message) {
        messageUntil = android.os.SystemClock.elapsedRealtime() + 6000;
        dashboard.message(title, message);
        shownReport = "";
    }

    private String currentReport() {
        KardsAccessibilityService service = KardsAccessibilityService.instance();
        String memory = service == null ? "{}" : service.battleProgressReport();
        try { if (new JSONObject(memory).has("session_id")) return memory; }
        catch (Exception ignored) { }
        return savedReport;
    }

    private void refreshDashboard() {
        if (dashboard == null) return;
        KardsAccessibilityService service = KardsAccessibilityService.instance();
        String memory = service == null ? "{}" : service.battleProgressReport();
        boolean useMemory = false;
        try { useMemory = new JSONObject(memory).has("session_id"); }
        catch (Exception ignored) { }
        String report = useMemory ? memory : savedReport;
        boolean busy = BattleWorkerLease.isOwned();
        if(compatCaptureButton!=null){
            compatCaptureButton.setEnabled(!busy);
            compatCaptureButton.setText(CompatCaptureService.isReady()?"兼容截图已启用 · 点击关闭"
                    :"启用兼容截图（系统截图黑屏时使用）");
        }
        boolean connected = service != null;
        if (android.os.SystemClock.elapsedRealtime() < messageUntil && !busy) return;
        if (report.equals(shownReport) && connected == shownConnected && busy == shownBusy
                && gameInstalled == shownInstalled) return;
        shownReport = report;
        shownConnected = connected;
        shownBusy = busy;
        shownInstalled = gameInstalled;
        panelState = useMemory ? TrainingPanelState.from(report) : TrainingPanelState.fromSaved(report);
        dashboard.render(panelState, connected, gameInstalled, busy, sessionDate(report));
    }

    private String sessionDate(String report) {
        try {
            String id = new JSONObject(report).optString("session_id");
            long timestamp = Long.parseLong(id.split("-")[0]);
            return new SimpleDateFormat("M月d日 HH:mm", Locale.CHINA).format(new Date(timestamp));
        } catch (Exception ignored) { return ""; }
    }

    private void loadLatestRecord() {
        final int generation = ++historyGeneration;
        File directory = new File(getFilesDir(), "battle");
        historyReader.execute(() -> {
            final String result = TrainingHistoryReader.readLatest(directory);
            main.post(() -> {
                if (isDestroyed() || generation != historyGeneration) return;
                savedReport = result;
                refreshDashboard();
            });
        });
    }

    private void showTrainingDetails() {
        if (!panelState.hasSession) return;
        String body = "对局模式：" + panelState.modeLabel + "\n\n" + panelState.summary + "\n\n运行时长：" + panelState.durationDisplay
                + "\n进行回合：" + panelState.turnCount + "\n已确认行动：" + panelState.actionCount
                + "\n\n已确认行动包含出牌、移动和攻击。";
        if (!panelState.stopReason.isEmpty()) body += "\n" + panelState.stopReason;
        new AlertDialog.Builder(this).setTitle(panelState.title).setMessage(body)
                .setPositiveButton("知道了", null).show();
    }

    private void launchBattle(boolean readOnly, String mode, boolean openGame) {
        launchBattle(readOnly, mode, openGame, 1);
    }

    private void launchBattle(boolean readOnly, String mode, boolean openGame, int matchCount) {
        if (matchCount < 0) {
            panelMessage("请检查局数", getString(R.string.match_count_invalid));
            return;
        }
        if (!("training".equals(mode) || "casual".equals(mode) || "ranked".equals(mode))) {
            panelMessage("请选择对局模式", "选择休闲或排位后再开始。");
            return;
        }
        KardsAccessibilityService service = KardsAccessibilityService.instance();
        Intent game = getPackageManager().getLaunchIntentForPackage("com.android1939.kards");
        if (service == null || game == null) {
            panelMessage("还差一步准备", "请先安装 KARDS，并开启对战助手的无障碍权限。");
            return;
        }
        if (observationLoop != null) observationLoop.stop();
        boolean launchGame = openGame || readOnly || "training".equals(mode);
        boolean armedThisRequest = false;
        try {
            JSONObject options = battleOptions(readOnly, mode, matchCount);
            if (!service.startBattle(options.toString())) {
                panelMessage("暂时无法开始", BattleStartAttempt.userMessage(service.lastStartAttempt()));
                return;
            }
            armedThisRequest = true;
            // Render the service's actual armed report while the user still sees this panel.
            // Both entry buttons require a fresh game foreground; opening an app does not admit it.
            messageUntil = 0;
            shownReport = "";
            refreshDashboard();
            if (launchGame) startActivity(game);
        } catch (Exception error) {
            if (armedThisRequest) service.cancelBattle();
            panelMessage(launchGame ? "暂时无法打开游戏" : "暂时无法开始辅助",
                    launchGame ? "辅助已停止。请确认 KARDS 可以正常启动，再试一次。"
                            : "辅助已停止。请检查辅助服务后重试。");
        }
    }

    /** Build the same validated options for both launch buttons without starting anything. */
    static JSONObject battleOptions(boolean readOnly, String mode, int matchCount) throws Exception {
        if (matchCount < 0) throw new IllegalArgumentException("invalid_match_count");
        boolean multiple = matchCount != 1;
        return new JSONObject().put("read_only", readOnly).put("match_mode", mode)
                .put("native_menu", !readOnly && !MatchEntryOptions.TRAINING.equals(mode))
                .put("retain_full_evidence", false)
                .put("match_count", matchCount).put("entry_mode", GameEntryGate.LAUNCH_GAME)
                .put("start_with_opening", !readOnly).put("post_match_settle", true)
                .put("max_seconds", readOnly ? 60 : multiple ? 1800 : 1200)
                .put("max_inputs", readOnly ? 0 : multiple ? 200 : 120).put("unknown_seconds", 30)
                .put("idle_seconds", 120).put("max_failed_inputs", 5);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if(requestCode==REQUEST_COMPAT_CAPTURE) {
            if(resultCode==RESULT_OK && data!=null) {
                try {
                    startForegroundService(new Intent(this,CompatCaptureService.class)
                            .putExtra("result_code",resultCode).putExtra("result_data",data));
                    status.setText("兼容截图正在连接；连接后返回游戏，再开始辅助。");
                } catch(RuntimeException error){status.setText("兼容截图启动失败，请重新启用。");}
            } else status.setText("未启用兼容截图；本次没有开始辅助或游戏输入。");
            return;
        }
        if (requestCode != REQUEST_REPLAY_PNG || resultCode != RESULT_OK || data == null
                || data.getData() == null) {
            return;
        }
        Uri uri = data.getData();
        status.setText(R.string.replay_loading);
        try {
            // Read dimensions before allocating a bitmap from an untrusted document.
            BitmapFactory.Options bounds = new BitmapFactory.Options();
            bounds.inJustDecodeBounds = true;
            try (InputStream stream = getContentResolver().openInputStream(uri)) {
                if (stream == null) throw new IllegalStateException("无法打开所选 PNG");
                BitmapFactory.decodeStream(stream, null, bounds);
            }
            if (!"image/png".equals(bounds.outMimeType)) {
                throw new IllegalArgumentException("所选文件不是有效 PNG");
            }
            if (!((bounds.outWidth == 1280 && bounds.outHeight == 720)
                    || (bounds.outWidth == 1920 && bounds.outHeight == 1080))) {
                throw new IllegalArgumentException("只接受 1280×720 或 1920×1080 PNG");
            }
            BitmapFactory.Options options = new BitmapFactory.Options();
            options.inScaled = false;
            options.inPreferredConfig = Bitmap.Config.ARGB_8888;
            Bitmap bitmap;
            try (InputStream stream = getContentResolver().openInputStream(uri)) {
                if (stream == null) throw new IllegalStateException("无法打开所选 PNG");
                bitmap = BitmapFactory.decodeStream(stream, null, options);
            }
            if (bitmap == null) throw new IllegalStateException("PNG 解码失败");
            String json = FrameReplay.analyze(bitmap, uri.toString(), mobileCore);
            java.io.File result = FrameReplay.writeResult(this, json);
            JSONObject observation = new JSONObject(json);
            status.setText(getString(R.string.replay_result, observation.getString("state"),
                    bounds.outWidth, bounds.outHeight,
                    observation.getJSONObject("diagnostics").getInt("candidate_count"),
                    result.getAbsolutePath()));
        } catch (Exception error) {
            status.setText(getString(R.string.replay_failure,
                    error.getClass().getSimpleName(), String.valueOf(error.getMessage())));
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        visible = true;
        gameInstalled = getPackageManager().getLaunchIntentForPackage("com.android1939.kards") != null;
        main.removeCallbacks(refresh);
        main.post(refresh);
        loadLatestRecord();
    }

    @Override
    protected void onStart() {
        super.onStart();
        KardsAccessibilityService.addConnectionListener(connectionListener);
    }

    @Override
    protected void onStop() {
        KardsAccessibilityService.removeConnectionListener(connectionListener);
        super.onStop();
    }

    @Override
    protected void onPause() {
        visible = false;
        main.removeCallbacks(refresh);
        if (observationLoop != null && observationLoop.isRunning()) {
            observationLoop.stop();
            status.setText("只读观察已暂停（应用离开前台）；动作授权：否");
        }
        if (monitorButton != null) monitorButton.setText("开始只读观察回路");
        super.onPause();
    }

    @Override
    protected void onSaveInstanceState(Bundle state) {
        super.onSaveInstanceState(state);
        state.putString(LAST_RESULT, status.getText().toString());
        state.putBoolean("diagnostics_open", dashboard.diagnosticsOpen());
        state.putString("match_count_input", dashboard.matchCountText());
    }

    @Override
    protected void onDestroy() {
        historyGeneration++;
        historyReader.shutdownNow();
        main.removeCallbacks(refresh);
        super.onDestroy();
    }
}
