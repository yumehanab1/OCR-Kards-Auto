package com.kards.mobilert;

import android.content.Context;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/** Bounded diagnostics only: no captures, game inputs, cleanup or evidence edits. */
final class ReadOnlySessionRecords {
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
