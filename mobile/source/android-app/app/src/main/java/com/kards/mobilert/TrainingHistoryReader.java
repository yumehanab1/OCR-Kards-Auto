package com.kards.mobilert;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Reads one latest campaign summary for the panel; never edits evidence or opens event logs. */
public final class TrainingHistoryReader {
    private static final Pattern SESSION_NAME = Pattern.compile("([1-9][0-9]{0,18})-[0-9a-f]{8}");
    private static final int MAX_SUMMARY_BYTES = 2 * 1024 * 1024;

    private TrainingHistoryReader() { }

    /** Call off the main thread. The result is intended for TrainingPanelState.fromSaved(). */
    public static String readLatest(File battleDirectory) {
        if (battleDirectory == null) return "{}";
        File latest = null;
        long latestTimestamp = -1;
        try {
            File canonicalRoot = battleDirectory.getCanonicalFile();
            File[] sessions = battleDirectory.listFiles();
            if (sessions == null) return "{}";
            for (File session : sessions) {
                if (!session.isDirectory()) continue;
                Matcher match = SESSION_NAME.matcher(session.getName());
                if (!match.matches()) continue;
                final long timestamp;
                try { timestamp = Long.parseLong(match.group(1)); }
                catch (NumberFormatException invalidTimestamp) { continue; }
                // Ignore a directory link outside this campaign root.
                if (!canonicalRoot.equals(session.getCanonicalFile().getParentFile())) continue;
                if (latest == null || timestamp > latestTimestamp
                        || (timestamp == latestTimestamp && session.getName().compareTo(latest.getName()) > 0)) {
                    latest = session;
                    latestTimestamp = timestamp;
                }
            }
        } catch (Exception unavailable) {
            return latest == null ? "{}" : interrupted(latest.getName());
        }
        if (latest == null) return "{}";
        // Once a latest session exists, missing/broken evidence must not reveal an older outcome.
        try {
            File summary = new File(latest, "summary.json");
            if (!summary.isFile() || summary.length() > MAX_SUMMARY_BYTES
                    || !latest.getCanonicalFile().equals(summary.getCanonicalFile().getParentFile())) {
                return interrupted(latest.getName());
            }
            String report = readBounded(summary);
            JSONObject parsed = new JSONObject(report);
            Object id = parsed.opt("session_id");
            Object active = parsed.opt("active");
            Object event = parsed.opt("event");
            if (!latest.getName().equals(id) || !(active instanceof Boolean) || !(event instanceof String)
                    || !isCampaignEvent((String) event)) return interrupted(latest.getName());
            return report;
        } catch (Exception invalidSummary) {
            return interrupted(latest.getName());
        }
    }

    private static boolean isCampaignEvent(String event) {
        return "armed".equals(event) || "engine".equals(event)
                || "stopping".equals(event) || "finished".equals(event);
    }

    private static String readBounded(File summary) throws Exception {
        try (FileInputStream input = new FileInputStream(summary);
             ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int count;
            int total = 0;
            while ((count = input.read(buffer)) != -1) {
                total += count;
                if (total > MAX_SUMMARY_BYTES) throw new IllegalStateException("summary_too_large");
                output.write(buffer, 0, count);
            }
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private static String interrupted(String id) {
        // The id was validated above. No durations, actions or results are invented here.
        return "{\"session_id\":\"" + id + "\",\"active\":true,\"event\":\"history_incomplete\"}";
    }
}
