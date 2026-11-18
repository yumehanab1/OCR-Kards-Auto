package com.kards.mobilert;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;
import java.util.zip.CRC32;
import org.json.JSONArray;

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
    private JSONObject deckDispatch;
    private long deckBefore=-1, deckFirstAfter=-1, deckLatest=-1, deckObserved=-1;
    private String deckObservedState="";
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
        if (deckBefore>=0 && id>deckBefore) {
            if (deckFirstAfter<0) deckFirstAfter=id;
            deckLatest=id;
        }
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

    /** No image I/O: called on the worker only after an actual or uncertain submission. */
    void beginDeckSelection(long id, JSONObject dispatch) {
        if (!frames.containsKey(id)) throw new IllegalStateException("menu_dispatch_source_missing");
        deckBefore=id;
        deckDispatch=dispatch;
        deckFirstAfter=deckLatest=deckObserved=-1;
        deckObservedState="";
    }

    void observeDeckSelection(long id, String state, boolean confirmed) {
        if (deckBefore<0 || id!=deckLatest || id<=deckBefore) return;
        deckObserved=id;
        deckObservedState=state;
        if (confirmed && "deck_ready".equals(state)) clearDeckSelection();
    }

    private void clearDeckSelection() {
        deckBefore=deckFirstAfter=deckLatest=deckObserved=-1;
        deckDispatch=null;
        deckObservedState="";
    }

    /** Archive only at terminal cleanup; never copy or hash a live tap source. */
    void finishDeckSelection(String sessionId, int roundIndex, String reason) {
        if (deckBefore<0) return;
        File directory=new File(round,"failed-menu-sources");
        try {
            checkedOutput(directory);
            if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("menu_evidence_directory");
            JSONArray originals=new JSONArray();
            retainDeckFrame(directory,originals,deckBefore,"before");
            if (deckLatest==deckFirstAfter) retainDeckFrame(directory,originals,deckFirstAfter,"first_after_and_latest");
            else {
                retainDeckFrame(directory,originals,deckFirstAfter,"first_after");
                retainDeckFrame(directory,originals,deckLatest,"latest");
            }
            boolean complete=true;
            for (int i=0;i<originals.length();i++) complete &= !originals.getJSONObject(i).has("error");
            writeMenuEvidence(directory,new JSONObject().put("schema",1).put("session_id",sessionId)
                    .put("round_index",roundIndex).put("outcome",complete?"unconfirmed":"evidence_error").put("stop_reason",reason)
                    .put("action","menu_select_deck").put("dispatch",deckDispatch)
                    .put("before_frame_id",deckBefore).put("first_after_frame_id",deckFirstAfter)
                    .put("latest_frame_id",deckLatest).put("last_observed_frame_id",deckObserved)
                    .put("last_observed_state",deckObservedState).put("originals",originals));
        } catch (Exception error) {
            // Taking evidence must not change the menu outcome or block normal cleanup.
            android.util.Log.w("KardsRetention","Cannot retain deck selection evidence",error);
            try { writeMenuEvidence(directory,new JSONObject().put("schema",1).put("session_id",sessionId)
                    .put("round_index",roundIndex).put("outcome","evidence_error").put("stop_reason",reason)
                    .put("dispatch",deckDispatch).put("before_frame_id",deckBefore).put("error",error.toString())); }
            catch (Exception unavailable) { android.util.Log.w("KardsRetention","Cannot write menu evidence error",unavailable); }
        } finally { clearDeckSelection(); }
    }

    private void retainDeckFrame(File directory, JSONArray originals, long id, String role) {
        if (id<0) return;
        try { copyDeckFrame(directory,originals,id,role); }
        catch (Exception error) {
            android.util.Log.w("KardsRetention","Cannot retain menu frame "+id,error);
            try { originals.put(new JSONObject().put("role",role).put("frame_id",id)
                    .put("png_crc_iend_valid",false).put("error",error.toString())); }
            catch (Exception unavailable) { android.util.Log.w("KardsRetention","Cannot record menu frame error",unavailable); }
        }
    }

    private void copyDeckFrame(File directory, JSONArray originals, long id, String role) throws Exception {
        // The frame is a member of this round's immutable registered working set.
        JSONObject packet=frames.get(id);
        if (packet==null) throw new IOException("menu_pinned_frame_missing");
        File png=source(packet), retained=new File(directory,png.getName());
        checkedOutput(retained);
        String sha=pngHash(png,packet.getInt("width"),packet.getInt("height"));
        // Allow normal retirement to finish its sidecar/JPEG using the old path.
        // The mirror uses an inode alias when possible, an exact-byte copy otherwise.
        String mode=EvidenceFrameFiles.mirror(png,retained);
        if (!sha.equals(hash(retained))) {
            Files.deleteIfExists(retained.toPath());
            throw new IOException("menu_source_copy_mismatch");
        }
        originals.put(new JSONObject().put("role",role).put("png",retained.getName()).put("sha256",sha)
                .put("bytes",retained.length()).put("copy_mode",mode).put("png_crc_iend_valid",true)
                .put("source_packet",packet));
    }

    private static void writeMenuEvidence(File directory, JSONObject json) throws Exception {
        checkedOutput(directory);
        File manifest=new File(directory,"manifest.json");checkedOutput(manifest);
        Files.write(manifest.toPath(),json.toString().getBytes(StandardCharsets.UTF_8));
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
            if (!all && (i >= ids.size()-RECENT || effect.contains(id)
                    || id==deckBefore || id==deckFirstAfter || id==deckLatest)) continue;
            JSONObject packet = frames.get(id);
            File png = source(packet);
            Set<String> reasons = selected.get(id);
            boolean failedEffect=reasons!=null && reasons.contains("unknown_or_failed_effect_context");
            if (reasons != null) archive(packet, png, reasons);
            else discarded++;
            // Unknown effects need the exact recognition bytes for a later
            // source-paired replay. JPEG review is explicitly not that proof.
            if(failedEffect) {
                File originals=new File(round,"failed-effect-sources");checkedOutput(originals);
                if(!originals.isDirectory() && !originals.mkdirs())throw new IllegalStateException("failed_effect_directory");
                File retained=new File(originals,png.getName());checkedOutput(retained);
                if(!retained.exists())Files.copy(png.toPath(),retained.toPath());
                if(!hash(retained).equals(hash(png)))throw new IllegalStateException("failed_effect_source_copy");
            }
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
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        try (BufferedInputStream input=new BufferedInputStream(Files.newInputStream(file.toPath()))) {
            byte[] buffer=new byte[65536];
            for (int n;(n=input.read(buffer))!=-1;) digest.update(buffer,0,n);
        }
        return hex(digest.digest());
    }

    private static String pngHash(File file, int width, int height) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        try (DataInputStream in=new DataInputStream(new java.security.DigestInputStream(
                new BufferedInputStream(Files.newInputStream(file.toPath())),digest))) {
            if (in.readLong()!=0x89504E470D0A1A0AL) throw new IOException("menu_png_signature");
            byte[] type=new byte[4], buffer=new byte[65536];
            boolean header=false, pixels=false;
            while (true) {
                int size=in.readInt();in.readFully(type);
                if (size<0 || size>file.length()) throw new IOException("menu_png_chunk_size");
                String name=new String(type,StandardCharsets.US_ASCII);
                CRC32 crc=new CRC32();crc.update(type);
                if (!header && !"IHDR".equals(name)) throw new IOException("menu_png_missing_header");
                if ("IHDR".equals(name)) {
                    if (header || size!=13) throw new IOException("menu_png_header");
                    in.readFully(buffer,0,size);crc.update(buffer,0,size);
                    java.nio.ByteBuffer dims=java.nio.ByteBuffer.wrap(buffer);
                    if (dims.getInt()!=width || dims.getInt()!=height) throw new IOException("menu_png_geometry");
                    header=true;
                } else {
                    pixels|="IDAT".equals(name) && size>0;
                    for (int left=size;left>0;) {
                        int n=Math.min(left,buffer.length);
                        in.readFully(buffer,0,n);crc.update(buffer,0,n);left-=n;
                    }
                }
                if (in.readInt()!=(int)crc.getValue()) throw new IOException("menu_png_crc");
                if ("IEND".equals(name)) {
                    if (size!=0 || !pixels || in.read()!=-1) throw new IOException("menu_png_end");
                    return hex(digest.digest());
                }
            }
        }
    }

    private static String hex(byte[] digest) {
        StringBuilder hex = new StringBuilder(64);
        for (byte b : digest) { hex.append(Character.forDigit((b>>>4)&15,16));hex.append(Character.forDigit(b&15,16)); }
        return hex.toString();
    }
}
