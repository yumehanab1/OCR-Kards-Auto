package com.kards.mobilert;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

/** Lossless working set; JPEGs are review artifacts and never recognition inputs.
 * All methods run on the campaign worker. Encoding/retirement happens BEFORE
 * requesting a fresh capture, never between its timestamp and dispatch.
 */
final class WorkingFrameEvidence {
    static final int RECENT = 3, MAX_WORKING = 32, QUALITY = 78;
    private final File round, declaredRound;
    private final LinkedHashMap<Long, JSONObject> frames = new LinkedHashMap<>();
    private final Map<Long, Set<String>> selected = new LinkedHashMap<>();
    private final Set<Long> effect = new LinkedHashSet<>();
    private boolean effectOpen;
    private String lastState = "";
    private int stateSamples, registered, archived, discarded;
    private long pngBytes, reviewBytes;
    private long openingPngBytes,openingReviewBytes;
    private int openingFrames;

    WorkingFrameEvidence(File round) throws Exception {
        this.declaredRound=round.getAbsoluteFile();this.round=round.getCanonicalFile();
    }

    void register(JSONObject packet) throws Exception {
        File source = source(packet);
        if (!source.isFile()) throw new IllegalStateException("working_source_missing");
        long id = packet.getLong("frame_id");
        if (frames.containsKey(id)) throw new IllegalStateException("duplicate_working_frame");
        frames.put(id, packet);
        registered++;pngBytes+=source.length();
        if (effectOpen) effect.add(id);
    }

    void beginEffect(long id) {
        if (effectOpen || !frames.containsKey(id)) throw new IllegalStateException("invalid_effect_lease");
        effectOpen = true; effect.add(id);
    }

    void endEffect(boolean failed) {
        if (!effectOpen) throw new IllegalStateException("effect_lease_missing");
        for (long id : effect) if (failed) select(id, "unknown_or_failed_effect_context");
        if (!effect.isEmpty()) select(new ArrayList<>(effect).get(effect.size()-1), "action_after");
        effectOpen = false; effect.clear();
    }

    void select(long id, String reason) {
        if (frames.containsKey(id)) selected.computeIfAbsent(id, key -> new LinkedHashSet<>()).add(reason);
    }

    void observeState(long id,String state) {
        if(!state.equals(lastState)){lastState=state;stateSamples=0;}
        stateSamples++;
        if(state.startsWith("result_") && stateSamples<=2)select(id,state);
        if("opponent_turn".equals(state) && stateSamples<=2)select(id,"opponent_transition");
        if("unknown".equals(state) && (stateSamples<=3 || stateSamples%10==0))select(id,"unknown_screen_context");
    }

    void beforeCapture() throws Exception {
        retire(false);
        if (frames.size() >= MAX_WORKING) throw new IllegalStateException("working_frame_budget");
    }

    void finish(boolean failed) throws Exception {
        if (effectOpen) endEffect(true);
        for (long id : frames.keySet()) select(id, failed ? "session_stop_context" : "round_final_context");
        retire(true);
        JSONObject opening=compactClosedOpening(round);
        openingFrames+=opening.getInt("frames");openingPngBytes+=opening.getLong("png_bytes");openingReviewBytes+=opening.getLong("jpeg_bytes");
        JSONObject summary=new JSONObject().put("schema",1).put("original_frames_captured",registered)
                .put("original_png_bytes",pngBytes).put("review_frames",archived).put("review_jpeg_bytes",reviewBytes)
                .put("discarded_poll_frames",discarded).put("working_png_remaining",frames.size())
                .put("jpeg_quality",QUALITY).put("review_only",true)
                .put("opening_frames",openingFrames).put("opening_original_png_bytes",openingPngBytes)
                .put("opening_review_jpeg_bytes",openingReviewBytes);
        Files.write(new File(round,"screenshot-summary.json").toPath(),summary.toString().getBytes(StandardCharsets.UTF_8));
    }

    private void retire(boolean all) throws Exception {
        ArrayList<Long> ids = new ArrayList<>(frames.keySet());
        for (int i = 0; i < ids.size(); i++) {
            long id = ids.get(i);
            if (!all && (i >= ids.size()-RECENT || effect.contains(id))) continue;
            JSONObject packet = frames.get(id);
            File png = source(packet);
            Set<String> reasons = selected.get(id);
            if (reasons != null) archive(packet, png, reasons);
            else discarded++;
            JSONObject disposition=new JSONObject(packet.toString()).put("working_source_retired",true)
                    .put("review_only",true).put("review_path",reasons==null?JSONObject.NULL:new File(round,"review/"+png.getName().replace(".png",".jpg")).getAbsolutePath());
            File status=new File(png.getParentFile(),png.getName().replace(".png",".json"));
            checkedOutput(status);
            Files.write(status.toPath(),disposition.toString().getBytes(StandardCharsets.UTF_8));
            if (!Files.deleteIfExists(png.toPath())) throw new IllegalStateException("working_source_delete_failed");
            frames.remove(id); selected.remove(id);
        }
    }

