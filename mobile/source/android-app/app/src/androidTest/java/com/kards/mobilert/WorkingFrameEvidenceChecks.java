package com.kards.mobilert;

import android.content.Context;
import android.graphics.Bitmap;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.file.Files;

/** Real codecs and file lifetimes, independent of gameplay input. */
final class WorkingFrameEvidenceChecks {
    private static void check(JSONArray checks,String name,boolean ok) throws Exception {
        checks.put(new JSONObject().put("name",name).put("passed",ok));if(!ok)throw new IllegalStateException(name);
    }
    private static JSONObject packet(File round,int id) throws Exception {
        File png=new File(round,String.format(java.util.Locale.ROOT,"frames/%05d.png",id));png.getParentFile().mkdirs();
        Bitmap bitmap=Bitmap.createBitmap(320,180,Bitmap.Config.ARGB_8888);
        for(int y=0;y<180;y++)for(int x=0;x<320;x++)bitmap.setPixel(x,y,0xff000000|((x*13+id)&255)<<16|((y*17)&255)<<8|((x+y)&255));
        try(FileOutputStream stream=new FileOutputStream(png)){bitmap.compress(Bitmap.CompressFormat.PNG,100,stream);}
        finally{bitmap.recycle();}
        return new JSONObject().put("frame_id",id).put("png_path",png.getAbsolutePath()).put("width",320).put("height",180);
    }
    static void run(Context context,JSONArray checks) throws Exception {
        File round=Files.createTempDirectory(new File(context.getFilesDir(),"device-tests").toPath(),"working-frames-").toFile();
        WorkingFrameEvidence evidence=new WorkingFrameEvidence(round);
        JSONObject first=packet(round,1);evidence.register(first);evidence.select(1,"action_before");evidence.beginEffect(1);
        byte[] original=Files.readAllBytes(new File(first.getString("png_path")).toPath());
        for(int i=2;i<=18;i++){evidence.beforeCapture();evidence.register(packet(round,i));}
        check(checks,"pending_effect_keeps_original_before_after_seventeen_captures",java.util.Arrays.equals(original,Files.readAllBytes(new File(first.getString("png_path")).toPath())));
        evidence.endEffect(false);
        check(checks,"release_does_not_encode_in_fresh_dispatch_path",new File(first.getString("png_path")).exists() && !new File(round,"review/00001.jpg").exists());
        evidence.beforeCapture();
        check(checks,"retirement_keeps_three_original_frames",new File(round,"frames/00016.png").exists() && !new File(round,"frames/00015.png").exists());
        JSONObject meta=new JSONObject(new String(Files.readAllBytes(new File(round,"review/00001.json").toPath()),java.nio.charset.StandardCharsets.UTF_8));
        check(checks,"archive_is_labeled_review_only_full_geometry",meta.getBoolean("recognition_input")==false && meta.getInt("width")==320 && meta.getInt("height")==180);
        check(checks,"original_and_lossy_archive_have_separate_hashes",!meta.getString("source_png_sha256").equals(meta.getString("review_sha256")));
        check(checks,"ordinary_unselected_poll_frame_is_discarded",!new File(round,"review/00002.jpg").exists());
        evidence.beginEffect(18);
        for(int i=19;i<=23;i++){evidence.beforeCapture();evidence.register(packet(round,i));}
        evidence.endEffect(true);evidence.beforeCapture();
        check(checks,"unknown_effect_preserves_intermediate_review_context",new File(round,"review/00019.jpg").exists());
        evidence.finish(true);
        check(checks,"worker_finish_leaves_no_working_png",new File(round,"frames").listFiles((dir,name)->name.endsWith(".png")).length==0);
        check(checks,"final_after_and_stop_context_archived",new File(round,"review/00023.jpg").exists() && new File(round,"review/00018.jpg").exists());
        boolean refused=false;try{evidence.beginEffect(1);}catch(IllegalStateException expected){refused=true;}
        check(checks,"cannot_lease_already_retired_source",refused);
        File limit=Files.createTempDirectory(round.toPath(),"limit-").toFile();WorkingFrameEvidence capped=new WorkingFrameEvidence(limit);
        capped.register(packet(limit,1));capped.beginEffect(1);
        for(int i=2;i<=WorkingFrameEvidence.MAX_WORKING;i++){capped.beforeCapture();capped.register(packet(limit,i));}
        refused=false;try{capped.beforeCapture();}catch(IllegalStateException expected){refused=true;}
        check(checks,"oversized_pending_lease_stops_without_deleting_inputs",refused && new File(limit,"frames/00001.png").exists());
        capped.finish(true);
        File escaped=Files.createTempDirectory(context.getCacheDir().toPath(),"working-outside-").toFile();
        File keep=new File(escaped,"keep.png");Files.write(keep.toPath(),new byte[]{1,2,3});
        File linked=new File(round,"frames/00099.png");Files.createSymbolicLink(linked.toPath(),keep.toPath());
        refused=false;try{evidence.register(new JSONObject().put("frame_id",99).put("png_path",linked.getAbsolutePath()));}
        catch(IllegalArgumentException expected){refused=true;}
        check(checks,"working_source_symlink_escape_refused",refused && keep.length()==3);
        File reviewEscape=new File(round,"review/00025.jpg");Files.createSymbolicLink(reviewEscape.toPath(),keep.toPath());
        evidence.register(packet(round,25));evidence.select(25,"action_before");
        refused=false;try{evidence.finish(true);}catch(IllegalArgumentException expected){refused=true;}
        check(checks,"archive_output_symlink_cannot_overwrite_external_file",refused && keep.length()==3);
        File opening=new File(round,"single-action/2000000000000-abcdef12");opening.mkdirs();
        for(int i=1;i<=2;i++){
            JSONObject p=packet(round,30+i);File target=new File(opening,String.format(java.util.Locale.ROOT,"frame-%04d.png",i));
            Files.move(new File(p.getString("png_path")).toPath(),target.toPath());
            Files.write(new File(opening,String.format(java.util.Locale.ROOT,"frame-%04d.json",i)).toPath(),
                    new JSONObject().put("frameSequence",i).put("width",320).put("height",180).toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        }
        File summary=new File(opening,"summary.json");Files.write(summary.toPath(),"{\"active\":true}".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        refused=false;try{WorkingFrameEvidence.compactClosedOpening(round);}catch(IllegalStateException expected){refused=true;}
        check(checks,"opening_originals_are_protected_until_terminal",refused && new File(opening,"frame-0001.png").exists());
        Files.write(summary.toPath(),"{\"active\":false}".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        JSONObject compacted=WorkingFrameEvidence.compactClosedOpening(round);
        check(checks,"closed_opening_before_after_are_compacted",compacted.getInt("frames")==2 && !new File(opening,"frame-0001.png").exists() && new File(opening,"review/frame-0002.jpg").exists());
        check(checks,"opening_compaction_is_idempotent",WorkingFrameEvidence.compactClosedOpening(round).getInt("frames")==0);
    }
}
