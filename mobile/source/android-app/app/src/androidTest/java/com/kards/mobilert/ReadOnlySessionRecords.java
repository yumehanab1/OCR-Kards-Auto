package com.kards.mobilert;

import android.content.Context;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileInputStream;
import java.io.RandomAccessFile;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** Bounded diagnostics only: no captures, game inputs, cleanup or evidence edits. */
final class ReadOnlySessionRecords {
    private static final int MAX_READ_BYTES = 2 * 1024 * 1024;
    private static final int LIST_RECORD_BYTES = 128 * 1024;
    private static final String SESSION = "[1-9][0-9]{0,18}-[0-9a-f]{8}";
    private static final String ROOT_RECORD = "(?:summary\\.json|options\\.json|bridge-events\\.jsonl|capture-retries\\.jsonl|dispatch-diagnostics\\.jsonl|retention\\.json)";
    private static final String ROUND_RECORD = "rounds/[0-9]{3,10}/(?:summary\\.json|engine\\.json|battle-summary\\.json|menu-summary\\.json|opening\\.json|settle\\.json|last-engine-event\\.json|last-menu-event\\.json|bridge-payloads\\.jsonl|inputs\\.jsonl|menu-inputs\\.jsonl|settle-inputs\\.jsonl|retention\\.json|screenshot-summary\\.json|native-(?:observation|planning|replanned|effect)-[0-9]{6,}\\.json|(?:frames|review)/[0-9]{5,}\\.json)";

    /** Separate opt-in entry: the original read()/collect() contract remains unchanged. */
    static String diagnose(Context context, String session, String path, String offset, String length) throws Exception {
        JSONObject result;
        if ("list".equals(session)) {
            if (path != null || offset != null || length != null) throw new IllegalArgumentException("list_has_no_file_range");
            result = list(context);
        } else if (path != null) {
            result = readFile(context, session, path, boundedNumber(offset, 0, Long.MAX_VALUE, "offsetBytes"),
                    (int) boundedNumber(length, 65536, MAX_READ_BYTES, "chunkBytes"));
        } else {
            if (offset != null || length != null) throw new IllegalArgumentException("range_requires_relativePath");
            result = new JSONObject(read(context, session));
            result.put("operation", "legacy_session_records");
        }
        result.put("game_inputs_by_reader", 0).put("captures_by_reader", 0)
                .put("original_evidence_writes_by_reader", 0).put("original_evidence_cleanup_by_reader", 0)
                .put("in_process_state", processState());
        return result.toString();
    }

    private static long boundedNumber(String value, long fallback, long maximum, String name) {
        if (value == null) return fallback;
        if (!value.matches("[0-9]{1,19}")) throw new IllegalArgumentException(name);
        final long parsed;
        try { parsed = Long.parseLong(value); }
        catch (NumberFormatException invalid) { throw new IllegalArgumentException(name); }
        if (parsed < 0 || parsed > maximum || ("chunkBytes".equals(name) && parsed == 0))
            throw new IllegalArgumentException(name);
        return parsed;
    }

    private static JSONObject list(Context context) throws Exception {
        File battle = new File(context.getFilesDir(), "battle");
        JSONObject result = new JSONObject().put("operation", "list_sessions").put("limit", 10)
                .put("max_read_bytes", MAX_READ_BYTES).put("summary_options_file_limit_bytes", LIST_RECORD_BYTES);
        JSONArray sessions = new JSONArray(); result.put("sessions", sessions);
        if (!battle.exists()) return result.put("battle_directory_status", "missing").put("eligible_sessions", 0);
        if (!battle.getAbsoluteFile().equals(battle.getCanonicalFile())
                && !context.getFilesDir().getCanonicalFile().equals(battle.getCanonicalFile().getParentFile()))
            throw new IllegalArgumentException("battle_directory_outside_files");
        File canonicalBattle = battle.getCanonicalFile();
        File[] children = battle.listFiles();
        if (children == null) return result.put("battle_directory_status", "unreadable").put("eligible_sessions", JSONObject.NULL);
        List<File> valid = new ArrayList<>();
        for (File item : children) if (item.getName().matches(SESSION) && item.isDirectory()
                && item.getCanonicalFile().getParentFile().equals(canonicalBattle)
                && item.getCanonicalFile().equals(new File(canonicalBattle, item.getName()))) valid.add(item);
        valid.sort(Comparator.<File, java.math.BigInteger>comparing(item ->
                new java.math.BigInteger(item.getName().split("-", 2)[0])).reversed()
                .thenComparing(File::getName, Comparator.reverseOrder()));
        result.put("battle_directory_status", "available").put("eligible_sessions", valid.size());
        int remaining = MAX_READ_BYTES;
        for (File item : valid.subList(0, Math.min(10, valid.size()))) {
            JSONObject row = new JSONObject().put("session_id", item.getName());
            for (String name : new String[]{"summary.json", "options.json"}) {
                JSONObject record = smallRecord(item.getCanonicalFile(), name, Math.min(remaining, LIST_RECORD_BYTES));
                if (record.has("read_bytes")) remaining -= record.getInt("read_bytes");
                row.put(name, record);
            }
            sessions.put(row);
        }
        return result.put("listed_sessions", sessions.length()).put("read_bytes", MAX_READ_BYTES - remaining);
    }

