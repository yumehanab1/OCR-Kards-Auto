package com.kards.mobilert;

import android.content.Context;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONObject;
import org.json.JSONArray;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;

/** Historical 1280x720 pixels and generated 1920x1080 scale variants; no inputs. */
final class Aspect169ReplayChecks {
    static JSONObject run(Context test,Context target) throws Exception {
        File directory=new File(target.getFilesDir(),"aspect-169-probe");
        NativePipelineChecks.copy(test,"aspect-169-probe",directory);
        JSONArray manifest=new JSONArray(new String(Files.readAllBytes(new File(directory,"manifest.json").toPath()),StandardCharsets.UTF_8));
        for(int i=0;i<manifest.length();i++){
            JSONObject item=manifest.getJSONObject(i);byte[] bytes=Files.readAllBytes(new File(directory,item.getString("file")).toPath());
            StringBuilder hex=new StringBuilder();for(byte b:MessageDigest.getInstance("SHA-256").digest(bytes))hex.append(String.format(java.util.Locale.ROOT,"%02x",b&255));
            if(!hex.toString().equals(item.getString("sha256")))throw new IllegalStateException("aspect_fixture_hash");
        }
        File core=new File(directory,"core"),menu=new File(directory,"menu"),opening=new File(directory,"opening");
        NativePipelineChecks.copy(target,"mobile-core",core);NativePipelineChecks.copy(target,"match-entry",menu);NativePipelineChecks.copy(target,"mulligan-one-shot",opening);
        String characters;try(InputStream in=target.getAssets().open("native-ocr/characters.json")){characters=new String(in.readAllBytes(),StandardCharsets.UTF_8);}
        if(!Python.isStarted())Python.start(new AndroidPlatform(target));
        JSONObject result=new JSONObject(Python.getInstance().getModule("apk_native_bootstrap").callAttr("saved_pipeline",directory.getAbsolutePath(),core.getAbsolutePath(),menu.getAbsolutePath(),opening.getAbsolutePath(),NativeOnnxModels.get(target),characters).toString());
        JSONArray frames=result.getJSONArray("frames");if(frames.length()!=6)throw new IllegalStateException("aspect_missing_frames");
        for(int i=0;i<frames.length();i++){
            JSONObject frame=frames.getJSONObject(i),expected=manifest.getJSONObject(i);JSONArray shape=frame.getJSONArray("source_shape");
            if(shape.getInt(0)!=expected.getInt("height") || shape.getInt(1)!=expected.getInt("width"))throw new IllegalStateException("aspect_source_coordinates");
            if(!"standard_16_9".equals(FrameAspectProfile.classify(shape.getInt(1),shape.getInt(0))))throw new IllegalStateException("aspect_profile");
            if(!frame.getString("state").equals(expected.getString("expected_state")))throw new IllegalStateException("aspect_state");
            if(!"our".equals(frame.getJSONObject("scene").getJSONObject("frontline").getString("owner")))throw new IllegalStateException("aspect_frontline");
        }
        return new JSONObject().put("passed",true).put("source_kind","three_historical_normalized_frames_plus_three_generated_scales")
                .put("frame_count",6).put("sizes",new JSONArray().put("1280x720").put("1920x1080"))
                .put("device_inputs",0).put("captures",0).put("pipeline",result);
    }
}
