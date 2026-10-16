package com.kards.mobilert;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Path;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** One explicitly started campaign. Python owns decisions; this boundary owns all device I/O. */
public final class ApkBattleSession {
    private final EvidenceRetention retention;
    private WorkingFrameEvidence workingEvidence;
    private int lastRecordedRound;
    private static final String GAME = "com.android1939.kards";
    private static final long FRAME_MAX_AGE_MS = 3000;
    private final KardsAccessibilityService service;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final AtomicBoolean cancelled = new AtomicBoolean();
    private final JSONObject options;
    private final File directory;
    private final long started = SystemClock.elapsedRealtime();
    private final GameEntryGate entryGate;
    private final boolean startupAdmission;
    private volatile long deadline;
    private final int maxSeconds;
    private final int maxInputs;
    private final boolean readOnly;
    private final String matchMode;
    private final MatchCampaignPlan campaignPlan;
    private final JSONArray rounds = new JSONArray();
    private final BattleProgressReport.RoundTotals roundTotals = new BattleProgressReport.RoundTotals();
    private volatile File roundDirectory;
    private volatile int roundIndex = 1;
    private volatile int completedMatches;
    private volatile long priorMenuInputs, priorOpeningInputs, priorSettleInputs;
    private volatile long roundBattleStartedInputs;
    private volatile long roundStarted;
    private volatile long roundFrameStartedSequence;
    private volatile JSONObject lastBattleResult;
    private volatile boolean active = true;
    private volatile boolean workerStarted;
    private volatile boolean workerLaunched;
    private volatile boolean workerExited;
    private volatile String stopReason = "";
    private volatile String report = "{}";
    private volatile String progressReport = "{}";
    private volatile JSONObject lastFrame;
    private volatile long consumedFrame;
    private volatile long frameSequence;
    private volatile long inputs;
    private volatile int menuInputs;
    private volatile String stage;
    private volatile boolean inputStatusUncertain;
    private volatile JSONObject opening;
    private volatile JSONObject menuResult;
    private volatile JSONObject lastMenuEvent;
    private volatile JSONObject settleResult;
    private volatile int settleClicks;
    private final boolean settleEnabled;
    private final int[][] settlePoints;

    ApkBattleSession(KardsAccessibilityService service, String configuration, GameEntryGate entryGate) throws Exception {
        this.service = service;
        this.entryGate = entryGate;
        options = new JSONObject(configuration == null ? "{}" : configuration);
        if(options.has("retain_full_evidence") && !(options.opt("retain_full_evidence") instanceof Boolean))
            throw new IllegalArgumentException("invalid_retain_full_evidence");
        boolean fullEvidence=options.optBoolean("retain_full_evidence",false);
        if(fullEvidence && (service.getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE)==0)
            throw new IllegalArgumentException("full_evidence_requires_debug_build");
        matchMode = MatchEntryOptions.parseMode(options);
        campaignPlan = new MatchCampaignPlan(options, matchMode);
        if (!GameEntryGate.parseMode(options).equals(entryGate.mode)) throw new IllegalArgumentException("entry_mode_mismatch");
        options.put("entry_mode", entryGate.mode);
        maxSeconds = Math.max(15, Math.min(1800, options.optInt("max_seconds", campaignPlan.isMultiple() ? 1800 : 1200)));
        maxInputs = Math.max(0, Math.min(200, options.optInt("max_inputs", campaignPlan.isMultiple() ? 200 : 120)));
        readOnly = options.optBoolean("read_only", false);
        if (options.optBoolean("native_observe_only", false)
                && (!readOnly || (service.getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) == 0))
            throw new IllegalArgumentException("native_observation_requires_debug_read_only");
        options.put("max_seconds", maxSeconds).put("max_inputs", maxInputs).put("read_only", readOnly);
        options.put("match_mode", matchMode);
        options.put("match_count", campaignPlan.matchCount);
        if (campaignPlan.isMultiple()) options.put("start_with_opening", true);
        settleEnabled = options.optBoolean("post_match_settle", true) && !readOnly
                && !MatchEntryOptions.TRAINING.equals(matchMode);
        settlePoints = SettleDispatchGuard.parsePoints(options.optJSONArray("settle_points"));
        options.put("post_match_settle", settleEnabled);
        stage = !MatchEntryOptions.TRAINING.equals(matchMode) ? "menu"
                : options.optBoolean("start_with_opening", true) && !readOnly ? "opening" : "battle";
        startupAdmission=GameEntryGate.LAUNCH_GAME.equals(entryGate.mode) && "menu".equals(stage)
                && !options.optBoolean("native_observe_only",false);
        if(startupAdmission)entryGate.enableBootstrap(service.gameDepartureEpoch());
        String id = System.currentTimeMillis() + "-" + UUID.randomUUID().toString().substring(0, 8);
        directory = new File(service.getFilesDir(), "battle/" + id);
        if (!directory.mkdirs()) throw new IllegalStateException("evidence_directory");
        retention=fullEvidence?null:new EvidenceRetention(service.getFilesDir(),directory);
        if(fullEvidence && !new File(directory,"frames").mkdirs())throw new IllegalStateException("evidence_directory");
        startRound(1);
        save(new File(directory, "options.json"), options.toString(2));
        if (!BattleWorkerLease.tryClaim(this, directory.getName())) throw new IllegalStateException("battle_worker_busy");
        publish("armed", "waiting_for_game", null);
        main.postDelayed(this::watchdog, 500);
    }