    private static JSONObject smallRecord(File root, String path, int budget) throws Exception {
        File source = safeFile(root, path);
        JSONObject result = new JSONObject().put("path", path);
        if (!source.exists()) return result.put("status", "missing");
        if (!source.isFile()) return result.put("status", "not_regular_file");
        long size = source.length(), modified = source.lastModified();
        result.put("bytes", size).put("last_modified_ms", modified);
        if (size > LIST_RECORD_BYTES) return result.put("status", "omitted").put("omitted", "over_128KiB_list_record_limit");
        if (size > budget) return result.put("status", "omitted").put("omitted", "over_2MiB_list_total_limit");
        byte[] raw = readRange(source, 0, (int) size);
        return result.put("status", "read").put("read_bytes", raw.length).put("sha256", hash(raw))
                .put("text", new String(raw, StandardCharsets.UTF_8))
                .put("stable_metadata", source.length() == size && source.lastModified() == modified);
    }

    private static JSONObject readFile(Context context, String session, String path, long offset, int length) throws Exception {
        if (session == null || !session.matches(SESSION)) throw new IllegalArgumentException("session_id");
        if (!(path.matches(ROOT_RECORD) || path.matches(ROUND_RECORD))) throw new IllegalArgumentException("relativePath_not_whitelisted");
        File battle = new File(context.getFilesDir(), "battle").getCanonicalFile();
        File root = new File(battle, session).getCanonicalFile();
        if (!root.getParentFile().equals(battle) || !root.equals(new File(battle, session)) || !root.isDirectory())
            throw new IllegalArgumentException("session_missing_or_linked");
        File source = safeFile(root, path);
        JSONObject result = new JSONObject().put("operation", "read_session_file").put("session_id", session)
                .put("path", path).put("offset_bytes", offset).put("requested_chunk_bytes", length)
                .put("max_chunk_bytes", MAX_READ_BYTES);
        if (!source.exists()) return result.put("status", "missing");
        if (!source.isFile()) return result.put("status", "not_regular_file");
        long size = source.length(), modified = source.lastModified();
        if (offset > size) throw new IllegalArgumentException("offset_past_eof");
        byte[] raw = readRange(source, offset, (int) Math.min(length, size - offset));
        String wholeHash = hashFile(source);
        return result.put("status", "read").put("bytes", size).put("last_modified_ms", modified)
                .put("read_bytes", raw.length).put("sha256", wholeHash).put("chunk_sha256", hash(raw))
                .put("base64", android.util.Base64.encodeToString(raw, android.util.Base64.NO_WRAP))
                .put("next_offset_bytes", offset + raw.length).put("eof", offset + raw.length == size)
                .put("stable_metadata", source.length() == size && source.lastModified() == modified);
    }

    private static File safeFile(File root, String path) throws Exception {
        File requested = new File(root, path), canonical = requested.getCanonicalFile();
        if (!requested.getAbsoluteFile().equals(canonical) || !canonical.toPath().startsWith(root.toPath()))
            throw new IllegalArgumentException("record_outside_session_or_linked");
        return canonical;
    }

