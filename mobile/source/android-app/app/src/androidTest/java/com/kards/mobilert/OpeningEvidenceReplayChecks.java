package com.kards.mobilert;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONObject;
import org.json.JSONArray;
import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** Exact PNGs from the finished code107 live game; no capture, launch or input. */
final class OpeningEvidenceReplayChecks {
    static JSONObject run(Context assets,Context target) throws Exception {
        JSONObject manifest;
        try(InputStream in=assets.getAssets().open("opening-retention-probe/manifest.json")){
            java.io.ByteArrayOutputStream buffer=new java.io.ByteArrayOutputStream();byte[] block=new byte[16384];int count;
            while((count=in.read(block))!=-1)buffer.write(block,0,count);
            manifest=new JSONObject(new String(buffer.toByteArray(),StandardCharsets.UTF_8));
        }
        File round=Files.createTempDirectory(new File(target.getFilesDir(),"device-tests").toPath(),"opening-review-replay-").toFile();
        JSONArray files=manifest.getJSONArray("files");long pngBytes=0;int pngCount=0;
        for(int i=0;i<files.length();i++){
            JSONObject spec=files.getJSONObject(i);String relative=spec.getString("file");
            if(!relative.matches("[1-9][0-9]{0,18}-[0-9a-f]{8}/(frame-[0-9]{4,}\\.(png|json)|summary\\.json)"))throw new IllegalArgumentException("replay_asset_name");
            File destination=new File(round,"single-action/"+relative);destination.getParentFile().mkdirs();
            try(InputStream in=assets.getAssets().open("opening-retention-probe/"+relative)){Files.copy(in,destination.toPath());}
            if(!hash(destination).equals(spec.getString("sha256")))throw new IllegalStateException("replay_source_hash");
            if(relative.endsWith(".png")){pngBytes+=destination.length();pngCount++;}
        }
        new WorkingFrameEvidence(round).finish(false);
        long jpegBytes=0;int compared=0;
        for(int i=0;i<files.length();i++){
            JSONObject spec=files.getJSONObject(i);String name=spec.getString("file");if(!name.endsWith(".png"))continue;
            File old=new File(round,"single-action/"+name);if(old.exists())throw new IllegalStateException("opening_png_not_retired");
            String stem=old.getName().replace(".png","");File review=new File(old.getParentFile(),"review/"+stem+".jpg");
            File metadata=new File(old.getParentFile(),"review/"+stem+".json");
            JSONObject meta=new JSONObject(new String(Files.readAllBytes(metadata.toPath()),StandardCharsets.UTF_8));
            if(!meta.getString("source_png_sha256").equals(spec.getString("sha256")) || !meta.getString("review_sha256").equals(hash(review)) || meta.getBoolean("recognition_input"))throw new IllegalStateException("opening_review_provenance");
            Bitmap bitmap=BitmapFactory.decodeFile(review.getAbsolutePath());
            if(bitmap==null)throw new IllegalStateException("opening_review_decode");
            try{if(bitmap.getWidth()!=meta.getJSONObject("source_packet").getInt("width") || bitmap.getHeight()!=meta.getJSONObject("source_packet").getInt("height"))throw new IllegalStateException("opening_geometry_changed");}
            finally{bitmap.recycle();}
            jpegBytes+=review.length();compared++;
        }
        JSONObject summary=new JSONObject(new String(Files.readAllBytes(new File(round,"screenshot-summary.json").toPath()),StandardCharsets.UTF_8));
        if(summary.getInt("opening_frames")!=pngCount || summary.getLong("opening_review_jpeg_bytes")!=jpegBytes)throw new IllegalStateException("opening_summary_count");
        return new JSONObject().put("passed",true).put("source",manifest).put("scope","saved_real_opening_postround_replay")
                .put("original_png_bytes",pngBytes).put("review_jpeg_bytes",jpegBytes).put("hashes_compared",compared)
                .put("directory",round.getAbsolutePath()).put("device_inputs",0).put("captures",0)
                .put("opponent_mulligan_wait", opponentWaitReplay(assets,target,round));
    }

    private static JSONObject opponentWaitReplay(Context assets,Context target,File directory) throws Exception {
        File source=new File(directory,"code139-frame0008-review.jpg");
        NativePipelineChecks.copy(assets,"opening-opponent-wait-probe/code139-frame0008-review.jpg",source);
        String sourceHash=hash(source);
        if(!"ff743846098fd3ec23ddfda81249c5a94b9b69df0e10a327d07f881ab7e79655".equals(sourceHash))
            throw new IllegalStateException("opponent_wait_review_hash");
        if(!Python.isStarted()) Python.start(new AndroidPlatform(target));
        File core=new File(directory,"opponent-wait-core");
        NativePipelineChecks.copy(target,"mobile-core",core);
        Python.getInstance().getModule("sys").get("path").callAttr("insert",0,new File(core,"src").getAbsolutePath());
        Bitmap bitmap=BitmapFactory.decodeFile(source.getAbsolutePath());
        if(bitmap==null)throw new IllegalStateException("opponent_wait_review_decode");
        MulliganRecognizer.Result result;
        try { result=new NativeOpeningInspector(target).inspectSaved(bitmap,source); }
        finally { bitmap.recycle(); }
        if(result.phase!=MulliganRecognizer.Phase.WAITING_OPPONENT_MULLIGAN || result.score<.90)
            throw new IllegalStateException("opponent_wait_review_unrecognized:"+result.phase+":"+result.reason);
        JSONObject semantics=new JSONObject(Python.getInstance().getModule("json").callAttr("dumps",
                Python.getInstance().getModule("apk_native.opening_wait_test").callAttr("run",
                    new File(target.getFilesDir(),"native-opening-component").getAbsolutePath())).toString());
        if(!semantics.getBoolean("passed"))throw new IllegalStateException("opponent_wait_semantics");
        return new JSONObject().put("passed",true).put("phase",result.phase.name())
                .put("reason",result.reason).put("score",result.score).put("review_jpeg_sha256",sourceHash)
                .put("semantics",semantics)
                .put("source_kind","archived_review_jpeg_not_original_png").put("device_inputs",0).put("captures",0);
    }

    private static String hash(File file) throws Exception {
        byte[] bytes=MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file.toPath()));StringBuilder hex=new StringBuilder();
        for(byte b:bytes)hex.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return hex.toString();
    }
}
