package com.kards.mobilert;

import android.content.Context;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.File;
import org.json.JSONArray;
import org.json.JSONObject;

/** Saved nonstandard-16:9 turn controls through Android ONNX; no captures/input. */
final class TurnRegionChecks {
    static JSONObject run(Context test,Context target) throws Exception {
        JSONArray checks=new JSONArray();
        for(int[] size:new int[][]{{1280,720},{1920,1080},{2304,1296},{2780,1264}}) {
            JSONArray regions=regions(size[0],size[1]);
            expect(checks,"valid_"+size[0]+"x"+size[1],null,
                TurnOcrRegions.rejection("battle",regions,size[0],size[1]));
        }
        // The production 720p ROI is rounded before the 1.8x source restore.
        expect(checks,"valid_rounded_1_8_source_roi",null,TurnOcrRegions.rejection("battle",
            new JSONArray("[[1382,414,922,778]]"),2304,1296));
        JSONArray valid=regions(1280,720);
        for(String stage:new String[]{"menu","settle","opening",""})
            expect(checks,"reject_stage_"+stage,"turn_ocr_stage_required",
                TurnOcrRegions.rejection(stage,valid,1280,720));
        for(String encoded:new String[]{"[]","[[768,230,512,432],[768,230,512,432]]"})
            expect(checks,"reject_count_"+encoded,"turn_ocr_region_count",
                TurnOcrRegions.rejection("battle",new JSONArray(encoded),1280,720));
        String[] invalid={"[[768,230,512]]","[[768,230,512,432,0]]","[null]",
            "[[-1,230,512,432]]","[[768,-1,512,432]]","[[768,230,0,432]]","[[768,230,512,0]]",
            "[[768,230,513,432]]","[[768,230,512,491]]","[[742,230,538,432]]",
            "[[768,215,512,432]]","[[768,230,512,447]]","[[768.5,230,511,432]]",
            "[[\"768\",230,512,432]]","[[768,230,2147483648,432]]"};
        for(String encoded:invalid)
            expect(checks,"reject_bounds_"+encoded,"turn_ocr_region_bounds",
                TurnOcrRegions.rejection("battle",new JSONArray(encoded),1280,720));
        expect(checks,"reject_invalid_source_size","turn_ocr_region_bounds",
            TurnOcrRegions.rejection("battle",valid,0,720));
        File directory=new File(target.getFilesDir(),"turn-controls-probe");
        if(!directory.isDirectory() && !directory.mkdirs())throw new IllegalStateException("turn_probe_directory");
        File source=new File(directory,"code133-own-turn-2304x1296-review.jpg");
        NativePipelineChecks.copy(test,"turn-controls-probe/"+source.getName(),source);
        if(!Python.isStarted())Python.start(new AndroidPlatform(target));
        JSONObject scoped=NativeOriginalOcr.inspectTurnRegions(target,source,regions(2304,1296));
        if(!"turn_controls".equals(scoped.optString("scope"))
                || !"source_pixels".equals(scoped.optString("coordinate_space"))
                || scoped.optInt("width")!=2304 || scoped.optInt("height")!=1296)
            throw new AssertionError("scoped_turn_ocr_geometry");
        checks.put("actual_android_scope_and_source_geometry");
        JSONArray items=scoped.getJSONArray("items");
        int endLabels=0,opponentLabels=0;
        for(int i=0;i<items.length();i++) {
            JSONObject item=items.getJSONObject(i);
            if(!item.optBoolean("score_available") || item.optDouble("score")<.93)continue;
            String text=item.getString("text").replace(" ","");
            if("敌方".equals(text))opponentLabels++;
            if(!"结束回合".equals(text))continue;
            JSONArray box=item.getJSONArray("box");
            double minX=Double.POSITIVE_INFINITY,minY=Double.POSITIVE_INFINITY;
            double maxX=Double.NEGATIVE_INFINITY,maxY=Double.NEGATIVE_INFINITY;
            for(int j=0;j<box.length();j++) {
                JSONArray point=box.getJSONArray(j);
                double x=point.getDouble(0),y=point.getDouble(1);
                if(!Double.isFinite(x) || !Double.isFinite(y) || x<0 || y<0 || x>2304 || y>1296)
                    throw new AssertionError("scoped_turn_label_outside_source");
                minX=Math.min(minX,x);minY=Math.min(minY,y);
                maxX=Math.max(maxX,x);maxY=Math.max(maxY,y);
            }
            if(box.length()<3 || minX<2304*.60 || minY<1296*.35 || maxY>1296*.90
                    || maxX<=minX || maxY<=minY)throw new AssertionError("scoped_turn_label_geometry");
            endLabels++;
        }
        if(endLabels!=1 || opponentLabels!=0)throw new AssertionError("scoped_current_end_turn_label");
        checks.put("actual_android_current_end_turn_label");
        JSONObject backend=new JSONObject(Python.getInstance().getModule("json").callAttr("dumps",
            Python.getInstance().getModule("apk_native.turn_ocr_scope_test").callAttr("run")).toString());
        if(!backend.getBoolean("passed"))throw new AssertionError("turn_ocr_backend_checks");
        return new JSONObject().put("passed",true).put("checks",checks)
            .put("java_turn_region_guard_checks",checks.length()-2).put("java_scoped_ocr",scoped)
            .put("python_backend",backend).put("source_fixture",source.getName()).put("device_inputs",0).put("captures",0);
    }

    private static JSONArray regions(int width,int height) throws Exception {
        int x=(int)Math.round(width*.60),y=(int)Math.round(height*.32);
        return new JSONArray().put(new JSONArray().put(x).put(y).put(width-x).put((int)Math.round(height*.60)));
    }

    private static void expect(JSONArray checks,String name,String expected,String actual) {
        if(expected==null ? actual!=null : !expected.equals(actual))throw new AssertionError(name+":"+actual);
        checks.put(name);
    }
}
