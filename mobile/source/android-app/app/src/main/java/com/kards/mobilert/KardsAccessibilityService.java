package com.kards.mobilert;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.graphics.Bitmap;
import android.hardware.HardwareBuffer;
import android.os.Handler;
import android.os.Looper;
import android.view.Display;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.Set;

import java.util.concurrent.Executor;
import java.util.function.Consumer;

/**
 * Android screenshot adapter and explicitly armed one-shot mulligan action.
 * General board actions remain read-only.
 */
public final class KardsAccessibilityService extends AccessibilityService implements FrameSource {
    private static KardsAccessibilityService current;
    private static final Set<Consumer<Boolean>> connectionListeners = new HashSet<>();
    private static final String GAME_PACKAGE = "com.android1939.kards";
    private String foregroundPackage = "";
    private long foregroundGeneration;
    private int sourceWidth;
    private int sourceHeight;
    private BoundedMulliganSession mulliganSession;
    private ApkBattleSession battleSession;
    private volatile String lastStartAttempt = "{}";
    private String startPriorSessionId = "";
    private boolean startPriorActive;
    private String lastSessionReport;
    private final Handler screenshotHandler = new Handler(Looper.getMainLooper());
    private final Executor mainExecutor = command -> screenshotHandler.post(command);
    private final ScreenshotRequestPacer screenshotPacer = new ScreenshotRequestPacer();
    private boolean screenshotRequestsClosed;
    private GameFloatingControl floatingControl;

    public static KardsAccessibilityService instance() {
        return current;
    }

    /** Called on the main thread; listeners belong only to visible Activities. */
    public static void addConnectionListener(Consumer<Boolean> listener) {
        connectionListeners.add(listener);
        listener.accept(current != null);
    }

    public static void removeConnectionListener(Consumer<Boolean> listener) {
        connectionListeners.remove(listener);
    }