    private static byte[] readRange(File file, long offset, int size) throws Exception {
        byte[] raw = new byte[size];
        try (RandomAccessFile input = new RandomAccessFile(file, "r")) { input.seek(offset); input.readFully(raw); }
        return raw;
    }

    private static String hash(byte[] raw) throws Exception {
        return hex(MessageDigest.getInstance("SHA-256").digest(raw));
    }

    private static String hashFile(File source) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (FileInputStream input = new FileInputStream(source)) {
            byte[] buffer = new byte[65536]; int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        return hex(digest.digest());
    }

    private static String hex(byte[] raw) {
        StringBuilder result = new StringBuilder(raw.length * 2);
        for (byte value : raw) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        return result.toString();
    }

    private static JSONObject processState() throws Exception {
        KardsAccessibilityService service = KardsAccessibilityService.instance();
        JSONObject result = new JSONObject().put("pid", android.os.Process.myPid())
                .put("elapsed_realtime_ms", android.os.SystemClock.elapsedRealtime())
                .put("service_connected", service != null).put("preinstrumentation_state_proven", false);
        JSONObject progress = service == null ? new JSONObject() : new JSONObject(service.battleProgressReport());
        result.put("battle_progress_report", progress).put("active_status_known", progress.opt("active") instanceof Boolean);
        // snapshot() reclaims dead owners. Inspect the fields under the same monitor instead,
        // so the diagnostics cannot release even an already terminated worker's lease.
        synchronized (BattleWorkerLease.class) {
            Field owner = BattleWorkerLease.class.getDeclaredField("owner");
            Field session = BattleWorkerLease.class.getDeclaredField("ownerSessionId");
            Field worker = BattleWorkerLease.class.getDeclaredField("worker");
            owner.setAccessible(true); session.setAccessible(true); worker.setAccessible(true);
            Object token = owner.get(null); Thread thread = (Thread) worker.get(null);
            result.put("worker_lease", new JSONObject().put("owned", token != null)
                    .put("session_id", session.get(null)).put("worker_name", thread == null ? "" : thread.getName())
                    .put("worker_state", token == null ? "NONE" : thread == null ? "UNBOUND" : thread.getState().name())
                    .put("inspection_mutated_lease", false));
        }
        return result;
    }

    static String read(Context context, String session) throws Exception {
        if (session==null || !session.matches("[0-9]+-[a-z0-9]+")) throw new IllegalArgumentException("session_id");
        File root = new File(context.getFilesDir(), "battle/"+session).getCanonicalFile();
        File battle = new File(context.getFilesDir(), "battle").getCanonicalFile();
        if (!root.getParentFile().equals(battle) || !root.isDirectory()) throw new IllegalArgumentException("session_missing");
        JSONArray records = new JSONArray();
        collect(root, root, records, 0);
        return new JSONObject().put("session_id", session).put("game_inputs_by_reader", 0)
            .put("captures_by_reader", 0).put("records", records).toString();
    }
    static void collect(File root, File current, JSONArray records, int depth) throws Exception {
        if (depth>3) return;
        File[] files=current.listFiles();
        if (files==null) return;
        java.util.Arrays.sort(files, java.util.Comparator.comparing(File::getName));
        for (File file: files) {
            File canonical=file.getCanonicalFile();
            if (!canonical.toPath().startsWith(root.toPath())) continue;
            if(file.isDirectory()) { collect(root,file,records,depth+1); continue; }
            boolean review = file.getParentFile().getName().equals("review") &&
                (file.getName().equals("00011.jpg") || file.getName().equals("00026.jpg"));
            if(!(file.getName().endsWith(".json") || file.getName().endsWith(".jsonl") || review)) continue;
            if (records.length()>=80) throw new IllegalStateException("too_many_records");
            long size=file.length();
            JSONObject record=new JSONObject().put("path",root.toPath().relativize(file.toPath()).toString()).put("bytes",size);
            if(size<=512*1024 && review) record.put("image_base64",android.util.Base64.encodeToString(Files.readAllBytes(file.toPath()),android.util.Base64.NO_WRAP));
            else if(size<=512*1024) record.put("text",new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8));
            else record.put("omitted","over_512KiB");
            records.put(record);
        }
    }
}
