package com.kards.mobilert;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.UUID;

/** Creates isolated fake history files only. No real campaign, service or game access. */
public final class TrainingHistoryReaderChecks {
    private static final String LIVE20_ID = "1791275132134-5c00b730";
    private final JSONArray checks = new JSONArray();
    private int failures;
    private final File scratch;

    private TrainingHistoryReaderChecks(File parent) throws Exception {
        scratch = new File(parent, "history-reader-" + UUID.randomUUID());
        if (!scratch.mkdirs()) throw new IllegalStateException("Cannot create isolated history fixtures");
    }

    public static JSONObject run(File scratchDirectory) throws Exception {
        return run(scratchDirectory, null);
    }

    /** Host checks may supply the actual live20 file; device checks use its exact UI field projection. */
    public static JSONObject run(File scratchDirectory, String originalLive20Report) throws Exception {
        if (scratchDirectory == null) throw new IllegalArgumentException("scratchDirectory required");
        TrainingHistoryReaderChecks test = new TrainingHistoryReaderChecks(scratchDirectory);
        String live20 = originalLive20Report == null ? live20Projection() : originalLive20Report;
        test.emptyAndInvalidDirectories();
        test.latestSessionOwnsOutcome(live20);
        test.invalidLatestSummary(live20);
        test.numericOrderingAndSizeLimit();
        return new JSONObject().put("checks", test.checks).put("check_count", test.checks.length())
                .put("test_count", test.checks.length()).put("failure_count", test.failures)
                .put("device_inputs", 0).put("uses_real_service", false)
                .put("scratch_directory", test.scratch.getAbsolutePath())
                .put("original_live20_report_supplied", originalLive20Report != null);
    }

    private void emptyAndInvalidDirectories() throws Exception {
        check("null_root_has_no_history", "{}".equals(TrainingHistoryReader.readLatest(null)));
        File missing = new File(scratch, "missing");
        check("reader_does_not_create_a_missing_history_directory",
                "{}".equals(TrainingHistoryReader.readLatest(missing)) && !missing.exists());
        File empty = directory("empty");
        check("empty_history_stays_empty", "{}".equals(TrainingHistoryReader.readLatest(empty)));
        for (String name : new String[] {"invalid", "1791275132134-nohex000", "1791275132134-5C00B730",
                "0-abcdef12", "-1-abcdef12", "1791275132134-abcdef12-extra", "9999999999999999999-abcdef12"}) {
            File invalid = new File(empty, name);
            if (!invalid.mkdir()) throw new IllegalStateException("Cannot create invalid-name fixture");
        }
        write(new File(empty, "1791275132135-5c00b730"), "not a directory");
        check("illegal_session_names_and_regular_files_are_ignored", "{}".equals(TrainingHistoryReader.readLatest(empty)));
    }

    private void latestSessionOwnsOutcome(String live20) throws Exception {
        File root = directory("latest");
        File old = session(root, LIVE20_ID);
        File oldSummary = new File(old, "summary.json");
        write(oldSummary, live20);
        String report = TrainingHistoryReader.readLatest(root);
        TrainingPanelState normal = TrainingPanelState.fromSaved(report);
        check("normal_live20_summary_is_returned_byte_for_byte", report.equals(live20));
        check("normal_live20_preserves_defeat_and_confirmed_statistics", "训练结束·本局失利".equals(normal.title)
                && "9".equals(normal.actionCount) && "10".equals(normal.turnCount) && "8分59秒".equals(normal.durationDisplay));

        File newer = session(root, "1791275132135-abcdef12");
        String missing = TrainingHistoryReader.readLatest(root);
        TrainingPanelState interrupted = TrainingPanelState.fromSaved(missing);
        check("latest_missing_summary_never_falls_back_to_older_defeat",
                "1791275132135-abcdef12".equals(interrupted.sessionId)
                        && "上次运行已中断".equals(interrupted.title) && interrupted.interrupted);
        check("missing_summary_does_not_invent_metrics", "—".equals(interrupted.actionCount)
                && "—".equals(interrupted.turnCount) && "—".equals(interrupted.durationDisplay));
        check("reader_does_not_write_a_replacement_summary", !new File(newer, "summary.json").exists()
                && live20.equals(read(oldSummary)));

        // Logs may contain old counters or outcomes; they are not a summary fallback.
        write(new File(newer, "battle-events.jsonl"), live20);
        write(new File(newer, "last-engine-event.json"), live20);
        check("reader_does_not_take_statistics_from_event_logs", missing.equals(TrainingHistoryReader.readLatest(root)));
    }

