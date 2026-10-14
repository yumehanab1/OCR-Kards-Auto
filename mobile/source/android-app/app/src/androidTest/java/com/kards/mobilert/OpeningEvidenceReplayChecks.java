package com.kards.mobilert;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
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
                .put("directory",round.getAbsolutePath()).put("device_inputs",0).put("captures",0);
    }

    private static String hash(File file) throws Exception {
        byte[] bytes=MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file.toPath()));StringBuilder hex=new StringBuilder();
        for(byte b:bytes)hex.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return hex.toString();
    }
}