    /** Dismiss whatever the verified result left on screen. */
    private JSONObject runSettlement(JSONObject engineResult) throws Exception {
        stage = "settle";
        lastFrame = null;
        publish("settle", "settle_started", null);
        // The module parses this itself: neither a JSONArray nor a Java List is
        // iterable from Chaquopy, and a plain string crosses that boundary
        // without type surprises.
        org.json.JSONArray points = new org.json.JSONArray();
        for (int[] point : settlePoints) points.put(new org.json.JSONArray().put(point[0]).put(point[1]));
        JSONObject result = new JSONObject(Python.getInstance().getModule("apk_settle")
                .callAttr("run", new Bridge(), points.toString(),
                        menuAssetsDirectory().getAbsolutePath(),
                        (deadline - SystemClock.elapsedRealtime()) / 1000.0,
                        true, MatchCampaignPlan.resultConfirmed(engineResult),
                        (service.getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0
                                && "settle".equals(options.optString("debug_stage", "")),
                        options.optBoolean("native_menu", false))
                .toString());
        saveRound("settle.json", result.toString(2));
        publish("settle", result.optString("reason", "settle_finished"), result);
        return result;
    }

    /** Menu templates for this campaign; the settlement recogniser reuses them. */
    private File menuAssetsDirectory() {
        return new File(service.getFilesDir(), "match-entry/" + directory.getName());
    }

    public boolean isActive() { return active && !cancelled.get(); }
    public boolean isWorkerRunning() { return workerStarted && !workerExited; }
    public boolean isWorkerLaunched() { return workerLaunched; }
    public String report() { return report; }
    public String progressReport() { return progressReport; }
    String sessionId() { return directory.getName(); }
    boolean canContinueOpening() {
        return isActive() && "opening".equals(stage) && SystemClock.elapsedRealtime() < deadline
                && roundInputs() < maxInputs;
    }

    /** Called only with the existing bounded opening session's terminal report. */
    public void afterOpening(String json) {
        if (!isActive() || workerStarted) return;
        try {
            JSONObject result = new JSONObject(json);
            if (result.optBoolean("active", true)) return;
            opening = result;
            saveRound("opening.json", json);
            if (result.optBoolean("verified") || "already_my_turn_no_input".equals(result.optString("stopReason"))) {
                beginBattle();
            } else {
                finish("opening_not_verified", null);
            }
        } catch (Exception error) { finish("opening_report_error:" + error.getClass().getSimpleName(), null); }
    }

    boolean usesNativeFrames() { return options.optBoolean("native_menu", false); }
    File openingEvidenceRoot() { return retention==null?service.getFilesDir():roundDirectory; }

    public void beginBattle() {
        if (!MatchEntryOptions.TRAINING.equals(matchMode)) { cancel("match_entry_required"); return; }
        startWorker(false);
    }

    public void beginMatch() {
        if (MatchEntryOptions.TRAINING.equals(matchMode)) { cancel("match_entry_mode_required"); return; }
        startWorker(true);
    }

    /** Explicit overlay click: attach to the current game, never manufacture menu/opening evidence. */
    void beginCurrentBattle() {
        if(campaignPlan.matchCount!=1 || !usesNativeFrames()
                || !GameEntryGate.CURRENT_GAME.equals(entryGate.mode) || !entryGate.isAdmitted()) {
            cancel("invalid_current_battle_entry");return;
        }
        startWorker(false);
    }

    /** Debug-only: run the settlement dismissal against the screen that is up
     *  now, with no battle and no coordinates from outside. Same guards,
     *  budget and evidence as the automatic path, and only reachable from the
     *  debug-build broadcast receiver. */
    public void beginSettleOnly() {
        if (!"settle".equals(options.optString("debug_stage", ""))) { cancel("debug_stage_required"); return; }
        if (MatchEntryOptions.TRAINING.equals(matchMode)) { cancel("settle_mode_required"); return; }
        startWorker(false);
    }

    private synchronized void startWorker(boolean enterMatch) {
        if (!isActive() || workerStarted) return;
        workerStarted = true;
        boolean settleOnly = "settle".equals(options.optString("debug_stage", ""));
        stage = settleOnly ? "settle" : enterMatch ? "menu" : "battle";
        try {
        Thread worker = new Thread(() -> {
            try {
                File core = prepareCore();
                if (!Python.isStarted()) Python.start(new AndroidPlatform(service.getApplicationContext()));
                Bridge bridge = new Bridge();
                if (options.optBoolean("native_observe_only", false)) {
                    stage = "battle";
                    copyAssets("match-entry", menuAssetsDirectory());
                    File nativeOpening = new File(service.getFilesDir(), "native-opening/" + directory.getName());
                    copyAssets("mulligan-one-shot", nativeOpening);
                    NativeOnnxModels.get(service).warm();
                    JSONObject result = new JSONObject(Python.getInstance().getModule("apk_native_bootstrap")
                            .callAttr("live_observe", bridge, core.getAbsolutePath(), menuAssetsDirectory().getAbsolutePath(),
                                    nativeOpening.getAbsolutePath(), roundDirectory.getAbsolutePath()).toString());
                    saveRound("native-observations.json", result.toString(2));
                    finish(cancelled.get() ? stopReason : result.optString("stop_reason"), result);
                    return;
                }
                if (settleOnly) {
                    // Debug-only entry: no battle, no menu walk; the settlement
                    // dismissal runs against whatever screen is up now, under
                    // the same guards and click budget. The recogniser assets
                    // are staged here because the menu path is skipped.
                    copyAssets("match-entry", menuAssetsDirectory());
                    JSONObject result = runSettlement(new JSONObject());
                    finish(cancelled.get() ? stopReason : "settle_only_finished", result);
                    return;
                }
                while (true) {
                if (enterMatch) {
                    String rejection = enterMatchAndOpening(bridge);
                    if (rejection != null) { recordRound(rejection, null); finish(rejection, null); return; }
                }
                if (!isActive()) { finish(stopReason, null); return; }
                stage = "battle";
                lastFrame = null;
                publish("battle", "battle_started", null);
                JSONObject runtimeOptions = runtimeOptions(options);
                runtimeOptions.put("max_inputs", Math.max(1, maxInputs - roundInputs()));
                runtimeOptions.put("max_seconds", Math.max(15, (int)((deadline-SystemClock.elapsedRealtime())/1000L)));
                String result;
                if (usesNativeFrames()) {
                    copyAssets("match-entry", menuAssetsDirectory());
                    File nativeOpening = new File(service.getFilesDir(), "native-opening/" + directory.getName());
                    copyAssets("mulligan-one-shot", nativeOpening);
                    NativeOnnxModels.get(service).warm();
                    result = Python.getInstance().getModule("apk_native_bootstrap")
                            .callAttr("run_battle", bridge, core.getAbsolutePath(), menuAssetsDirectory().getAbsolutePath(),
                                    nativeOpening.getAbsolutePath(), roundDirectory.getAbsolutePath(), runtimeOptions.toString()).toString();
                } else result = Python.getInstance().getModule("apk_battle_runtime")
                        .callAttr("run", bridge, core.getAbsolutePath(), roundDirectory.getAbsolutePath(),
                                runtimeOptions.toString()).toString();
                JSONObject engineResult = new JSONObject(result);
                lastBattleResult = engineResult;
                saveRound("engine.json", engineResult.toString(2));
                saveRound("battle-summary.json", engineResult.toString(2));
                // A verified result leaves the game on a screen the engine does
                // not handle. Settlement dismisses it inside the same campaign,
                // lease and foreground admission, and never changes the battle
                // report - it only adds its own evidence.
                if (!cancelled.get() && !inputStatusUncertain && settleEnabled
                        && MatchCampaignPlan.resultConfirmed(engineResult)) {
                    try {
                        settleResult = runSettlement(engineResult);
                    } catch (Throwable settleFailure) {
                        android.util.Log.e("KardsBattle", "Settlement failed", settleFailure);
                        settleResult = new JSONObject().put("reason", "settle_error:"
                                + settleFailure.getClass().getSimpleName());
                    }
                }
                if (MatchCampaignPlan.resultConfirmed(engineResult)) completedMatches++;
                if (SystemClock.elapsedRealtime() >= deadline) cancel("time_budget");
                String next = campaignPlan.continuationReason(roundIndex, engineResult, settleResult,
                        cancelled.get(), inputStatusUncertain, maxSeconds * 1000L, maxInputs);
                recordRound(cancelled.get() ? stopReason : next == null ? "next_round_ready" : next, engineResult);
                if (next != null) {
                    finish(cancelled.get() ? stopReason : campaignPlan.matchCount == 1 ? "engine_finished" : next, engineResult);
                    return;
                }
                if (!advanceRound()) { finish(stopReason, engineResult); return; }
                publish("round", "next_round_started", null);
                }
            } catch (Throwable error) {
                android.util.Log.e("KardsBattle", "Embedded engine failed", error);
                finish(cancelled.get() ? stopReason : ("battle".equals(stage) ? "engine" : stage) + "_error:" + error, null);
            } finally {
                workerExited = true;
                if(workingEvidence!=null)try { workingEvidence.finish(!MatchCampaignPlan.resultConfirmed(lastBattleResult)); }
                catch(Exception error){android.util.Log.e("KardsRetention","Final screenshot archive failed",error);}
                if(retention!=null)retention.prune(null,System.currentTimeMillis());
                BattleWorkerLease.release(this);
            }
        }, "kards-embedded-battle");
        if (!BattleWorkerLease.bindWorker(this, worker)) throw new IllegalStateException("battle_worker_binding_failed");
        worker.start();
        workerLaunched = true;
        }
        catch (Throwable error) {
            workerExited = true;
            finish("worker_start_failed:" + error.getClass().getSimpleName(), null);
            BattleWorkerLease.release(this);
        }
    }

    /** Menu and opening execute inside the same worker, campaign, lease and foreground admission. */
    private String enterMatchAndOpening(Bridge bridge) throws Exception {        if (!isActive()) return stopReason;
        File menuAssets = new File(service.getFilesDir(), "match-entry/" + directory.getName());
        copyAssets("match-entry", menuAssets);
        if (!isActive()) return stopReason;
        if (options.optBoolean("native_menu", false)) NativeOnnxModels.get(service).warm();
        String result = Python.getInstance().getModule("apk_match_entry")
                .callAttr("run", bridge, menuAssets.getAbsolutePath(), matchMode,
                        options.optBoolean("native_menu", false)).toString();
        menuResult = new JSONObject(result);
        saveRound("menu-summary.json", result);
        publish("menu", menuResult.optString("reason", "menu_finished"), null);
        if (!isActive()) return stopReason;
        if (!MatchEntryOptions.isMenuReady(menuResult, matchMode)) {
            return "menu_entry_failed:" + menuResult.optString("reason", "unverified_result");
        }
        stage = "opening";
        entryGate.sealBootstrap();
        lastFrame = null;
        publish("opening", "waiting_for_opening", null);
        return awaitCampaignOpening();
    }

    private String awaitCampaignOpening() throws Exception {
        CountDownLatch terminal = new CountDownLatch(1);
        AtomicBoolean waiting = new AtomicBoolean(true);
        AtomicBoolean completed = new AtomicBoolean();
        AtomicReference<String> error = new AtomicReference<>();
        main.post(() -> {
            if (!waiting.get() || !isActive()) { error.set("cancelled"); terminal.countDown(); return; }
            try {
                boolean startedOpening = service.startCampaignOpening(this, entryGate, json -> {
                    if (!waiting.get()) return;
                    try {
                        JSONObject value = new JSONObject(json);
                        opening = value;
                        if (Boolean.FALSE.equals(value.opt("active"))) {
                            completed.set(true);
                            terminal.countDown();
                        }
                    } catch (Exception invalid) { error.set("opening_report_error"); terminal.countDown(); }
                });
                if (!startedOpening) { error.set("opening_start_failed"); terminal.countDown(); }
            } catch (Throwable failure) { error.set("opening_start_failed:" + failure.getClass().getSimpleName()); terminal.countDown(); }
        });
        long openingDeadline = Math.min(deadline, SystemClock.elapsedRealtime()
                + BoundedMulliganSession.TIME_BUDGET_MS + 8000);
        try {
            while (!terminal.await(200, TimeUnit.MILLISECONDS)) {
                if (!isActive()) return stopReason;
                if (SystemClock.elapsedRealtime() >= openingDeadline) {
                    cancel(SystemClock.elapsedRealtime() >= deadline ? "time_budget" : "opening_callback_timeout");
                    return stopReason;
                }
            }
            if (!isActive()) return stopReason;
            if (error.get() != null) return error.get();
            JSONObject result = opening;
            if (result == null || !completed.get()) return "opening_report_missing";
            return Boolean.TRUE.equals(result.opt("verified"))
                    || "already_my_turn_no_input".equals(result.opt("stopReason")) ? null : "opening_not_verified";
        } finally {
            waiting.set(false);
            if (!completed.get()) {
                // Invalidate this campaign before a delayed main-thread start/dispatch can run.
                if (isActive()) cancel(error.get() == null ? "opening_wait_cancelled" : error.get());
                JSONObject pending = opening;
                if (pending != null && pending.optBoolean("dispatchAccepted") && !pending.optBoolean("gestureCompleted")) {
                    inputStatusUncertain = true;
                }
                CountDownLatch stopped = new CountDownLatch(1);
                main.post(() -> { try { service.cancelCampaignOpening(this); } finally { stopped.countDown(); } });
                stopped.await(8, TimeUnit.SECONDS);
            }
            if (opening != null) saveRound("opening.json", opening.toString());
        }
    }

    public void cancel(String reason) {
        if (!active) return;
        stopReason = reason;
        cancelled.set(true);
        publish("stopping", reason, null);
        if (!MatchEntryOptions.TRAINING.equals(matchMode) && "opening".equals(stage)) {
            main.post(() -> service.cancelCampaignOpening(this));
        }
        if (!workerStarted) finish(reason, null);
    }

    private synchronized void watchdog() {
        if (!active) return;
        if (SystemClock.elapsedRealtime() >= deadline) cancel("time_budget");
        if (entryGate.isAdmitted()) {
            String rejection=checkEntry(service.foregroundSnapshot());
            if(rejection!=null && !GameEntryGate.WAITING.equals(rejection))cancel("foreground_changed");
        }
        if (active) main.postDelayed(this::watchdog, 500);
    }

    private synchronized String checkEntry(ForegroundSnapshot facts) {
        if(!"menu".equals(stage) || roundIndex!=1 || roundInputs()>0)entryGate.sealBootstrap();
        long prior=entryGate.admittedGeneration();
        String rejection=entryGate.check(facts.foregroundPackage,facts.generation,facts.departureEpoch);
        if(rejection==null && prior>=0 && prior!=entryGate.admittedGeneration()) {
            JSONObject oldFrame=lastFrame;
            if(oldFrame!=null && oldFrame.optLong("foreground_generation",-1)!=entryGate.admittedGeneration())lastFrame=null;
            try { publish("startup_window_changed","waiting_for_fresh_game_capture",entryGate.evidence()); }
            catch(Exception error) { android.util.Log.w("KardsBattle","Cannot record startup window",error); }
        }
        return rejection;
    }

    private synchronized void startRound(int index) throws Exception {
        if(workingEvidence!=null)workingEvidence.finish(false);
        roundIndex = index;
        roundStarted = SystemClock.elapsedRealtime();
        deadline = MatchCampaignPlan.roundDeadline(roundStarted, maxSeconds);
        roundFrameStartedSequence = frameSequence;
        roundDirectory = new File(directory, String.format(Locale.ROOT, "rounds/%03d", index));
        if (!roundDirectory.isDirectory() && !roundDirectory.mkdirs()) throw new IllegalStateException("round_directory");
        if(retention!=null)retention.begin(roundDirectory,System.currentTimeMillis());
        workingEvidence=retention==null?null:new WorkingFrameEvidence(roundDirectory);
        menuInputs = 0;
        settleClicks = 0;
        opening = null;
        menuResult = null;
        lastMenuEvent = null;
        settleResult = null;
        lastBattleResult = null;
        lastFrame = null;
        roundBattleStartedInputs = inputs;
        stage = !MatchEntryOptions.TRAINING.equals(matchMode) ? "menu"
                : options.optBoolean("start_with_opening", true) && !readOnly ? "opening" : "battle";
    }

    private synchronized boolean advanceRound() throws Exception {
        if (!isActive()) return false;
        if (inputStatusUncertain) { cancel("campaign_input_status_uncertain"); return false; }
        if (SystemClock.elapsedRealtime() >= deadline) { cancel("time_budget"); return false; }
        String rejection = campaignPlan.continuationReason(roundIndex, lastBattleResult, settleResult,
                false, false, maxSeconds * 1000L, maxInputs);
        if (rejection != null) { stopReason = rejection; return false; }
        priorMenuInputs += menuInputs;
        priorOpeningInputs += opening == null ? 0 : opening.optInt("gameInputs");
        priorSettleInputs += settleClicks;
        startRound(roundIndex + 1);
        return true;
    }

    private int roundInputs() {
        return MatchCampaignPlan.roundInputs(inputs, roundBattleStartedInputs, menuInputs,
                opening == null ? 0 : opening.optInt("gameInputs"), settleClicks);
    }

    private long totalInputs() {
        return inputs + priorMenuInputs + menuInputs + priorOpeningInputs
                + (opening == null ? 0 : opening.optInt("gameInputs")) + priorSettleInputs + settleClicks;
    }

    private void saveRound(String name, String value) throws Exception {
        save(new File(roundDirectory, name), value);
        // Keep the original single-round paths for existing consumers only.
        // Later rounds never replace the first round's preserved evidence.
        if (retention==null && roundIndex == 1) save(new File(directory, name), value);
    }

    private synchronized void recordRound(String reason, JSONObject engine) throws Exception {
        if (lastRecordedRound >= roundIndex) return;
        JSONObject item = new JSONObject().put("round_index", roundIndex).put("reason", reason)
                .put("directory", roundDirectory.getAbsolutePath())
                .put("elapsed_ms", SystemClock.elapsedRealtime()-roundStarted)
                .put("started_elapsed_ms", roundStarted).put("deadline_elapsed_ms", deadline)
                .put("max_seconds", maxSeconds).put("max_inputs", maxInputs)
                .put("round_inputs", roundInputs()).put("frames", frameSequence-roundFrameStartedSequence)
                .put("menu_inputs", menuInputs).put("game_inputs", inputs-roundBattleStartedInputs)
                .put("opening_inputs", opening == null ? 0 : opening.optInt("gameInputs"))
                .put("settle_inputs", settleClicks)
                .put("menu", menuResult == null ? JSONObject.NULL : menuResult)
                .put("opening", opening == null ? JSONObject.NULL : opening)
                .put("engine", engine == null ? JSONObject.NULL : engine)
                .put("settle", settleResult == null ? JSONObject.NULL : settleResult)
                .put("result_confirmed", MatchCampaignPlan.resultConfirmed(engine))
                .put("return_confirmed", MatchCampaignPlan.returned(settleResult))
                .put("input_status_uncertain", inputStatusUncertain);
        save(new File(roundDirectory, "summary.json"), item.toString(2));
        rounds.put(item);
        roundTotals.add(item);
        lastRecordedRound=roundIndex;
        if(retention!=null){
            retention.close(roundDirectory);
            while(rounds.length()>EvidenceRetention.MAX_ROUNDS)rounds.remove(0);
        }
    }

    private synchronized void finish(String reason, JSONObject result) {
        if (!active) return;
        active = false;
        stopReason = reason;
        cancelled.set(true);
        try { recordRound(reason, result == null ? lastBattleResult : result); }
        catch (Exception error) {
            stopReason = "evidence_write_failed";
            android.util.Log.e("KardsBattle", "Cannot save round", error);
        }
        publish("finished", stopReason, result);
        if (!workerStarted) BattleWorkerLease.release(this);
    }

    private synchronized void publish(String event, String reason, JSONObject result) {
        try {
            JSONObject json = new JSONObject().put("event", event).put("active", isActive())
                    .put("session_id", directory.getName()).put("directory", directory.getAbsolutePath())
                    .put("elapsed_ms", SystemClock.elapsedRealtime() - started).put("reason", reason)
                    .put("game_inputs", inputs).put("frames", frameSequence).put("read_only", readOnly)
                    .put("match_mode", matchMode).put("stage", stage).put("menu_inputs", menuInputs)
                    .put("match_count", campaignPlan.matchCount).put("round_index", roundIndex)
                    .put("completed_matches", completedMatches)
                    .put("budget_scope", "per_round").put("round_started_elapsed_ms", roundStarted)
                    .put("round_deadline_elapsed_ms", deadline).put("round_max_seconds", maxSeconds)
                    .put("round_max_inputs", maxInputs).put("round_inputs", roundInputs())
                    .put("round_frames", frameSequence-roundFrameStartedSequence)
                    .put("menu", menuResult == null ? JSONObject.NULL : menuResult)
                    .put("menu_progress", lastMenuEvent == null ? JSONObject.NULL : lastMenuEvent)
                    .put("input_status_uncertain", inputStatusUncertain)
                    .put("total_game_inputs", totalInputs())
                    .put("total_menu_inputs", priorMenuInputs + menuInputs)
                    .put("total_settle_inputs", priorSettleInputs + settleClicks)
                    .put("settle", settleResult == null ? JSONObject.NULL : settleResult)
                    .put("opening", opening == null ? JSONObject.NULL : opening)
                    .put("entry", entryGate.evidence())
                    .put("engine", result != null ? result : "menu".equals(stage) && lastMenuEvent != null
                            ? lastMenuEvent : JSONObject.NULL);
            String nextProgress = BattleProgressReport.project(json, roundTotals);
            // Detailed closed-round ledgers are serialized once at the terminal boundary.
            // Status/UI/event transport stays bounded regardless of the number of rounds.
            String nextReport = retention==null && "finished".equals(event) ? json.put("rounds", rounds).toString() : nextProgress;
            // A finished progress record must never outrun its complete audit artifact.
            if ("finished".equals(event)) save(new File(directory, "summary.json"), nextReport);
            if(retention==null)append(new File(directory, "bridge-events.jsonl"), nextProgress);
            else save(new File(directory,"bridge-events.jsonl"),nextProgress+"\n");
            report = nextReport;
            progressReport = nextProgress;
        } catch (Exception error) {
            stopReason = "evidence_write_failed";
            cancelled.set(true);
            if (!workerStarted) {
                active = false;
                BattleWorkerLease.release(this);
            }
            try {
                JSONObject failure = new JSONObject().put("event", active ? "stopping" : "finished")
                        .put("active", false).put("session_id", directory.getName())
                        .put("directory", directory.getAbsolutePath()).put("elapsed_ms", SystemClock.elapsedRealtime()-started)
                        .put("reason", stopReason).put("match_mode", matchMode).put("stage", stage)
                        .put("match_count", campaignPlan.matchCount).put("round_index", roundIndex)
                        .put("completed_matches", completedMatches).put("input_status_uncertain", inputStatusUncertain);
                progressReport = BattleProgressReport.project(failure, roundTotals);
                report = progressReport;
            } catch (Exception projectionFailure) {
                progressReport = "{}";
                report = progressReport;
            }
            android.util.Log.e("KardsBattle", "Evidence error", error);
        }
    }

    /** Public methods are called synchronously from the embedded Python worker, never the UI thread. */
    public final class Bridge {
        /** Read-only OCR tied to the same current source-pixel capture. */
        public String recognizeNativeText(String request) throws Exception {
            requireWorker();
            if (isCancelled()) return failure("cancelled");
            JSONObject supplied = new JSONObject(request);
            JSONObject frame = lastFrame;
            if (frame == null || !"source_pixels".equals(frame.optString("coordinate_space")))
                return failure("native_ocr_requires_source_capture");
            for (String key : new String[]{"frame_id", "captured_elapsed_ms", "foreground_generation",
                    "source_width", "source_height", "png_path"}) {
                if (!supplied.has(key) || !String.valueOf(supplied.get(key)).equals(String.valueOf(frame.get(key))))
                    return failure("native_ocr_capture_mismatch");
            }
            long age = elapsedRealtime() - frame.getLong("captured_elapsed_ms");
            if (age < 0 || age > ("menu".equals(stage) ? 5000 : 3000)) return failure("native_ocr_capture_expired");
            String rejection = checkEntry(service.foregroundSnapshot());
            if (rejection != null) return failure(rejection);
            age = elapsedRealtime() - frame.getLong("captured_elapsed_ms");
            if (age < 0 || age > ("menu".equals(stage) ? 5000 : 3000)) return failure("native_ocr_capture_expired");
            {
                JSONObject result;
                if("opening_controls".equals(supplied.optString("ocr_scope"))) {
                    if(!"menu".equals(stage))return failure("opening_ocr_stage_required");
                    JSONArray regions=supplied.getJSONArray("ocr_regions");
                    if(regions.length()!=2)return failure("opening_ocr_region_count");
                    int width=frame.getInt("source_width"),height=frame.getInt("source_height");
                    for(int i=0;i<regions.length();i++) {
                        JSONArray box=regions.getJSONArray(i);
                        if(box.length()!=4)return failure("opening_ocr_region_bounds");
                        int x=box.getInt(0),y=box.getInt(1),w=box.getInt(2),h=box.getInt(3);
                        if(x<0 || y<0 || w<=0 || h<=0 || x>width-w || y>height-h
                            || (i==0 && (y!=0 || h>height*.23))
                            || (i==1 && y<height*.70))return failure("opening_ocr_region_bounds");
                    }
                    result=NativeOriginalOcr.inspectOpeningRegions(service,new File(frame.getString("png_path")),regions);
                } else if("menu_controls".equals(supplied.optString("ocr_scope"))) {
                    if(!("menu".equals(stage)||"settle".equals(stage)))return failure("menu_ocr_stage_required");
                    JSONArray regions=supplied.getJSONArray("ocr_regions");
                    if(regions.length()!=2)return failure("menu_ocr_region_count");
                    int width=frame.getInt("source_width"),height=frame.getInt("source_height");
                    for(int i=0;i<regions.length();i++) {
                        JSONArray box=regions.getJSONArray(i);
                        if(box.length()!=4)return failure("menu_ocr_region_bounds");
                        int x=box.getInt(0),y=box.getInt(1),w=box.getInt(2),h=box.getInt(3);
                        if(x<0 || y<0 || w<=0 || h<=0 || x>width-w || y>height-h)
                            return failure("menu_ocr_region_bounds");
                    }
                    result=NativeOriginalOcr.inspectMenuRegions(service,new File(frame.getString("png_path")),regions);
                } else if("turn_controls".equals(supplied.optString("ocr_scope"))) {
                    JSONArray regions=supplied.getJSONArray("ocr_regions");
                    String regionRejection=TurnOcrRegions.rejection(stage,regions,frame.getInt("source_width"),frame.getInt("source_height"));
                    if(regionRejection!=null)return failure(regionRejection);
                    result=NativeOriginalOcr.inspectTurnRegions(service,new File(frame.getString("png_path")),regions);
                } else if("result_controls".equals(supplied.optString("ocr_scope"))) {
                    JSONArray regions=supplied.getJSONArray("ocr_regions");
                    String regionRejection=ResultOcrRegions.rejection(stage,regions,frame.getInt("source_width"),frame.getInt("source_height"));
                    if(regionRejection!=null)return failure(regionRejection);
                    result=NativeOriginalOcr.inspectResultRegions(service,new File(frame.getString("png_path")),regions);
                } else result=NativeOriginalOcr.inspect(service,new File(frame.getString("png_path")),720);
                age = elapsedRealtime() - frame.getLong("captured_elapsed_ms");
                if (isCancelled()) return failure("cancelled");
                if (lastFrame != frame || age < 0 || age > ("menu".equals(stage) ? 5000 : 3000)) return new JSONObject(failure("native_ocr_capture_expired"))
                        .put("frame_age_ms", age).put("elapsed_ms", result.optDouble("elapsed_ms"))
                        .put("model_stage_ms", result.optJSONArray("model_stage_ms")).toString();
                rejection = checkEntry(service.foregroundSnapshot());
                if (rejection != null) return failure(rejection);
                age = elapsedRealtime() - frame.getLong("captured_elapsed_ms");
                if (isCancelled()) return failure("cancelled");
                if (lastFrame != frame || age < 0 || age > ("menu".equals(stage) ? 5000 : 3000))
                    return failure("native_ocr_capture_expired");
                for (String key : new String[]{"frame_id", "captured_elapsed_ms", "foreground_generation",
                        "source_width", "source_height", "png_path"}) result.put(key, frame.get(key));
                return result.put("ok", true).toString();
            }
        }
        private MulliganRecognizer openingInspector;
        private boolean resultAssetsPrepared;
        public boolean isCancelled() { return cancelled.get() || !active; }
        public long elapsedRealtime() { return SystemClock.elapsedRealtime(); }
        public long deadlineElapsedRealtime() { return deadline; }
        public void beginEvidenceEffect(long frameId) {
            requireWorker();if(workingEvidence!=null)workingEvidence.beginEffect(frameId);
        }
        public void endEvidenceEffect(boolean failed) {
            requireWorker();if(workingEvidence!=null)workingEvidence.endEffect(failed);
        }
        public void emit(String json) {
            try {
                JSONObject payload = new JSONObject(json);
                if(workingEvidence!=null){
                    JSONObject value=payload.optJSONObject("value");
                    if(value!=null && "native_observation".equals(payload.optString("kind"))){
                        workingEvidence.observeState(value.optLong("frame_id"),value.optString("state"));
                    }
                    if(value!=null && "hook".equals(payload.optString("kind"))){
                        workingEvidence.select(value.optLong("before_capture"),"action_before");
                        workingEvidence.select(value.optLong("after_capture"),"action_after");
                    }
                    if(value!=null && "end_turn_outcome".equals(payload.optString("kind"))){
                        JSONArray proof=value.optJSONArray("evidence_frame_ids");
                        if(proof!=null)for(int i=0;i<proof.length();i++)workingEvidence.select(proof.optLong(i),"end_turn_transition_proof");
                    }
                }
                boolean menu = "menu".equals(stage);
                if (menu) lastMenuEvent = payload;
                append(new File(roundDirectory, "bridge-payloads.jsonl"), json);
                saveRound(menu ? "last-menu-event.json" : "last-engine-event.json", payload.toString());
                publish(menu ? "menu" : "engine", payload.optString("kind", "progress"), payload);
            } catch (Exception error) { cancel("invalid_engine_report"); }
        }

        /** Inspects only the most recently captured PNG; it never confirms an opening or taps. */
        public String inspectOpening() throws Exception {
            requireWorker();
            if (isCancelled()) return failure("cancelled");
            if (!"menu".equals(stage)) return failure("not_menu_stage");
            JSONObject frame = lastFrame;
            if (frame == null) return failure("missing_frame");
            long age = elapsedRealtime() - frame.getLong("captured_elapsed_ms");
            if (age < 0 || age > 5000) return failure("frame_age_expired");
            if ("source_pixels".equals(frame.optString("coordinate_space"))) {
                File assets = new File(service.getFilesDir(), "native-opening/" + directory.getName());
                if (!new File(assets, "mulligan_title.png").isFile()) copyAssets("mulligan-one-shot", assets);
                JSONObject result = new JSONObject(Python.getInstance().getModule("apk_native.opening")
                        .callAttr("observe", frame.getString("png_path"), assets.getAbsolutePath(), frame.toString(), this).toString());
                age = elapsedRealtime() - frame.getLong("captured_elapsed_ms");
                String rejection = checkEntry(service.foregroundSnapshot());
                if (rejection != null) return failure(rejection);
                age = elapsedRealtime() - frame.getLong("captured_elapsed_ms");
                if (isCancelled() || lastFrame != frame || age < 0 || age > 5000)
                    return failure("frame_age_expired");
                return result.put("ok", true).put("frame_id", frame.getLong("frame_id")).toString();
            }
            BitmapFactory.Options decode = new BitmapFactory.Options();
            decode.inScaled = false;
            decode.inPreferredConfig = Bitmap.Config.ARGB_8888;
            Bitmap bitmap = BitmapFactory.decodeFile(frame.getString("png_path"), decode);
            if (bitmap == null) return failure("opening_png_decode_failed");
            try {
                if (openingInspector == null) openingInspector = new MulliganRecognizer(service);
                MulliganRecognizer.Result result = openingInspector.inspect(bitmap);
                age = elapsedRealtime() - frame.getLong("captured_elapsed_ms");
                if (isCancelled()) return failure("cancelled");
                if (lastFrame != frame || age < 0 || age > 5000) return failure("frame_age_expired");
                return new JSONObject().put("ok", true).put("phase", result.phase.name())
                        .put("score", Double.isFinite(result.score) ? result.score : JSONObject.NULL)
                        .put("template_id", result.templateId).put("frame_id", frame.getLong("frame_id")).toString();
            } finally { bitmap.recycle(); }
        }

        public String capture() throws Exception {
            return captureInternal(false);
        }

        public String captureNative() throws Exception {
            return captureInternal(true);
        }

        private String captureInternal(boolean nativePixels) throws Exception {
            boolean waited=false;
            int captureFailures=0;
            while(true) {
                if(isCancelled())return failure("cancelled");
                if(elapsedRealtime()>=deadline)return failure("time_budget");
                String result=captureAttempt(nativePixels);
                if(GameEntryGate.RECAPTURE.equals(new JSONObject(result).optString("reason"))) {
                    lastFrame=null;
                    publish("startup_capture_retry","waiting_for_fresh_game_capture",null);
                    Thread.sleep(150);continue;
                }
                if("temporary_window_capture_error".equals(new JSONObject(result).optString("reason"))) {
                    if(++captureFailures>3)return failure("window_capture_retry_exhausted");
                    publish("capture_retry","waiting_for_fresh_game_capture",null);
                    Thread.sleep(350);continue;
                }
                if(!GameWindowState.OCCLUDED.equals(new JSONObject(result).optString("reason"))) {
                    if(waited)publish("overlay_wait_finished","game_window_available",null);
                    return result;
                }
                if(!waited)publish("overlay_wait","waiting_for_game_window",null);
                waited=true;
                Thread.sleep(300);
            }
        }

        private String captureAttempt(boolean nativePixels) throws Exception {
            requireWorker();
            if (isCancelled()) return failure("cancelled");
            if(workingEvidence!=null)workingEvidence.beforeCapture();
            if(retention!=null){
                // Reserve a conservative PNG allocation before the capture timestamp.
                // The app supports captures up to the current display geometry.
                android.util.DisplayMetrics display=service.getResources().getDisplayMetrics();
                long reserve=Math.max(16*1024*1024L,(long)display.widthPixels*display.heightPixels*5)+1024*1024L;
                retention.reserve(roundDirectory,System.currentTimeMillis(),reserve);
            }
            AtomicReference<FrameSnapshot> acquired = new AtomicReference<>();
            AtomicReference<String> error = new AtomicReference<>();
            AtomicBoolean abandoned = new AtomicBoolean();
            CountDownLatch latch = new CountDownLatch(1);
            long[] metadata = new long[2];
            main.post(() -> {
                try {
                if (isCancelled()) { error.set("cancelled"); latch.countDown(); return; }
                ForegroundSnapshot facts = service.foregroundSnapshot();
                String entryRejection = checkEntry(facts);
                if (entryRejection != null) {
                    error.set(entryRejection); latch.countDown(); return;
                }
                if(facts.windowState.occluded) {error.set(GameWindowState.OCCLUDED);latch.countDown();return;}
                metadata[0] = SystemClock.elapsedRealtime();
                metadata[1] = facts.generation;
                FrameSource.Callback captureCallback = new FrameSource.Callback() {
                    @Override public void onFrame(FrameSnapshot frame) {
                        try {
                            synchronized (acquired) {
                                if (abandoned.get() || isCancelled()) { frame.close(); return; }
                                String rejection = checkEntry(service.foregroundSnapshot());
                                if (rejection == null) rejection = entryGate.checkCapture(metadata[0], metadata[1]);
                                if (rejection != null) {
                                    error.set(rejection);
                                    frame.close();
                                } else acquired.set(frame);
                            }
                        } catch (RuntimeException failure) {
                            frame.close();
                            error.set("capture_callback_error:" + failure.getClass().getSimpleName());
                        } finally { latch.countDown(); }
                    }
                    @Override public void onFailure(String message) {
                        try {
                            ForegroundSnapshot facts=service.foregroundSnapshot();
                            String rejection=checkEntry(facts);
                            error.set(rejection!=null && !GameEntryGate.WAITING.equals(rejection)?rejection
                                    :entryGate.captureFailureReason(message,facts.foregroundPackage,facts.generation,facts.departureEpoch));
                        } catch(RuntimeException failure) {
                            error.set("capture_callback_error:"+failure.getClass().getSimpleName());
                        } finally { latch.countDown(); }
                    }
                };
                if (nativePixels) service.requestNativeFrame(captureCallback);
                else service.requestFrame(captureCallback);
                } catch (Throwable failure) {
                    error.set("capture_request_error:" + failure.getClass().getSimpleName());
                    latch.countDown();
                }
            });
            if (!latch.await(8, TimeUnit.SECONDS)) {
                synchronized (acquired) {
                    abandoned.set(true);
                    FrameSnapshot late = acquired.getAndSet(null);
                    if (late != null) late.close();
                }
                return failure("capture_timeout");
            }
            FrameSnapshot frame = acquired.getAndSet(null);
            if (frame == null) return failure(error.get() == null ? "cancelled" : error.get());
            try {
                if (isCancelled()) return failure("cancelled");
                if ((nativePixels ? !NativeFrameCoordinates.valid(frame.width(), frame.height(), frame.sourceWidth(), frame.sourceHeight())
                        : frame.width() != 1280 || frame.height() != 720) ||
                        !supported(frame.sourceWidth(), frame.sourceHeight())) return failure("unsupported_frame_size");
                long sequence = ++frameSequence;
                if (sequence-roundFrameStartedSequence > 1600) { cancel("frame_budget"); return failure("frame_budget"); }
                File frameDirectory=new File(retention==null?directory:roundDirectory,"frames");
                if(!frameDirectory.isDirectory() && !frameDirectory.mkdirs())throw new IllegalStateException("frame_directory");
                File png = new File(frameDirectory, String.format(Locale.ROOT, "%05d.png", sequence));
                long encodeStarted=SystemClock.elapsedRealtime();
                try (FileOutputStream stream = new FileOutputStream(png)) {
                    OriginalPng.write(frame.bitmap(),stream);
                }
                long encodeElapsed=SystemClock.elapsedRealtime()-encodeStarted;
                File capturedPng = png;
                String evidenceCopyMode = "original";
                if (retention==null && "battle".equals(stage)) {
                    // Runtime's strict evidence gate is per round. Keep the
                    // campaign's monotonic original, then give that round an
                    // immutable exact-byte alias; never authorize a parent-directory escape.
                    File roundFrames = new File(roundDirectory, "frames");
                    if (!roundFrames.isDirectory() && !roundFrames.mkdirs())
                        throw new IllegalStateException("round_frames_directory");
                    capturedPng = new File(roundFrames, png.getName());
                    evidenceCopyMode = EvidenceFrameFiles.mirror(png,capturedPng);
                }
                JSONObject json = new JSONObject().put("ok", true).put("frame_id", sequence)
                        .put("round_index", roundIndex)
                        .put("png_path", capturedPng.getAbsolutePath())
                        .put("campaign_png_path", png.getAbsolutePath()).put("captured_elapsed_ms", metadata[0])
                        .put("evidence_copy_mode", evidenceCopyMode)
                        .put("png_encode_ms",encodeElapsed)
                        .put("capture_scope",frame.captureScope).put("capture_window_id",frame.captureWindowId)
                        .put("capture_window_bounds",new JSONArray().put(frame.captureBounds.left).put(frame.captureBounds.top)
                                .put(frame.captureBounds.width()).put(frame.captureBounds.height()))
                        .put("foreground_generation", metadata[1]).put("source_width", frame.sourceWidth())
                        .put("source_height", frame.sourceHeight())
                        .put("aspect_profile", FrameAspectProfile.classify(frame.sourceWidth(), frame.sourceHeight()))
                        .put("width", frame.width()).put("height", frame.height())
                        .put("coordinate_space", nativePixels ? "source_pixels" : "normalized_1280x720");
                save(new File(frameDirectory, String.format(Locale.ROOT, "%05d.json", sequence)), json.toString());
                String currentRejection=checkEntry(service.foregroundSnapshot());
                if(currentRejection==null)currentRejection=entryGate.checkCapture(metadata[0],metadata[1]);
                if(currentRejection!=null)return failure(currentRejection);
                lastFrame = json;
                if(workingEvidence!=null)workingEvidence.register(json);
                return json.toString();
            } finally { frame.close(); }
        }

        public String dispatch(String request) throws Exception {
            return dispatchInternal(request, false);
        }

        public String dispatchMenu(String request) throws Exception {
            return dispatchInternal(request, true);
        }

        /** Settlement taps go through their own guard: single short tap, only
         *  after a verified result, never on a live control. */
        public String dispatchSettle(String request) throws Exception {
            requireWorker();
            JSONObject plan = new JSONObject(request);
            CountDownLatch latch = new CountDownLatch(1);
            AtomicReference<String> reply = new AtomicReference<>();
            AtomicBoolean sent = new AtomicBoolean();
            AtomicBoolean abandoned = new AtomicBoolean();
            File ledger = new File(retention==null?directory:roundDirectory, "settle-inputs.jsonl");
            main.post(() -> service.withoutOverlay(release -> {
                try {
                    String rejection = validateSettle(plan);
                    if (rejection != null || abandoned.get()) {
                        reply.set(dispatchReply(false, false, rejection == null ? "settle_callback_timeout" : rejection));
                        latch.countDown(); return;
                    }
                    JSONObject frame = lastFrame;
                    GestureDescription gesture = buildGesture(plan, frame);
                    rejection = validateSettle(plan);
                    if (rejection != null || abandoned.get()) {
                        reply.set(dispatchReply(false, false, rejection == null ? "settle_callback_timeout" : rejection));
                        latch.countDown(); return;
                    }
                    append(ledger, new JSONObject().put("event", "prepared")
                            .put("elapsed_ms", elapsedRealtime()).put("request", plan).toString());
                    rejection = validateSettle(plan);
                    if (rejection != null || abandoned.get()) {
                        reply.set(dispatchReply(false, false, rejection == null ? "settle_callback_timeout" : rejection));
                        latch.countDown(); return;
                    }
                    boolean accepted = service.dispatchGesture(gesture, new AccessibilityService.GestureResultCallback() {
                        @Override public void onCompleted(GestureDescription description) {
                            release.run();
                            reply.set(dispatchReply(true, true, "gesture_completed_unverified")); latch.countDown();
                        }
                        @Override public void onCancelled(GestureDescription description) {
                            release.run();
                            reply.set(dispatchReply(true, false, "gesture_cancelled")); latch.countDown();
                        }
                    }, main);
                    sent.set(accepted);
                    if (accepted) {
                        consumedFrame = frame.optLong("frame_id");
                        settleClicks++;
                        service.noteFloatingAction("settle");
                    }
                    else { reply.set(dispatchReply(false, false, "platform_rejected")); latch.countDown(); }
                    append(ledger, new JSONObject().put("event", "dispatch")
                            .put("accepted", accepted).put("input_count", settleClicks)
                            .put("round_index", roundIndex).put("campaign_input_count", totalInputs())
                            .put("request", plan).toString());
                } catch (Throwable error) {
                    reply.set(dispatchReply(sent.get(), false, "settle_boundary_error:" + error));
                    latch.countDown();
                } finally { if(!sent.get())release.run(); }
            }));
            if (!latch.await(8, TimeUnit.SECONDS)) {
                abandoned.set(true);
                inputStatusUncertain = true;
                cancel("settle_callback_timeout");
                return dispatchReply(sent.get(), false, "settle_callback_timeout");
            }
            String value = reply.get();
            if(workingEvidence!=null)workingEvidence.select(plan.optLong("frame_id"),"settlement_before");
            if (value != null && new JSONObject(value).optBoolean("accepted")
                    && !new JSONObject(value).optBoolean("completed")) inputStatusUncertain = true;
            return value;
        }

        private String validateSettle(JSONObject plan) throws Exception {
            ForegroundSnapshot facts=service.foregroundSnapshot();
            String foreground = facts.foregroundPackage;
            long generation = facts.generation;
            String entryRejection = checkEntry(facts);
            if (entryRejection != null) return entryRejection;
            if(facts.windowState.occluded)return GameWindowState.OCCLUDED;
            if (!BattleWorkerLease.isOwnedBy(ApkBattleSession.this)) return "campaign_lease_lost";
            if (roundInputs() >= maxInputs) return "campaign_input_budget";
            String rejection=SettleDispatchGuard.validate(plan, lastFrame, consumedFrame, isCancelled(), readOnly,
                    elapsedRealtime(), deadline, settleClicks, SettleDispatchGuard.TOTAL_MAX_CLICKS,
                    new int[0][], foreground, generation);
            return rejection!=null?rejection:pathOccluded(facts,physicalPathPoints(plan,lastFrame))?GameWindowState.OCCLUDED:null;
        }

        /** The settlement loop learns the screen through the menu recogniser. */
        public String observeMenu(String request) throws Exception {
            requireWorker();
            JSONObject plan = new JSONObject(request);
            String png = plan.optString("png_path", "");
            if (png.isEmpty()) return new JSONObject().put("state", "unknown").toString();
            String assets = plan.optString("assets", "");
            File directory = assets.isEmpty() ? menuAssetsDirectory() : new File(assets);
            return Python.getInstance().getModule("apk_match_entry")
                    .callAttr("observe", png, directory.getAbsolutePath()).toString();
        }

        /** Read-only result fallback for the exact current battle capture. */
        public String observeResult(String request) throws Exception {
            requireWorker();
            JSONObject plan = new JSONObject(request);
            JSONObject frame = lastFrame;
            if (isCancelled() || !"battle".equals(stage) || frame == null)
                return failure("result_capture_unavailable");
            for (String key : new String[]{"frame_id", "captured_elapsed_ms", "foreground_generation",
                    "source_width", "source_height"}) {
                if (!(plan.opt(key) instanceof Number) || frame.getLong(key) != plan.getLong(key))
                    return failure("result_capture_mismatch");
            }
            if (!frame.getString("png_path").equals(plan.optString("png_path", "")))
                return failure("result_capture_mismatch");
            long age = elapsedRealtime() - frame.getLong("captured_elapsed_ms");
            if (age < 0 || age > 5000) return failure("result_capture_expired");
            File assets = menuAssetsDirectory();
            if (!resultAssetsPrepared) {
                // Normal entry already staged these; direct/debug entry skips
                // the menu, so stage its same immutable assets lazily once.
                if (!new File(assets, "manifest.json").isFile()) copyAssets("match-entry", assets);
                resultAssetsPrepared = true;
            }
            JSONObject observed = new JSONObject(Python.getInstance().getModule("apk_match_entry")
                    .callAttr("observe", frame.getString("png_path"), assets.getAbsolutePath(), true).toString());
            age = elapsedRealtime() - frame.getLong("captured_elapsed_ms");
            if (isCancelled() || lastFrame != frame || age < 0 || age > 5000)
                return failure("result_capture_expired");
            for (String key : new String[]{"frame_id", "captured_elapsed_ms", "foreground_generation",
                    "source_width", "source_height", "png_path"}) observed.put(key, frame.get(key));
            return observed.put("ok", true).toString();
        }

        private String dispatchInternal(String request, boolean menu) throws Exception {
            requireWorker();
            JSONObject plan = new JSONObject(request);
            CountDownLatch latch = new CountDownLatch(1);
            AtomicReference<String> reply = new AtomicReference<>();
            AtomicBoolean abandoned = new AtomicBoolean();
            AtomicBoolean sent = new AtomicBoolean();
            File ledger = new File(retention==null?directory:roundDirectory, menu ? "menu-inputs.jsonl" : "inputs.jsonl");
            main.post(() -> service.withoutOverlay(release -> {
                try {
                    String rejection = validate(plan, menu);
                    if (rejection != null || abandoned.get()) {
                        reply.set(dispatchReply(false, false, rejection == null ? "dispatch_timeout" : rejection));
                        latch.countDown(); return;
                    }
                    JSONObject frame = lastFrame;
                    GestureDescription gesture = buildGesture(plan, frame);
                    // Recheck after the foreground IPC and gesture construction, immediately before input.
                    rejection = validate(plan, menu);
                    if (rejection != null || abandoned.get()) {
                        reply.set(dispatchReply(false, false, rejection == null ? "dispatch_timeout" : rejection));
                        latch.countDown(); return;
                    }
                    append(ledger, new JSONObject().put("event", "prepared")
                            .put("elapsed_ms", elapsedRealtime()).put("request", plan)
                            .put("physical_path_points", physicalPathPoints(plan, frame)).toString());
                    // Evidence writing must not silently use up the remaining age budget.
                    rejection = validate(plan, menu);
                    if (rejection != null || abandoned.get()) {
                        reply.set(dispatchReply(false, false, rejection == null ? "dispatch_timeout" : rejection));
                        latch.countDown(); return;
                    }
                    if(menu)entryGate.sealBootstrap();
                    boolean accepted = service.dispatchGesture(gesture, new AccessibilityService.GestureResultCallback() {
                        @Override public void onCompleted(GestureDescription description) {
                            release.run();
                            reply.set(dispatchReply(true, true, "gesture_completed_unverified")); latch.countDown();
                        }
                        @Override public void onCancelled(GestureDescription description) {
                            release.run();
                            reply.set(dispatchReply(true, false, "gesture_cancelled")); latch.countDown();
                        }
                    }, main);
                    sent.set(accepted);
                    if (accepted) {
                        consumedFrame = frame.optLong("frame_id");
                        if (menu) menuInputs++; else inputs++;
                        if(!menu)service.noteFloatingAction(plan.optString("context"));
                    } else { reply.set(dispatchReply(false, false, "platform_rejected")); latch.countDown(); }
                    append(ledger, new JSONObject().put("event", "dispatch")
                            .put("accepted", accepted).put("input_count", menu ? menuInputs : inputs)
                            .put("round_index", roundIndex).put("campaign_input_count", totalInputs()).put("request", plan).toString());
                } catch (Throwable error) {
                    cancel("dispatch_boundary_error");
                    reply.set(dispatchReply(sent.get(), false,
                            "dispatch_boundary_error:" + error)); latch.countDown();
                } finally { if(!sent.get())release.run(); }
            }));
            if (!latch.await(8, TimeUnit.SECONDS)) {
                abandoned.set(true);
                inputStatusUncertain = true;
                cancel("gesture_callback_timeout_input_status_uncertain");
                // A missing callback does not prove that no input occurred.
                return dispatchReply(sent.get(), false, "gesture_callback_timeout");
            }
            String value = reply.get();
            if(workingEvidence!=null)workingEvidence.select(plan.optLong("frame_id"),menu?"menu_before":"action_before");
            if (value != null && new JSONObject(value).optBoolean("accepted")
                    && !new JSONObject(value).optBoolean("completed")) inputStatusUncertain = true;
            return value;
        }

        private String validate(JSONObject plan, boolean menu) throws Exception {
            // Take time/cancellation snapshots after the potentially slow foreground IPC.
            ForegroundSnapshot facts=service.foregroundSnapshot();
            String foreground = facts.foregroundPackage;
            long generation = facts.generation;
            String entryRejection = checkEntry(facts);
            if(menu && startupAdmission && GameEntryGate.WAITING.equals(entryRejection))
                return GameEntryGate.RECAPTURE;
            if (entryRejection != null) return entryRejection;
            if(menu && startupAdmission && plan.has("captured_elapsed_ms") && plan.has("foreground_generation")) {
                String captureRejection=entryGate.checkCapture(plan.getLong("captured_elapsed_ms"),plan.getLong("foreground_generation"));
                if(captureRejection!=null)return captureRejection;
            }
            if(facts.windowState.occluded)return GameWindowState.OCCLUDED;
            if (!BattleWorkerLease.isOwnedBy(ApkBattleSession.this)) return "campaign_lease_lost";
            if (roundInputs() >= maxInputs) return "campaign_input_budget";
            if (menu) {
                String rejection=MenuDispatchGuard.validate(plan,lastFrame,consumedFrame,isCancelled(),readOnly,
                    elapsedRealtime(),deadline,menuInputs,stage,matchMode,foreground,generation);
                return rejection!=null?rejection:pathOccluded(facts,physicalPathPoints(plan,lastFrame))?GameWindowState.OCCLUDED:null;
            }
            if (!"battle".equals(stage)) return "not_battle_stage";
            String rejection=BattleDispatchGuard.validate(plan, lastFrame, consumedFrame, isCancelled(), readOnly,
                    elapsedRealtime(), deadline, roundInputs(), maxInputs, foreground, generation);
            return rejection!=null?rejection:pathOccluded(facts,physicalPathPoints(plan,lastFrame))?GameWindowState.OCCLUDED:null;
        }
    }

    static JSONObject runtimeOptions(JSONObject options) throws Exception {
        return MatchEntryOptions.runtimeOptions(options);
    }

    private static boolean pathOccluded(ForegroundSnapshot facts,JSONArray path) throws Exception {
        float[][] points=new float[path.length()][2];
        for(int i=0;i<path.length();i++) {
            points[i][0]=(float)path.getJSONArray(i).getDouble(0);
            points[i][1]=(float)path.getJSONArray(i).getDouble(1);
        }
        return facts.windowState.blocksPath(points);
    }

    static JSONArray physicalPathPoints(JSONObject plan, JSONObject frame) throws Exception {
        String rejection = BattleDispatchGuard.validatePath(plan, frame);
        if (rejection != null) throw new IllegalArgumentException(rejection);
        JSONArray normalized;
        if ("deploy".equals(plan.getString("context"))) {
            normalized = plan.getJSONArray("path_points");
        } else {
            normalized = new JSONArray().put(plan.getJSONArray("from"));
            if ("drag".equals(plan.getString("kind"))) normalized.put(plan.getJSONArray("to"));
        }
        boolean nativePixels = "source_pixels".equals(frame.optString("coordinate_space"));
        if (nativePixels != "source_pixels".equals(plan.optString("coordinate_space")))
            throw new IllegalArgumentException("coordinate_space_mismatch");
        double sx = nativePixels ? 1.0 : frame.getInt("source_width") / 1280.0;
        double sy = nativePixels ? 1.0 : frame.getInt("source_height") / 720.0;
        JSONArray physical = new JSONArray();
        for (int i = 0; i < normalized.length(); i++) {
            JSONArray point = normalized.getJSONArray(i);
            physical.put(new JSONArray().put(point.getDouble(0) * sx).put(point.getDouble(1) * sy));
        }
        return physical;
    }

    static GestureDescription buildGesture(JSONObject plan, JSONObject frame) throws Exception {
        JSONArray points = physicalPathPoints(plan, frame);
        Path path = new Path();
        for (int i = 0; i < points.length(); i++) {
            JSONArray point = points.getJSONArray(i);
            if (i == 0) path.moveTo((float) point.getDouble(0), (float) point.getDouble(1));
            else path.lineTo((float) point.getDouble(0), (float) point.getDouble(1));
        }
        return new GestureDescription.Builder().addStroke(
                new GestureDescription.StrokeDescription(path, 0, plan.getLong("duration_ms"))).build();
    }

    private static void requireWorker() {
        if (Looper.myLooper() == Looper.getMainLooper()) throw new IllegalStateException("blocking_bridge_on_main_thread");
    }
    private static boolean supported(int w, int h) { return FrameAspectProfile.supported(w, h); }
    private static boolean point(JSONArray a) throws Exception {
        return a.length() == 2 && Double.isFinite(a.getDouble(0)) && Double.isFinite(a.getDouble(1))
                && a.getDouble(0) > 0 && a.getDouble(0) < 1280 && a.getDouble(1) > 0 && a.getDouble(1) < 720;
    }
    private static String dispatchReply(boolean accepted, boolean completed, String reason) {
        try { return new JSONObject().put("accepted", accepted).put("completed", completed).put("reason", reason).toString(); }
        catch (Exception impossible) { throw new IllegalStateException(impossible); }
    }
    private static String failure(String reason) throws Exception { return new JSONObject().put("ok", false).put("reason", reason).toString(); }
    private File prepareCore() throws Exception {
        java.security.MessageDigest digest = java.security.MessageDigest.getInstance("SHA-256");
        try (InputStream input = service.getAssets().open("mobile-core/manifest.json")) {
            byte[] buffer = new byte[16384]; int length;
            while ((length = input.read(buffer)) != -1) digest.update(buffer, 0, length);
        }
        StringBuilder key = new StringBuilder();
        for (byte value : digest.digest()) key.append(String.format(Locale.ROOT, "%02x", value & 255));
        File core = new File(service.getFilesDir(), "embedded-core/" + key);
        // A stable content key lets another explicitly started session reuse the interpreter.
        // Refresh only from this APK's packaged assets; never from external storage.
        copyAssets("mobile-core", core);
        return core;
    }
    private void copyAssets(String path, File destination) throws Exception {
        String[] children = service.getAssets().list(path);
        if (children != null && children.length > 0) {
            if (!destination.isDirectory() && !destination.mkdirs()) throw new IllegalStateException("core_directory");
            for (String child : children) copyAssets(path + "/" + child, new File(destination, child));
        } else {
            try (InputStream input = service.getAssets().open(path); FileOutputStream output = new FileOutputStream(destination)) {
                byte[] buffer = new byte[16384]; int length;
                while ((length = input.read(buffer)) != -1) output.write(buffer, 0, length);
            }
        }
    }
    private static void save(File file, String text) throws Exception {
        try (FileOutputStream out = new FileOutputStream(file)) { out.write(text.getBytes(StandardCharsets.UTF_8)); }
    }
    private static synchronized void append(File file, String text) throws Exception {
        try (FileOutputStream out = new FileOutputStream(file, true)) { out.write((text + "\n").getBytes(StandardCharsets.UTF_8)); }
    }
}