    private File source(JSONObject packet) throws Exception {
        File png = new File(packet.getString("png_path"));
        File directory = new File(round, "frames");
        // Android may expose getFilesDir via /data/user/0 while canonical paths
        // resolve via /data/data. Admit only that declared round alias, then
        // verify the exact canonical frames/name target (no child symlinks).
        File declared=new File(new File(declaredRound,"frames"),png.getName());
        File canonical=new File(directory,png.getName());
        if ((!png.getAbsoluteFile().equals(declared) && !png.getAbsoluteFile().equals(canonical))
                || !png.getCanonicalFile().equals(canonical)
                || !png.getName().matches("[0-9]{5,}\\.png"))
            throw new IllegalArgumentException("working_source_outside_round");
        return canonical;
    }

    private void archive(JSONObject packet, File png, Set<String> reasons) throws Exception {
        File reviews = new File(round, "review");
        long bytes=archiveAt(packet,png,reviews,png.getName().replace(".png",""),reasons);
        archived++;reviewBytes+=bytes;
    }

    private static long archiveAt(JSONObject packet, File png, File reviews, String stem, Set<String> reasons) throws Exception {
        if (!reviews.isDirectory() && !reviews.mkdirs()) throw new IllegalStateException("review_directory");
        if (!reviews.getAbsoluteFile().equals(reviews.getCanonicalFile())) throw new IllegalStateException("review_symlink");
        File jpeg = new File(reviews, stem+".jpg");
        File metadata=new File(reviews,stem+".json");
        checkedOutput(jpeg);checkedOutput(metadata);
        BitmapFactory.Options decode = new BitmapFactory.Options(); decode.inScaled = false;
        Bitmap bitmap = BitmapFactory.decodeFile(png.getAbsolutePath(), decode);
        if (bitmap == null) throw new IllegalStateException("review_decode_failed");
        try {
            // Retain full geometry for visual review; recognition always used the PNG.
            try (FileOutputStream stream = new FileOutputStream(jpeg)) {
                if (!bitmap.compress(Bitmap.CompressFormat.JPEG, QUALITY, stream)) throw new IllegalStateException("review_encode_failed");
            }
            JSONObject meta = new JSONObject().put("schema", 1).put("purpose", "review_only")
                    .put("recognition_input", false).put("format", "jpeg").put("quality", QUALITY)
                    .put("width", bitmap.getWidth()).put("height", bitmap.getHeight())
                    .put("source_packet", packet).put("source_png_sha256", hash(png))
                    .put("review_sha256", hash(jpeg)).put("review_bytes", jpeg.length())
                    .put("reasons", new org.json.JSONArray(reasons));
            Files.write(metadata.toPath(), meta.toString().getBytes(StandardCharsets.UTF_8));
            return jpeg.length();
        } finally { bitmap.recycle(); }
    }

    /** Only terminal bounded-opening sessions are eligible. Their original PNGs
     * remain untouched while the inspector or gesture postcondition can use them.
     * The caller is the campaign worker after the round, never the main thread.
     */
    static JSONObject compactClosedOpening(File round) throws Exception {
        round=round.getCanonicalFile();File directory=new File(round,"single-action");
        int count=0;long pngBytes=0,jpegBytes=0;
        if(!directory.exists())return new JSONObject().put("frames",0).put("png_bytes",0).put("jpeg_bytes",0);
        if(!directory.getAbsoluteFile().equals(directory.getCanonicalFile()))throw new IllegalArgumentException("opening_directory_symlink");
        File[] sessions=directory.listFiles();if(sessions==null)throw new IllegalStateException("opening_directory_unreadable");
        for(File session:sessions){
            if(!session.isDirectory() || !session.getName().matches("[1-9][0-9]{0,18}-[0-9a-f]{8}"))continue;
            checkedOutput(session);
            File summary=new File(session,"summary.json");checkedOutput(summary);
            JSONObject status=new JSONObject(new String(Files.readAllBytes(summary.toPath()),StandardCharsets.UTF_8));
            if(!Boolean.FALSE.equals(status.opt("active")))throw new IllegalStateException("opening_evidence_still_active");
            File[] frames=session.listFiles((dir,name)->name.matches("frame-[0-9]{4,}\\.png"));
            if(frames==null)throw new IllegalStateException("opening_frames_unreadable");
            for(File png:frames){
                checkedOutput(png);String stem=png.getName().replace(".png","");
                File index=new File(session,stem+".json");checkedOutput(index);
                JSONObject metadata=new JSONObject(new String(Files.readAllBytes(index.toPath()),StandardCharsets.UTF_8));
                JSONObject packet=new JSONObject(metadata.toString()).put("png_path",png.getAbsolutePath()).put("source_namespace","bounded_opening");
                File reviews=new File(session,"review");
                long original=png.length();long bytes=archiveAt(packet,png,reviews,stem,java.util.Collections.singleton("closed_opening_context"));
                metadata.put("working_source_retired",true).put("review_only",true).put("review_path",new File(reviews,stem+".jpg").getAbsolutePath());
                Files.write(index.toPath(),metadata.toString().getBytes(StandardCharsets.UTF_8));
                Files.delete(png.toPath());count++;pngBytes+=original;jpegBytes+=bytes;
            }
        }
        return new JSONObject().put("frames",count).put("png_bytes",pngBytes).put("jpeg_bytes",jpegBytes);
    }

    private static void checkedOutput(File file) throws Exception {
        if(!file.getAbsoluteFile().equals(file.getCanonicalFile()))throw new IllegalArgumentException("review_output_symlink");
    }

    private static String hash(File file) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file.toPath()));
        StringBuilder hex = new StringBuilder();
        for (byte b : digest) hex.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        return hex.toString();
    }
}