    private static void publishConnection(boolean connected) {
        for (Consumer<Boolean> listener : new ArrayList<>(connectionListeners)) listener.accept(connected);
    }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        current = this;
        floatingControl = new GameFloatingControl(this);
        publishConnection(true);
    }

    @Override
    public void onDestroy() {
        screenshotRequestsClosed = true;
        if (floatingControl != null) floatingControl.destroy();
        cancelBattle();
        cancelMulligan();
        if (current == this) {
            current = null;
            publishConnection(false);
        }
        super.onDestroy();
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        String packageName = event == null || event.getPackageName() == null
                ? "" : event.getPackageName().toString();
        // Ignore only this attached overlay window, not the application's Activity
        // or arbitrary windows with the same package name.
        if (floatingControl != null && event != null && getPackageName().equals(packageName)
                && floatingControl.ownsWindow(event.getWindowId())) return;
        updateForeground(packageName);
    }

    @Override
    public void onInterrupt() {
        cancelBattle();
        cancelMulligan();
    }

    private void updateForeground(String packageName) {
        if (!foregroundPackage.equals(packageName)) {
            foregroundPackage = packageName;
            foregroundGeneration++;
        }
    }

    /** Inspect only the active window's package; never traverse or log window content. */
    @SuppressWarnings("deprecation")
    private String activePackage() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            updateForeground("");
            return "";
        }
        try {
            String name = root.getPackageName() == null ? "" : root.getPackageName().toString();
            updateForeground(name);
            return name;
        } finally {
            root.recycle();
        }
    }

    public boolean startMulliganOnce() {
        cancelBattle();
        if (BattleWorkerLease.isOwned()) return false;
        return startMulliganOnce(null);
    }

    private boolean startMulliganOnce(Consumer<String> observer) {
        return startMulliganOnce(observer, null);
    }

    private boolean startMulliganOnce(Consumer<String> observer, GameEntryGate entryGate) {
        return startMulliganOnce(observer, entryGate, null);
    }

    private boolean startMulliganOnce(Consumer<String> observer, GameEntryGate entryGate,
                                      ApkBattleSession owner) {
        cancelMulligan();
        // Refresh foreground facts; a supplied campaign keeps its original admission token.
        activePackage();
        boolean nativePixels = owner != null && owner.usesNativeFrames();
        FrameSource source = nativePixels ? this::requestNativeFrame : this;
        mulliganSession = new BoundedMulliganSession(this, source, new BoundedMulliganSession.Platform() {
            @Override public void prepareInput(java.util.function.Consumer<Runnable> ready) { withoutOverlay(ready); }
            @Override public String currentForegroundPackage() { return activePackage(); }
            @Override public long foregroundGeneration() { return foregroundGeneration; }
            @Override public boolean dispatchTap(float x, float y, BoundedMulliganSession.TapCallback callback) {
                if (owner != null && (battleSession != owner || !owner.canContinueOpening()
                        || !BattleWorkerLease.isOwnedBy(owner))) return false;
                long before = foregroundGeneration;
                if (!GAME_PACKAGE.equals(activePackage()) || before != foregroundGeneration
                        || mulliganSession == null || !mulliganSession.isRunning()
                        || !FrameAspectProfile.supported(sourceWidth, sourceHeight)
                        || !Float.isFinite(x) || !Float.isFinite(y)
                        || x <= 0 || x >= 1 || y <= 0 || y >= 1) return false;
                Path tap = new Path();
                tap.moveTo(x * sourceWidth, y * sourceHeight);
                GestureDescription gesture = new GestureDescription.Builder()
                        .addStroke(new GestureDescription.StrokeDescription(tap, 0, 60)).build();
                // The active-window IPC above can take time; check freshness at the actual input boundary.
                if (!mulliganSession.canDispatchPreparedTapNow()
                        || (owner != null && !owner.canContinueOpening())) return false;
                return dispatchGesture(gesture, new GestureResultCallback() {
                    @Override public void onCompleted(GestureDescription description) { callback.onCompleted(); }
                    @Override public void onCancelled(GestureDescription description) { callback.onCancelled(); }
                }, new Handler(Looper.getMainLooper()));
            }
        }, json -> {
            lastSessionReport = json;
            if (observer != null) observer.accept(json);
        }, entryGate, nativePixels, owner==null?getFilesDir():owner.openingEvidenceRoot());
        return mulliganSession.start();
    }

    String currentForegroundPackage() { return activePackage(); }
    long gameForegroundGeneration() { return foregroundGeneration; }

    /** A menu worker hands its existing campaign and foreground token to the bounded opening. */
    boolean startCampaignOpening(ApkBattleSession campaign, GameEntryGate gate, Consumer<String> observer) {
        if (Looper.myLooper() != Looper.getMainLooper() || current != this || battleSession != campaign
                || !campaign.canContinueOpening() || !BattleWorkerLease.isOwnedBy(campaign)) return false;
        return startMulliganOnce(observer, gate, campaign);
    }

    void cancelCampaignOpening(ApkBattleSession campaign) {
        if (battleSession == campaign) cancelMulligan();
    }

    public synchronized boolean startBattle(String options) {
        return startBattle(options, false);
    }

    private synchronized boolean startBattle(String options, boolean currentBattle) {
        // A previous Python worker must finish before its process-global core can be reused.
        if (!admitStart("battle")) return false;
        ApkBattleSession campaign = null;
        try {
            org.json.JSONObject config = new org.json.JSONObject(options == null ? "{}" : options);
            String matchMode = MatchEntryOptions.parseMode(config);
            String mode = GameEntryGate.parseMode(config);
            cancelMulligan();
            String foreground = activePackage();
            GameEntryGate entryGate = new GameEntryGate(mode, foreground, foregroundGeneration,
                    android.os.SystemClock.elapsedRealtime());
            campaign = new ApkBattleSession(this, config.toString(), entryGate);
            battleSession = campaign;
            if (currentBattle) {
                campaign.beginCurrentBattle();
            } else if (!MatchEntryOptions.TRAINING.equals(matchMode)) {
                campaign.beginMatch();
            } else if (config.optBoolean("start_with_opening", true) && !config.optBoolean("read_only", false)) {
                if (!startMulliganOnce(campaign::afterOpening, entryGate, campaign)) {
                    campaign.cancel("opening_start_failed");
                    return answerStart(false, "battle", "opening_start_failed", "");
                }
            } else campaign.beginBattle();
            boolean started = campaign.isActive() || campaign.isWorkerLaunched();
            if (started && !currentBattle && !MatchEntryOptions.TRAINING.equals(matchMode))
                getSharedPreferences("floating-control", MODE_PRIVATE).edit()
                        .putString("mode", matchMode).putInt("count", config.optInt("match_count",1)).apply();
            return answerStart(started, "battle", started ? "started" : "worker_start_failed", "");
        } catch (Exception error) {
            // Never cancel a prior campaign when this request failed before constructing its own.
            if (campaign != null) campaign.cancel("start_error:" + error.getClass().getSimpleName());
            return startError("battle", error);
        }
    }

    /** Refusals are request answers; battleReport() remains the actual campaign report. */
    public String lastStartAttempt() { return lastStartAttempt; }

    private boolean admitStart(String operation) {
        startPriorSessionId = priorSessionId();
        startPriorActive = battleSession != null && battleSession.isActive();
        BattleWorkerLease.Snapshot lease = BattleWorkerLease.snapshot();
        boolean ownerActive = lease.ownerToken instanceof ApkBattleSession
                && ((ApkBattleSession) lease.ownerToken).isActive();
        if (lease.ownerToken instanceof ApkBattleSession && lease.ownerToken != battleSession) {
            // A replacement Service may have no local report for the still-owned worker.
            startPriorSessionId = lease.sessionId;
            startPriorActive = ownerActive;
        }
        String reason = BattleStartAttempt.busyReason(lease, ownerActive);
        if (!reason.isEmpty()) {
            lastStartAttempt = BattleStartAttempt.report(false, operation, reason,
                    android.os.SystemClock.elapsedRealtime(), startPriorSessionId,
                    startPriorActive, "", lease, "");
            return false;
        }
        if (battleSession != null && battleSession.isActive() && lease.ownerToken != battleSession) {
            // A dashboard ownership probe may have already recovered the dead thread.
            // Invalidate its stale campaign report; this does not release any worker.
            battleSession.cancel("campaign_lease_recovered");
        }
        return true;
    }

    private String priorSessionId() {
        return battleSession == null ? "" : battleSession.sessionId();
    }

    private boolean answerStart(boolean accepted, String operation, String reason, String errorDetail) {
        lastStartAttempt = BattleStartAttempt.report(accepted, operation, reason,
                android.os.SystemClock.elapsedRealtime(), startPriorSessionId, startPriorActive,
                accepted ? priorSessionId() : "", BattleWorkerLease.snapshot(), errorDetail);
        return accepted;
    }

    private boolean startError(String operation, Exception error) {
        String reason = error instanceof org.json.JSONException || error instanceof IllegalArgumentException
                ? "invalid_options" : "start_error";
        if ("current_game_not_foreground".equals(error.getMessage())) reason = "current_game_not_foreground";
        if ("battle_worker_busy".equals(error.getMessage())) {
            BattleWorkerLease.Snapshot lease = BattleWorkerLease.snapshot();
            boolean ownerActive = lease.ownerToken instanceof ApkBattleSession
                    && ((ApkBattleSession) lease.ownerToken).isActive();
            reason = BattleStartAttempt.busyReason(lease, ownerActive);
            if (reason.isEmpty()) reason = "worker_claim_race";
        }
        return answerStart(false, operation, reason, error.getClass().getSimpleName() + ":" + error.getMessage());
    }

    public void cancelBattle() {
        if (battleSession != null) battleSession.cancel("user_stop");
        cancelMulligan();
    }

    /** UI clicks are the only callers; polling/rendering never starts a worker. */
    boolean startFromFloatingControl(boolean currentBattle) {
        try {
            android.content.SharedPreferences prefs=getSharedPreferences("floating-control",MODE_PRIVATE);
            String mode=prefs.getString("mode",MatchEntryOptions.CASUAL);
            org.json.JSONObject config=MainActivity.battleOptions(false,mode,
                    currentBattle?1:prefs.getInt("count",1));
            config.put("entry_mode",GameEntryGate.CURRENT_GAME);
            if(currentBattle)config.put("start_with_opening",false);
            return startBattle(config.toString(),currentBattle);
        } catch(Exception error) { return startError("battle",error); }
    }

    void withoutOverlay(java.util.function.Consumer<Runnable> work) {
        if(floatingControl==null)work.accept(()->{});else floatingControl.withoutOverlay(work);
    }
    void noteFloatingAction(String context) {
        screenshotHandler.post(()->{if(floatingControl!=null)floatingControl.noteAction(context);});
    }
    GameFloatingControl floatingControlForTest() { return floatingControl; }

    /** Debug-only: arm a settlement-only campaign on the current screen.
     *
     * The option must carry debug_stage=settle, which only the debug-build
     * receiver sets; entry mode is current_game so nothing is launched and no
     * foreground transition is fabricated. */
    public synchronized boolean startSettleOnce(String options) {
        if (!admitStart("settle")) return false;
        ApkBattleSession campaign = null;
        try {
            org.json.JSONObject config = new org.json.JSONObject(options == null ? "{}" : options);
            if (!"settle".equals(config.optString("debug_stage", ""))) {
                return answerStart(false, "settle", "invalid_options", "debug_stage must be settle");
            }
            MatchEntryOptions.parseMode(config);
            String mode = GameEntryGate.parseMode(config);
            cancelMulligan();
            String foreground = activePackage();
            GameEntryGate entryGate = new GameEntryGate(mode, foreground, foregroundGeneration,
                    android.os.SystemClock.elapsedRealtime());
            campaign = new ApkBattleSession(this, config.toString(), entryGate);
            battleSession = campaign;
            campaign.beginSettleOnly();
            boolean started = campaign.isActive() || campaign.isWorkerLaunched();
            return answerStart(started, "settle", started ? "started" : "worker_start_failed", "");
        } catch (Exception error) {
            if (campaign != null) campaign.cancel("start_error:" + error.getClass().getSimpleName());
            return startError("settle", error);
        }
    }
    public String battleReport() { return battleSession == null ? "{}" : battleSession.report(); }
    public String battleProgressReport() { return battleSession == null ? "{}" : battleSession.progressReport(); }

    public void cancelMulligan() {
        if (mulliganSession != null) mulliganSession.cancel();
    }

    public String lastSessionReport() { return lastSessionReport; }

    public void requestScreenshot(Consumer<String> callback) {
        requestFrame(new FrameSource.Callback() {
            @Override
            public void onFrame(FrameSnapshot snapshot) {
                try {
                    callback.accept("截图能力：成功（" + snapshot.width() + "×" + snapshot.height()
                            + "，已转为 Bitmap）。");
                } finally {
                    snapshot.close();
                }
            }

            @Override
            public void onFailure(String message) {
                callback.accept(message);
            }
        });
    }

    /**
     * Captures one read-only frame and converts the platform HardwareBuffer
     * into a software ARGB_8888 Bitmap before invoking the callback.
     */
    @Override
    public void requestFrame(FrameSource.Callback callback) {
        requestFrame(callback, false);
    }

    /** Dynamic pipeline only: keep original screenshot pixels and dimensions. */
    public void requestNativeFrame(FrameSource.Callback callback) {
        requestFrame(callback, true);
    }

    private void requestFrame(FrameSource.Callback callback, boolean preserveSourcePixels) {
        if (callback == null) {
            return;
        }
        final long requestedAtMillis = System.currentTimeMillis();
        screenshotHandler.post(() -> requestFrameWhenAllowed(callback, requestedAtMillis, preserveSourcePixels));
    }

    private void requestFrameWhenAllowed(FrameSource.Callback callback, long requestedAtMillis, boolean preserveSourcePixels) {
        if (screenshotRequestsClosed) {
            callback.onFailure("截图能力：服务已断开。");
            return;
        }
        long delay = screenshotPacer.acquireDelay(android.os.SystemClock.elapsedRealtime());
        if (delay > 0) {
            screenshotHandler.postDelayed(() -> requestFrameWhenAllowed(callback, requestedAtMillis, preserveSourcePixels), delay);
            return;
        }
        withoutOverlay(release -> takeFrameNow(new FrameSource.Callback() {
            @Override public void onFrame(FrameSnapshot snapshot) {
                try { callback.onFrame(snapshot); } finally { release.run(); }
            }
            @Override public void onFailure(String reason) {
                try { callback.onFailure(reason); } finally { release.run(); }
            }
        },requestedAtMillis,preserveSourcePixels));
    }

    private void takeFrameNow(FrameSource.Callback callback,long requestedAtMillis,boolean preserveSourcePixels) {
        if(screenshotRequestsClosed){callback.onFailure("截图能力：服务已断开。");return;}
        // Every admitted request takes a new native screenshot. Keep the original
        // request time as the conservative age bound; waiting never refreshes it.
        try {
        takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, new TakeScreenshotCallback() {
            @Override
            public void onSuccess(ScreenshotResult screenshot) {
                HardwareBuffer hardwareBuffer = screenshot.getHardwareBuffer();
                if (hardwareBuffer == null) {
                    callback.onFailure("截图能力：系统返回空 HardwareBuffer。");
                    return;
                }
                Bitmap hardwareBitmap = null;
                try {
                    hardwareBitmap = Bitmap.wrapHardwareBuffer(hardwareBuffer, screenshot.getColorSpace());
                    if (hardwareBitmap == null) {
                        callback.onFailure("截图能力：无法包装 HardwareBuffer。");
                        return;
                    }
                    int sourceWidth = hardwareBitmap.getWidth();
                    int sourceHeight = hardwareBitmap.getHeight();
                    Bitmap softwareBitmap = hardwareBitmap.copy(Bitmap.Config.ARGB_8888, false);
                    if (softwareBitmap == null) {
                        callback.onFailure("截图能力：无法复制为软件 Bitmap。");
                        return;
                    }
                    Bitmap normalized = preserveSourcePixels ? softwareBitmap : normalize(softwareBitmap);
                    KardsAccessibilityService.this.sourceWidth = sourceWidth;
                    KardsAccessibilityService.this.sourceHeight = sourceHeight;
                    // Use request start as a conservative age bound, including capture/conversion latency.
                    callback.onFrame(new FrameSnapshot(normalized, requestedAtMillis,
                            sourceWidth, sourceHeight));
                } catch (RuntimeException error) {
                    callback.onFailure("截图能力：Bitmap 转换失败：" + error.getClass().getSimpleName());
                } finally {
                    if (hardwareBitmap != null && !hardwareBitmap.isRecycled()) {
                        hardwareBitmap.recycle();
                    }
                    hardwareBuffer.close();
                }
            }

            @Override
            public void onFailure(int errorCode) {
                callback.onFailure("截图能力：失败，错误码=" + errorCode + "；后续接入 MediaProjection 备用通道。");
            }
        });
        } catch (RuntimeException error) {
            callback.onFailure("截图能力：请求失败：" + error.getClass().getSimpleName());
        }
    }

    /** Normalize every supported landscape profile into the logical 1280x720 canvas. */
    private static Bitmap normalize(Bitmap bitmap) {
        if (bitmap.getWidth() == 1280 && bitmap.getHeight() == 720) {
            return bitmap;
        }
        int width = 1280;
        Bitmap scaled = Bitmap.createScaledBitmap(bitmap, width, 720, true);
        if (scaled != bitmap && !bitmap.isRecycled()) {
            bitmap.recycle();
        }
        return scaled;
    }

    public void probeGesture(Consumer<String> callback) {
        if (!getPackageName().equals(activePackage())) {
            callback.accept("手势探针已取消：原型页面不在前台。");
            return;
        }
        Path path = new Path();
        path.moveTo(10f, 10f);
        path.lineTo(11f, 11f);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0, 80))
                .build();
        dispatchGesture(gesture, new GestureResultCallback() {
            @Override
            public void onCompleted(GestureDescription description) {
                callback.accept("手势能力：系统已接受探针（未触碰 KARDS）。");
            }

            @Override
            public void onCancelled(GestureDescription description) {
                callback.accept("手势能力：探针被取消。");
            }
        }, new Handler(Looper.getMainLooper()));
    }
}