    private void invalidLatestSummary(String live20) throws Exception {
        File root = directory("damaged");
        write(new File(session(root, LIVE20_ID), "summary.json"), live20);
        String newId = "1791275132136-abcdef12";
        File latest = session(root, newId);
        File summary = new File(latest, "summary.json");
        for (String damaged : new String[] {"{damaged", "null", "[]", "{}", live20,
                "{\"session_id\":\"" + newId + "\",\"active\":\"false\",\"event\":\"finished\"}"}) {
            write(summary, damaged);
            TrainingPanelState state = TrainingPanelState.fromSaved(TrainingHistoryReader.readLatest(root));
            check("latest_invalid_or_mismatched_summary_remains_interrupted_" + checks.length(),
                    newId.equals(state.sessionId) && state.interrupted
                            && "上次运行已中断".equals(state.title) && "—".equals(state.actionCount));
            check("damaged_original_is_never_modified_" + checks.length(), damaged.equals(read(summary)));
        }
        JSONObject active = new JSONObject().put("session_id", newId).put("active", true).put("event", "engine")
                .put("elapsed_ms", 12345).put("engine", new JSONObject().put("kind", "think")
                        .put("value", new JSONObject().put("turn", 2)));
        write(summary, active.toString());
        TrainingPanelState savedActive = TrainingPanelState.fromSaved(TrainingHistoryReader.readLatest(root));
        check("valid_unfinished_summary_keeps_known_progress_but_not_live_status", !savedActive.active
                && savedActive.interrupted && "2".equals(savedActive.turnCount)
                && "12秒".equals(savedActive.durationDisplay) && "—".equals(savedActive.actionCount));
    }

    private void numericOrderingAndSizeLimit() throws Exception {
        File root = directory("numeric-order");
        session(root, "9-abcdef12");
        File latest = session(root, "10-abcdef12");
        TrainingPanelState numeric = TrainingPanelState.fromSaved(TrainingHistoryReader.readLatest(root));
        check("timestamps_are_compared_numerically_not_lexicographically", "10-abcdef12".equals(numeric.sessionId));
        File oversized = new File(latest, "summary.json");
        try (FileOutputStream stream = new FileOutputStream(oversized)) {
            byte[] block = new byte[8192];
            for (int index = 0; index < 256; index++) stream.write(block);
            stream.write(1);
        }
        TrainingPanelState tooLarge = TrainingPanelState.fromSaved(TrainingHistoryReader.readLatest(root));
        check("oversized_summary_is_bounded_without_showing_older_record", tooLarge.interrupted
                && "10-abcdef12".equals(tooLarge.sessionId) && "—".equals(tooLarge.actionCount)
                && oversized.length() == 2 * 1024 * 1024 + 1);
    }

    private File directory(String name) throws Exception {
        File directory = new File(scratch, name);
        if (!directory.mkdir()) throw new IllegalStateException("Cannot create fixture directory");
        return directory;
    }

    private static File session(File root, String id) throws Exception {
        File directory = new File(root, id);
        if (!directory.mkdir()) throw new IllegalStateException("Cannot create fixture session");
        return directory;
    }

    private static void write(File file, String contents) throws Exception {
        try (FileOutputStream stream = new FileOutputStream(file)) {
            stream.write(contents.getBytes(StandardCharsets.UTF_8));
        }
    }

    private static String read(File file) throws Exception {
        return new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
    }

    private static String live20Projection() {
        // Original live20 summary SHA256 ecf49c8ccf62388c1de3236c2c3db915575b8f8540aa2acffb56dfc25b79495c.
        return "{\"event\":\"finished\",\"active\":false,\"session_id\":\"" + LIVE20_ID + "\","
                + "\"elapsed_ms\":539025,\"reason\":\"engine_finished\",\"game_inputs\":19,"
                + "\"engine\":{\"elapsed_ms\":525404,\"actions_confirmed\":9,\"end_turns_confirmed\":10,"
                + "\"engine_turns_seen\":10,\"stop_reason\":\"result_defeat\",\"result_verified\":true,"
                + "\"battle_result_reached\":true,\"full_game_passed\":false}}";
    }

    private void check(String name, boolean passed) throws Exception {
        checks.put(new JSONObject().put("name", name).put("passed", passed));
        if (!passed) failures++;
    }
}
