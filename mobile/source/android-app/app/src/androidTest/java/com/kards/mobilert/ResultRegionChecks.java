package com.kards.mobilert;

import android.content.Context;
import com.chaquo.python.Python;
import java.io.File;
import java.nio.charset.StandardCharsets;
import org.json.JSONArray;
import org.json.JSONObject;

/** Original phone victory PNG, scope guards and semantic negatives; no input. */
final class ResultRegionChecks {
    static JSONObject run(Context test,Context target) throws Exception {
        JSONArray valid=new JSONArray("[[973,442,834,607],[973,1062,834,177],[2085,0,695,253]]");
        if(ResultOcrRegions.rejection("battle",valid,2780,1264)!=null)throw new AssertionError("valid_result_regions");
        for(String stage:new String[]{"menu","settle","opening"})
            if(ResultOcrRegions.rejection(stage,valid,2780,1264)==null)throw new AssertionError("wrong_result_stage");
        String[] invalid={"[]","[[973,442,834,607],[973,1062,834,177]]","[[0,0,2780,1264],[973,1062,834,177],[2085,0,695,253]]",
            "[[973,442,834,607],[973,0,834,177],[2085,0,695,253]]","[[973,442,834,607],[973,1062,834,177],[0,0,695,253]]",
            "[[973,442,0,607],[973,1062,834,177],[2085,0,695,253]]","[[973,442,834,607],[973,1062,834,177],[2085,0,700,253]]"};
        for(String encoded:invalid)if(ResultOcrRegions.rejection("battle",new JSONArray(encoded),2780,1264)==null)throw new AssertionError("unbounded_result_regions");
        File directory=new File(target.getFilesDir(),"phone-result-probe");
        NativePipelineChecks.copy(test,"phone-result-probe",directory);
        File banks=new File(target.getFilesDir(),"native-pipeline-probe");
        String characters;
        try(java.io.InputStream stream=target.getAssets().open("native-ocr/characters.json")) {
            characters=new String(stream.readAllBytes(),StandardCharsets.UTF_8);
        }
        JSONObject result=new JSONObject(Python.getInstance().getModule("apk_native.result_regions_test")
            .callAttr("run_device",new File(directory,"original.png").getAbsolutePath(),new File(banks,"core").getAbsolutePath(),
                new File(banks,"menu").getAbsolutePath(),new File(banks,"opening").getAbsolutePath(),NativeOnnxModels.get(target),characters).toString());
        if(!result.getBoolean("passed"))throw new AssertionError("phone_result_replay");
        JSONObject scoped=NativeOriginalOcr.inspectResultRegions(target,new File(directory,"original.png"),valid);
        if(!"result_controls".equals(scoped.getString("scope")) || !"source_pixels".equals(scoped.getString("coordinate_space"))
                || scoped.getInt("width")!=2780 || scoped.getInt("height")!=1264)throw new AssertionError("scoped_result_ocr_geometry");
        java.util.Set<String> labels=new java.util.HashSet<>();
        JSONArray items=scoped.getJSONArray("items");
        for(int i=0;i<items.length();i++) {
            JSONObject item=items.getJSONObject(i);
            if(item.getDouble("score")>=.98)labels.add(item.getString("text").replace(" ",""));
        }
        if(!labels.containsAll(java.util.Arrays.asList("胜利","继续","查看战场")))throw new AssertionError("scoped_result_ocr_labels");
        return result.put("java_region_guard_checks",11).put("java_scoped_ocr",scoped);
    }
}
