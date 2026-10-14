package com.kards.mobilert;

import android.app.Activity;
import android.app.Application;
import android.app.Instrumentation;
import android.content.ComponentName;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.view.ViewParent;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Iterator;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Platform-only tests: saved PNGs, the prototype Activity, and optional read-only capture. */
public final class DeviceRegressionInstrumentation extends Instrumentation {
    private final JSONArray cases = new JSONArray();
    private final JSONObject report = new JSONObject();
    private Bundle arguments;
    private File outputDirectory;
    private MainActivity activity;
    private int failures;
    private int skipped;

    @Override
    public void onCreate(Bundle suppliedArguments) {
        super.onCreate(suppliedArguments);
        arguments = suppliedArguments == null ? new Bundle() : new Bundle(suppliedArguments);
        start();
    }

    @Override
    public void onStart() {
        long started = System.currentTimeMillis();
        Bundle result = new Bundle();
        try {
            outputDirectory = new File(getTargetContext().getFilesDir(), "device-tests");
            require(outputDirectory.isDirectory() || outputDirectory.mkdirs(), "Cannot create report directory");
            File[] previousReports = outputDirectory.listFiles((dir, name) -> name.matches("[a-z0-9_.-]+\\.json"));
            require(previousReports != null, "Cannot inspect previous test output");
            for (File previous : previousReports) require(previous.delete(), "Cannot remove stale test report");
            report.put("suite", "android-platform-read-only-regression-v1");
            report.put("run_id", arguments.getString("runId", "manual"));
            report.put("started_at_ms", started);
            report.put("input_count", 0);
            report.put("touch_count", 0);
            report.put("kards_launch_count", 0);
            report.put("ui_automation_used", false);
            report.put("live_frame_mode", arguments.getString("liveFrame", "auto"));
            android.content.pm.PackageInfo packageInfo = getTargetContext().getPackageManager()
                    .getPackageInfo(getTargetContext().getPackageName(), 0);
            report.put("app_version", packageInfo.versionName);
            report.put("app_version_code", packageInfo.getLongVersionCode());
            report.put("cases", cases);
            if ("true".equals(arguments.getString("releaseSmokeOnly", "false"))) {
                runCase("evidence_retention", item -> item.put("checks", EvidenceRetentionChecks.run(getTargetContext())));
                runCase("floating_status", item -> item.put("checks", FloatingControlChecks.model()));
                runCase("activity_result_lifecycle", this::testActivityLifecycle);
                runCase("native_saved_pipeline", item -> item.put("checks", NativePipelineChecks.run(getContext(),getTargetContext())));
                runCase("opening_evidence_replay", item -> item.put("checks", OpeningEvidenceReplayChecks.run(getContext(),getTargetContext())));
                runCase("aspect_16_9_replay", item -> item.put("checks", Aspect169ReplayChecks.run(getContext(),getTargetContext())));
            } else if ("true".equals(arguments.getString("openingEvidenceOnly", "false"))) {
                runCase("opening_evidence_replay", item -> item.put("checks", OpeningEvidenceReplayChecks.run(getContext(),getTargetContext())));
            } else if ("true".equals(arguments.getString("specialSkinsOnly", "false"))) {
                runCase("special_skins", item -> item.put("checks", SpecialSkinsChecks.run(getContext(),getTargetContext())));
            } else if ("true".equals(arguments.getString("floatingGameOnly", "false"))) {
                getUiAutomation(android.app.UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
                report.put("ui_automation_used",true);
                runCase("floating_game_foreground", item -> item.put("checks", FloatingControlChecks.gameForeground(this)));
            } else if ("true".equals(arguments.getString("floatingControlOnly", "false"))) {
                getUiAutomation(android.app.UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
                report.put("ui_automation_used",true);
                startPrototypeActivity();
                runCase("floating_status", item -> item.put("checks", FloatingControlChecks.model()));
                runCase("floating_platform", item -> item.put("checks", FloatingControlChecks.platform(this)));
            } else if ("true".equals(arguments.getString("nativePipelineOnly", "false"))) {
                runCase("native_saved_pipeline", item -> item.put("checks", NativePipelineChecks.run(getContext(), getTargetContext())));
            } else if ("true".equals(arguments.getString("nativeOcrOnly", "false"))) {
                runCase("native_saved_ocr", item -> item.put("checks", NativeOcrChecks.run(getContext(), getTargetContext())));
            } else {
            runCase("evidence_retention", item -> item.put("checks", EvidenceRetentionChecks.run(getTargetContext())));
            runCase("floating_status", item -> item.put("checks", FloatingControlChecks.model()));
            runCase("evidence_frame_mirror", item -> item.put("checks", EvidenceFrameFilesChecks.run(getTargetContext())));
            runCase("native_campaign_ledger", item -> item.put("checks", NativeCampaignLedgerChecks.run(getContext())));
            runCase("saved_frame_replay", this::testSavedFrames);
            runCase("activity_result_lifecycle", this::testActivityLifecycle);
            runCase("training_panel_state", item -> {
                JSONObject checks = TrainingPanelStateChecks.run();
                item.put("checks", checks);
                require(checks.getInt("failure_count") == 0, "Training panel state checks failed");
            });
            runCase("training_history_reader", item -> {
                JSONObject checks = TrainingHistoryReaderChecks.run(new File(outputDirectory, "history-reader"));
                item.put("checks", checks);
                require(checks.getInt("failure_count") == 0, "Training history checks failed");
            });
            runCase("training_dashboard_controls", item -> {
                startPrototypeActivity();
                onMain(() -> {
                    try {
                        JSONObject checks = TrainingDashboardChecks.run(activity);
                        item.put("checks", checks);
                        require(checks.getInt("failure_count") == 0, "Training dashboard checks failed");
                    } catch (Exception error) {
                        throw new AssertionError("Training dashboard checks could not complete", error);
                    }
                });
            });
            runCase("observation_loop_generation", this::testLoopGeneration);
            runCase("mulligan_session_guards", item -> {
                JSONObject checks = MulliganSessionChecks.run(getTargetContext());
                item.put("checks", checks);
                require(checks.getInt("failure_count") == 0, "Mulligan session guard checks failed");
            });
            runCase("battle_worker_lease", item -> {
                JSONObject checks = BattleWorkerLeaseChecks.run();
                item.put("checks", checks);
                require(checks.getInt("failure_count") == 0, "Battle process worker lease checks failed");
            });
            runCase("battle_dispatch_guards", item -> {
                JSONObject checks = BattleDispatchGuardChecks.run();
                item.put("checks", checks);
                require(checks.getInt("failure_count") == 0, "Battle final dispatch guard checks failed");
            });
            runCase("game_entry_guards", item -> {
                JSONObject checks = GameEntryGateChecks.run();
                item.put("checks", checks);
                require(checks.getInt("failure_count") == 0, "Game entry guard checks failed");
            });
            runCase("match_entry_options", item -> {
                JSONObject checks = MatchEntryOptionsChecks.run();
                item.put("checks", checks);
                require(checks.getInt("failure_count") == 0, "Match entry option checks failed");
                JSONObject campaignChecks = MatchCampaignPlanChecks.run();
                item.put("campaign_checks", campaignChecks);
                require(campaignChecks.getInt("failure_count") == 0, "Match campaign plan checks failed");
                JSONObject progressChecks = BattleProgressReportChecks.run();
                item.put("progress_checks", progressChecks);
                require(progressChecks.getInt("failure_count") == 0, "Battle progress report checks failed");
            });
            runCase("menu_dispatch_guards", item -> {
                JSONObject checks = MenuDispatchGuardChecks.run();
                item.put("checks", checks);
                require(checks.getInt("failure_count") == 0, "Menu dispatch guard checks failed");
            });
            runCase("settle_dispatch_guards", item -> {
                JSONObject checks = SettleDispatchGuardChecks.run();
                item.put("checks", checks);
                require(checks.getInt("failure_count") == 0, "Settle dispatch guard checks failed");
            });
            runCase("match_entry_saved_frames", item -> {
                JSONObject checks = MatchEntryChecks.run(getContext(), getTargetContext());
                item.put("checks", checks);
                require(checks.getBoolean("passed") && checks.getInt("device_inputs") == 0,
                        "Saved menu replay checks failed or reported device inputs");
            });
            runCase("mulligan_recognizer_replay", item -> {
                JSONObject checks = MulliganRecognizerChecks.run(getContext());
                item.put("checks", checks);
                require(checks.getInt("failure_count") == 0, "Mulligan recognizer checks failed");
            });
            runCase("live_frame", this::testLiveFrame);
            runCase("embedded_mobile_core", item -> {
                JSONObject checks = EmbeddedCoreChecks.run(getContext(), getTargetContext());
                item.put("checks", checks);
                require(checks.getInt("failure_count") == 0, "Embedded mobile core checks failed");
            });
            }
        } catch (Throwable error) {
            failures++;
            put(report, "suite_error", error.toString());
        } finally {
            if (activity != null) {
                try {
                    onMain(() -> activity.finish());
                    waitForIdleSync();
                } catch (Throwable error) {
                    failures++;
                    put(report, "cleanup_error", error.toString());
                }
            }
            put(report, "completed_at_ms", System.currentTimeMillis());
            put(report, "duration_ms", System.currentTimeMillis() - started);
            put(report, "status", failures == 0 ? "passed" : "failed");
            put(report, "failure_count", failures);
            put(report, "skipped_count", skipped);
            try {
                write(new File(outputDirectory, "report.json"), report.toString(2));
                result.putString("report", "files/device-tests/report.json");
            } catch (Throwable error) {
                failures++;
                result.putString("report_error", error.toString());
            }
            result.putString("stream", "\nDevice regression " + (failures == 0 ? "PASSED" : "FAILED")
                    + "; failures=" + failures + "; skipped=" + skipped + "\n");
            result.putString("status", failures == 0 ? "passed" : "failed");
            if("true".equals(arguments.getString("exportReport", "false"))) {
                String encoded=android.util.Base64.encodeToString(report.toString().getBytes(StandardCharsets.UTF_8),android.util.Base64.NO_WRAP);
                int chunks=0;
                for(int offset=0;offset<encoded.length();offset+=32000){
                    Bundle chunk=new Bundle();chunk.putString("report_chunk",encoded.substring(offset,Math.min(encoded.length(),offset+32000)));
                    sendStatus(0,chunk);chunks++;
                }
                result.putInt("report_chunk_count",chunks);
            }
            finish(failures == 0 ? Activity.RESULT_OK : Activity.RESULT_CANCELED, result);
        }
    }

    private interface TestCase { void run(JSONObject result) throws Exception; }

    // Assertions must reach the instrumentation thread so failures still produce report.json.
    private void onMain(Runnable action) {
        AtomicReference<Throwable> error = new AtomicReference<>();
        super.runOnMainSync(() -> {
            try { action.run(); } catch (Throwable failure) { error.set(failure); }
        });
        if (error.get() != null) throw new AssertionError("Main-thread test failed", error.get());
    }

    private void runCase(String name, TestCase test) {
        JSONObject result = new JSONObject();
        put(result, "name", name);
        cases.put(result);
        try {
            test.run(result);
            if (!result.has("status")) result.put("status", "passed");
            if ("skipped".equals(result.getString("status"))) skipped++;
        } catch (Throwable error) {
            failures++;
            put(result, "status", "failed");
            put(result, "error", error.toString());
        }
        Bundle progress = new Bundle();
        progress.putString("stream", name + ": " + result.optString("status") + "\n");
        sendStatus(0, progress);
    }

    private void testSavedFrames(JSONObject result) throws Exception {
        byte[] manifestBytes = asset("replay/manifest.json");
        JSONObject manifest = new JSONObject(new String(manifestBytes, StandardCharsets.UTF_8));
        JSONArray fixtures = manifest.getJSONArray("fixtures");
        require(fixtures.length() == 6, "Expected exactly six saved frames");
        result.put("manifest_sha256", sha256(manifestBytes));
        JSONArray frames = new JSONArray();
        result.put("frames", frames);
        int frameFailures = 0;
        for (int index = 0; index < fixtures.length(); index++) {
            JSONObject fixture = fixtures.getJSONObject(index);
            JSONObject frameResult = new JSONObject();
            frames.put(frameResult);
            String label = fixture.getString("label");
            frameResult.put("label", label);
            try {
                require(label.matches("[a-z0-9_]+"), "Unsafe fixture label");
                String assetPath = fixture.getString("asset");
                require(assetPath.equals("replay/" + label + ".png"), "Unexpected fixture asset path");
                byte[] png = asset(assetPath);
                String pngHash = sha256(png);
                require(pngHash.equalsIgnoreCase(fixture.getString("sha256")), "PNG SHA256 mismatch");
                frameResult.put("png_sha256", pngHash);
                String firstJson = analyze(png, assetPath);
                String secondJson = analyze(png, assetPath);
                write(new File(outputDirectory, label + ".json"), firstJson);
                write(new File(outputDirectory, label + ".repeat.json"), secondJson);
                JSONObject first = new JSONObject(firstJson);
                JSONObject second = new JSONObject(secondJson);
                assertObservation(first, fixture.getString("expected_state"),
                        fixture.getInt("source_width"), fixture.getInt("source_height"));
                assertObservation(second, fixture.getString("expected_state"),
                        fixture.getInt("source_width"), fixture.getInt("source_height"));
                require(assetPath.equals(first.getJSONObject("diagnostics").getString("source")),
                        "Replay source was not preserved");
                String firstSignature = signature(first);
                String secondSignature = signature(second);
                require(firstSignature.equals(secondSignature), "Repeated replay signature changed");
                File saved = FrameReplay.writeResult(getTargetContext(), firstJson);
                require(firstJson.equals(new String(readFile(saved), StandardCharsets.UTF_8)),
                        "FrameReplay.writeResult did not preserve JSON");
                frameResult.put("state", first.getString("state"));
                frameResult.put("signature", firstSignature);
                frameResult.put("repeat_signature", secondSignature);
                frameResult.put("status", "passed");
            } catch (Throwable error) {
                frameFailures++;
                frameResult.put("status", "failed");
                frameResult.put("error", error.toString());
            }
        }
        result.put("frame_count", fixtures.length());
        result.put("passed_frames", fixtures.length() - frameFailures);
        require(frameFailures == 0, frameFailures + " saved frame(s) failed");
    }

    private String analyze(byte[] png, String source) {
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inScaled = false;
        Bitmap bitmap = BitmapFactory.decodeByteArray(png, 0, png.length, options);
        require(bitmap != null, "PNG decode failed");
        String json = FrameReplay.analyze(bitmap, source, new ReadOnlyMobileCore());
        require(bitmap.isRecycled(), "Replay must release the decoded Bitmap");
        return json;
    }

    private static void assertObservation(JSONObject observation, String expectedState,
                                          int sourceWidth, int sourceHeight) throws Exception {
        require(observation.get("schema_version") instanceof Number
                && observation.getInt("schema_version") == 1, "Schema version must be numeric 1");
        if (expectedState != null) require(expectedState.equals(observation.getString("state")), "Unexpected state");
        require(Boolean.FALSE.equals(observation.get("action_authorized")), "Action was authorized");
        JSONObject frame = observation.getJSONObject("frame");
        require(frame.getInt("width") == 1280 && frame.getInt("height") == 720, "Normalized size mismatch");
        require(frame.getInt("source_width") == sourceWidth && frame.getInt("source_height") == sourceHeight,
                "Source size mismatch");
        require(frame.getLong("captured_at_ms") > 0 && frame.getLong("age_ms") >= 0, "Invalid frame time");
        JSONObject stability = observation.getJSONObject("stability");
        require(Boolean.FALSE.equals(stability.get("stable")), "Single frame was marked stable");
        require(stability.getInt("sample_count") == 1 && stability.isNull("motion_fraction"), "Invalid single-frame stability");
        JSONObject frontline = observation.getJSONObject("frontline");
        require("unknown".equals(frontline.getString("owner")), "Frontline owner must remain unknown");
        require(frontline.isNull("line_y") && frontline.isNull("line_score")
                && frontline.isNull("front_cards_confirmed"), "Unconfirmed frontline facts became known");
        require(observation.isNull("hq"), "HQ must remain unknown");
        require(observation.getJSONArray("units").length() == 0
                && observation.getJSONArray("enemy_support").length() == 0
                && observation.getJSONArray("enemy_front").length() == 0, "Unconfirmed unit facts became known");
        JSONObject guard = observation.getJSONObject("guard");
        require("unknown".equals(guard.getString("status")) && Boolean.FALSE.equals(guard.get("complete")),
                "Guard status must remain incomplete and unknown");
        JSONObject diagnostics = observation.getJSONObject("diagnostics");
        require("read_only".equals(diagnostics.getString("executor_mode")), "Executor must remain read-only");
        require(Boolean.FALSE.equals(diagnostics.get("normalization_rejected")), "Known source size was rejected");
        require(diagnostics.getInt("candidate_count") == diagnostics.getJSONArray("candidates").length(),
                "Candidate count mismatch");
    }

    private void testActivityLifecycle(JSONObject result) throws Exception {
        File png = new File(outputDirectory, "activity-replay.png");
        try (FileOutputStream stream = new FileOutputStream(png)) {
            stream.write(asset("replay/game_opening.png"));
        }
        startPrototypeActivity();
        AtomicReference<String> replayText = new AtomicReference<>();
        onMain(() -> {
            activity.onActivityResult(4101, Activity.RESULT_OK, new Intent().setData(Uri.fromFile(png)));
            TextView status = activity.findViewById(android.R.id.message);
            require(status != null, "Result TextView is missing android.R.id.message");
            String text = status.getText().toString();
            require(text.contains("回放结果") && text.contains("IN_GAME"), "Activity did not display saved replay result");
            require(hasScrollParent(status), "Replay result is not inside a ScrollView");
            replayText.set(text);
            callActivityOnResume(activity);
            require(text.equals(status.getText().toString()), "onResume overwrote replay result");
        });
        result.put("on_resume_preserves_result", true);
        onMain(() -> {
            activity.onActivityResult(4101, Activity.RESULT_CANCELED, null);
            callActivityOnResume(activity);
            TextView status = activity.findViewById(android.R.id.message);
            require(replayText.get().equals(status.getText().toString()), "Cancelling the picker lost the result");
        });
        result.put("picker_cancel_preserves_result", true);
        File invalid = new File(outputDirectory, "invalid.png");
        write(invalid, "not a PNG");
        onMain(() -> {
            activity.onActivityResult(4101, Activity.RESULT_OK, new Intent().setData(Uri.fromFile(invalid)));
            TextView status = activity.findViewById(android.R.id.message);
            String failure = status.getText().toString();
            require(failure.contains("回放失败") && failure.contains("有效 PNG"), "Invalid PNG was not rejected");
            callActivityOnResume(activity);
            require(failure.equals(status.getText().toString()), "onResume hid the replay error");
            activity.onActivityResult(4101, Activity.RESULT_OK, new Intent().setData(Uri.fromFile(png)));
            require(replayText.get().equals(status.getText().toString()), "Valid replay did not recover after failure");
        });
        result.put("invalid_png_rejected_and_error_preserved", true);
        Application application = (Application) getTargetContext().getApplicationContext();
        MainActivity original = activity;
        CountDownLatch resumed = new CountDownLatch(1);
        AtomicReference<MainActivity> replacement = new AtomicReference<>();
        Application.ActivityLifecycleCallbacks callbacks = new Application.ActivityLifecycleCallbacks() {
            @Override public void onActivityCreated(Activity candidate, Bundle state) { }
            @Override public void onActivityStarted(Activity candidate) { }
            @Override public void onActivityResumed(Activity candidate) {
                if (candidate instanceof MainActivity && candidate != original) {
                    replacement.set((MainActivity) candidate);
                    resumed.countDown();
                }
            }
            @Override public void onActivityPaused(Activity candidate) { }
            @Override public void onActivityStopped(Activity candidate) { }
            @Override public void onActivitySaveInstanceState(Activity candidate, Bundle state) { }
            @Override public void onActivityDestroyed(Activity candidate) { }
        };
        application.registerActivityLifecycleCallbacks(callbacks);
        try {
            onMain(original::recreate);
            require(resumed.await(15, TimeUnit.SECONDS), "Activity recreation did not resume within 15 seconds");
            activity = replacement.get();
            waitForIdleSync();
            onMain(() -> {
                TextView status = activity.findViewById(android.R.id.message);
                require(status != null && replayText.get().equals(status.getText().toString()),
                        "Activity recreation lost the replay result");
            });
            result.put("recreation_preserves_result", true);
        } finally {
            application.unregisterActivityLifecycleCallbacks(callbacks);
            if (replacement.get() != null) activity = replacement.get();
        }
        result.put("replay_state", "IN_GAME");
    }

    private void startPrototypeActivity() {
        if (activity != null && !activity.isDestroyed()) return;
        Intent intent = new Intent(getTargetContext(), MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        activity = (MainActivity) startActivitySync(intent);
        waitForIdleSync();
    }

    private static boolean hasScrollParent(TextView status) {
        ViewParent parent = status.getParent();
        while (parent != null) {
            if (parent instanceof ScrollView) return true;
            parent = parent.getParent();
        }
        return false;
    }

    private void testLoopGeneration(JSONObject result) throws Exception {
        result.put("screenshot_pacer_checks", ScreenshotRequestPacerChecks.runChecks());
        List<FrameSource.Callback> pending = new ArrayList<>();
        int[] observations = {0};
        int[] outputs = {0};
        int[] errors = {0};
        FrameSource source = pending::add;
        MobileCore core = frame -> {
            observations[0]++;
            return BoardObservation.unknown("synthetic generation regression");
        };
        ReadOnlyObservationLoop loop = new ReadOnlyObservationLoop(source, core, 250,
                json -> outputs[0]++, message -> errors[0]++);
        Bitmap oldBitmap = Bitmap.createBitmap(1280, 720, Bitmap.Config.ARGB_8888);
        Bitmap currentBitmap = Bitmap.createBitmap(1280, 720, Bitmap.Config.ARGB_8888);
        try {
            onMain(loop::start);
            waitForIdleSync();
            onMain(() -> {
                require(pending.size() == 1, "Initial capture missing");
                loop.stop();
                loop.start();
            });
            waitForIdleSync();
            onMain(() -> {
                require(pending.size() == 2, "Restart capture missing");
                pending.get(0).onFrame(new FrameSnapshot(oldBitmap, System.currentTimeMillis()));
                require(oldBitmap.isRecycled(), "Stale generation Bitmap was not closed");
                require(observations[0] == 0 && outputs[0] == 0, "Stale generation reached observer");
            });
            Thread.sleep(350);
            onMain(() -> {
                require(pending.size() == 2, "Stale callback released or rescheduled the pending new capture");
                pending.get(1).onFrame(new FrameSnapshot(currentBitmap, System.currentTimeMillis()));
                require(currentBitmap.isRecycled(), "Current generation Bitmap was not closed");
                require(observations[0] == 1 && outputs[0] == 1, "Current generation was not observed exactly once");
                loop.stop();
                loop.start();
            });
            waitForIdleSync();
            onMain(() -> {
                require(pending.size() == 3, "Third capture missing");
                loop.stop();
                pending.get(2).onFailure("late failure after stop");
                require(errors[0] == 0, "Stopped generation published a late failure");
            });
            Thread.sleep(350);
            onMain(() -> require(pending.size() == 3 && !loop.isRunning(), "Stopped loop scheduled more work"));
        } finally {
            onMain(loop::stop);
            if (!oldBitmap.isRecycled()) oldBitmap.recycle();
            if (!currentBitmap.isRecycled()) currentBitmap.recycle();
        }
        int[] nullFailures = {0};
        int[] nullOutputs = {0};
        ReadOnlyObservationLoop unavailable = new ReadOnlyObservationLoop(null, core, 250,
                json -> nullOutputs[0]++,
                message -> nullFailures[0]++);
        try {
            onMain(unavailable::start);
            waitForIdleSync();
            Thread.sleep(350);
            onMain(() -> require(!unavailable.isRunning() && nullFailures[0] == 1 && nullOutputs[0] == 0,
                    "Null source must fail once and stop"));
        } finally {
            onMain(unavailable::stop);
        }
        result.put("stale_frame_closed", true);
        result.put("stale_frame_observed", false);
        result.put("new_pending_capture_preserved", true);
        result.put("late_failure_ignored", true);
        result.put("null_source_stops", true);
    }

    private void testLiveFrame(JSONObject result) throws Exception {
        String mode = arguments.getString("liveFrame", "auto");
        require("auto".equals(mode) || "required".equals(mode) || "skip".equals(mode), "Unknown liveFrame mode");
        if ("skip".equals(mode)) {
            result.put("status", "skipped");
            result.put("reason", "Live screenshot explicitly disabled");
            return;
        }
        String enabled = Settings.Secure.getString(getTargetContext().getContentResolver(),
                Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        ComponentName expected = new ComponentName(getTargetContext(), KardsAccessibilityService.class);
        boolean authorized = false;
        if (enabled != null) {
            for (String component : enabled.split(":")) {
                if (expected.equals(ComponentName.unflattenFromString(component))) authorized = true;
            }
        }
        result.put("service_authorized", authorized);
        if (!authorized && "auto".equals(mode)) {
            result.put("status", "skipped");
            result.put("reason", "Accessibility service is not authorized; no settings were changed");
            return;
        }
        require(authorized, "Live frame requires the existing accessibility authorization");
        startPrototypeActivity();
        Bundle waiting = new Bundle();
        waiting.putString("stream", "WAITING_FOR_ACCESSIBILITY_SERVICE\n");
        sendStatus(0, waiting);
        AtomicReference<KardsAccessibilityService> connected = new AtomicReference<>();
        long deadline = System.currentTimeMillis() + 30000;
        do {
            onMain(() -> connected.set(KardsAccessibilityService.instance()));
            if (connected.get() != null) break;
            Thread.sleep(100);
        } while (System.currentTimeMillis() < deadline);
        require(connected.get() != null, "Authorized service did not connect within 30 seconds");
        AtomicReference<Boolean> focused = new AtomicReference<>(false);
        long focusDeadline = System.currentTimeMillis() + 5000;
        do {
            onMain(() -> focused.set(activity.hasWindowFocus()
                    && activity.getWindow().getDecorView().isShown()));
            if (focused.get()) break;
            Thread.sleep(100);
        } while (System.currentTimeMillis() < focusDeadline);
        require(focused.get(), "Prototype window is not visible and focused");
        result.put("prototype_window_focused", true);
        AtomicReference<String> json = new AtomicReference<>();
        AtomicReference<String> failure = new AtomicReference<>();
        JSONArray attempts = new JSONArray();
        result.put("capture_attempts", attempts);
        for (int index = 1; index <= 6 && json.get() == null; index++) {
          Thread.sleep(1000); // Allow compositor updates and honor the screenshot rate limit.
          final int attemptIndex = index;
          JSONObject attempt = new JSONObject();
          attempts.put(attempt);
          CountDownLatch captured = new CountDownLatch(1);
          onMain(() -> connected.get().requestFrame(new FrameSource.Callback() {
            @Override public void onFrame(FrameSnapshot snapshot) {
                try {
                    require(snapshot.bitmap().getConfig() == Bitmap.Config.ARGB_8888,
                            "Live capture is not an ARGB_8888 software Bitmap");
                    Bitmap bitmap = snapshot.bitmap();
                    int min = 255, max = 0, samples = 0, bright = 0;
                    for (int y = 0; y < bitmap.getHeight(); y += 8) {
                        for (int x = 0; x < bitmap.getWidth(); x += 8) {
                            int pixel = bitmap.getPixel(x, y);
                            int luminance = (((pixel >> 16) & 255) + ((pixel >> 8) & 255) + (pixel & 255)) / 3;
                            min = Math.min(min, luminance);
                            max = Math.max(max, luminance);
                            if (luminance > 180) bright++;
                            samples++;
                        }
                    }
                    boolean visible = max - min > 40 && bright > samples / 2;
                    attempt.put("min_luma", min).put("max_luma", max)
                            .put("bright_fraction", bright / (double) samples).put("visible", visible);
                    String name = visible ? "live-frame.png" : "live-frame-rejected-" + attemptIndex + ".png";
                    try (FileOutputStream stream = new FileOutputStream(new File(outputDirectory, name))) {
                        require(snapshot.bitmap().compress(Bitmap.CompressFormat.PNG, 100, stream),
                                "Could not save live frame evidence");
                    }
                    if (!visible) {
                        failure.set("Blank or non-prototype screenshot");
                        return;
                    }
                    BoardObservation observation = new ReadOnlyMobileCore().observe(snapshot);
                    json.set(BoardObservationJson.toJson(observation, snapshot, System.currentTimeMillis()));
                    failure.set(null);
                } catch (Throwable error) {
                    failure.set(error.toString());
                    put(attempt, "error", error.toString());
                } finally {
                    snapshot.close();
                    captured.countDown();
                }
            }
            @Override public void onFailure(String message) {
                failure.set(message);
                put(attempt, "error", message);
                captured.countDown();
            }
          }));
          require(captured.await(15, TimeUnit.SECONDS), "requestFrame callback timed out");
        }
        require(failure.get() == null && json.get() != null, "Live frame failed: " + failure.get());
        write(new File(outputDirectory, "live-frame.json"), json.get());
        JSONObject observation = new JSONObject(json.get());
        assertObservation(observation, "NON_GAME", 1920, 1080);
        result.put("frame", observation.getJSONObject("frame"));
        result.put("state", observation.getString("state"));
        result.put("action_authorized", observation.getBoolean("action_authorized"));
        result.put("foreground", MainActivity.class.getName());
        testScreenshotBurst(connected.get(), result);
    }

    private void testScreenshotBurst(KardsAccessibilityService service, JSONObject result) throws Exception {
        CountDownLatch complete = new CountDownLatch(3);
        List<String> failures = java.util.Collections.synchronizedList(new ArrayList<>());
        java.util.concurrent.atomic.AtomicInteger freshFrames = new java.util.concurrent.atomic.AtomicInteger();
        long requestedAt = System.currentTimeMillis();
        onMain(() -> {
            for (int i = 0; i < 3; i++) {
                service.requestFrame(new FrameSource.Callback() {
                    @Override public void onFrame(FrameSnapshot snapshot) {
                        try {
                            require(snapshot.isUsable() && snapshot.width() == 1280 && snapshot.height() == 720,
                                    "Burst returned an unusable frame");
                            require(snapshot.capturedAtMillis() >= requestedAt
                                            && System.currentTimeMillis() - snapshot.capturedAtMillis() <= 3000,
                                    "Burst frame lost its conservative request age");
                            freshFrames.incrementAndGet();
                        } catch (Throwable error) {
                            failures.add(error.toString());
                        } finally { snapshot.close(); complete.countDown(); }
                    }
                    @Override public void onFailure(String message) {
                        failures.add(message); complete.countDown();
                    }
                });
            }
        });
        require(complete.await(8, TimeUnit.SECONDS), "Screenshot burst callbacks timed out");
        require(failures.isEmpty() && freshFrames.get() == 3, "Screenshot burst failed: " + failures);
        result.put("burst_fresh_frames", freshFrames.get());
        result.put("burst_inputs", 0);
        result.put("burst_elapsed_ms", System.currentTimeMillis() - requestedAt);
    }

    private byte[] asset(String path) throws Exception {
        try (InputStream stream = getContext().getAssets().open(path)) { return read(stream); }
    }

    private static byte[] readFile(File file) throws Exception {
        try (InputStream stream = new FileInputStream(file)) { return read(stream); }
    }

    private static byte[] read(InputStream stream) throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int length;
        while ((length = stream.read(buffer)) != -1) output.write(buffer, 0, length);
        return output.toByteArray();
    }

    private static void write(File file, String value) throws Exception {
        try (FileOutputStream stream = new FileOutputStream(file)) {
            stream.write(value.getBytes(StandardCharsets.UTF_8));
        }
    }

    private static String signature(JSONObject value) throws Exception {
        JSONObject copy = new JSONObject(value.toString());
        copy.getJSONObject("frame").remove("captured_at_ms");
        return sha256(canonical(copy).getBytes(StandardCharsets.UTF_8));
    }

    private static String canonical(Object value) throws Exception {
        if (value instanceof JSONObject) {
            JSONObject object = (JSONObject) value;
            List<String> keys = new ArrayList<>();
            Iterator<String> iterator = object.keys();
            while (iterator.hasNext()) keys.add(iterator.next());
            Collections.sort(keys);
            StringBuilder result = new StringBuilder("{");
            for (String key : keys) {
                if (result.length() > 1) result.append(',');
                result.append(JSONObject.quote(key)).append(':').append(canonical(object.get(key)));
            }
            return result.append('}').toString();
        }
        if (value instanceof JSONArray) {
            JSONArray array = (JSONArray) value;
            StringBuilder result = new StringBuilder("[");
            for (int index = 0; index < array.length(); index++) {
                if (index > 0) result.append(',');
                result.append(canonical(array.get(index)));
            }
            return result.append(']').toString();
        }
        return value instanceof String ? JSONObject.quote((String) value) : String.valueOf(value);
    }

    private static String sha256(byte[] bytes) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);
        StringBuilder result = new StringBuilder();
        for (byte value : digest) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 0xff));
        return result.toString();
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void put(JSONObject object, String key, Object value) {
        try { object.put(key, value); } catch (org.json.JSONException ignored) { }
    }
}
