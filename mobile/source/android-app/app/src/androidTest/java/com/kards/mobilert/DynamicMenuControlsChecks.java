package com.kards.mobilert;

import android.content.Context;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;

/** Saved 720p failure replay through production OCR and menu recognition; no device input. */
public final class DynamicMenuControlsChecks {
    public static final class SavedBridge {
        private final JSONObject ocr;
        SavedBridge(JSONObject ocr) { this.ocr=ocr; }
        public String recognizeNativeText(String request) throws Exception {
            JSONObject result=new JSONObject(request);
            result.put("ok",true).put("items",ocr.getJSONArray("items"));
            result.put("scope",result.optString("ocr_scope"));
            return result.toString();
        }
    }
    static JSONObject run(Context test,Context target) throws Exception {
        File directory=new File(target.getFilesDir(),"dynamic-menu-probe");
        if(!directory.isDirectory() && !directory.mkdirs()) throw new IllegalStateException("menu_probe_directory");
        File source=new File(directory,"code125-home-720-review.jpg");
        NativePipelineChecks.copy(test,"dynamic-menu-probe/code125-home-720-review.jpg",source);
        File menu=new File(directory,"menu");NativePipelineChecks.copy(target,"match-entry",menu);
        if(!Python.isStarted()) Python.start(new AndroidPlatform(target));
        Python py=Python.getInstance();
        File core=new File(directory,"core");NativePipelineChecks.copy(target,"mobile-core",core);
        py.getModule("sys").get("path").callAttr("insert",0,new File(core,"src").getAbsolutePath());
        JSONObject ocr=NativeOriginalOcr.inspect(target,source,720);
        JSONObject packet=new JSONObject().put("ok",true).put("coordinate_space","source_pixels")
            .put("width",1280).put("height",720).put("source_width",1280).put("source_height",720)
            .put("frame_id",1).put("captured_elapsed_ms",0).put("foreground_generation",1).put("png_path",source.getAbsolutePath());
        JSONArray results=new JSONArray();
        for(int scenario=0;scenario<3;scenario++) {
            boolean startup=scenario==0,settlement=scenario==2;
            JSONObject currentOcr=settlement ? NativeOriginalOcr.inspectMenuRegions(target,source,
                new JSONArray("[[0,0,461,720],[768,0,512,720]]")) : ocr;
            JSONObject result=new JSONObject(py.getModule("apk_native.menu").get("NativeMenuRecognizer")
                .call(menu.getAbsolutePath(),new SavedBridge(currentOcr),startup,settlement).callAttr("observe",
                    py.getModule("cv2").callAttr("imread",source.getAbsolutePath()),
                    py.getModule("json").callAttr("loads",packet.toString())).toString());
            if(!"home".equals(result.getString("state"))) throw new IllegalStateException("dynamic_home_not_recognized");
            JSONArray bounds=result.getJSONObject("targets").getJSONArray("menu_home_start");
            if(bounds.getDouble(0)>1280*.2 || bounds.getDouble(2)<=0 || bounds.getDouble(3)<=0)
                throw new IllegalStateException("dynamic_home_target");
            if(settlement && !"menu_controls".equals(result.getJSONObject("ocr_metrics").optString("scope")))
                throw new IllegalStateException("settlement_dynamic_menu_ocr_not_reached");
            results.put(result.put("startup_test",startup).put("settlement_test",settlement));
        }
        JSONObject semantics=new JSONObject(py.getModule("apk_native.menu_dynamic_test").callAttr("run",menu.getAbsolutePath()).toString());
        if(!semantics.getBoolean("passed")) throw new IllegalStateException("dynamic_menu_semantics");
        File opening=new File(directory,"opening");NativePipelineChecks.copy(target,"mulligan-one-shot",opening);
        JSONObject controls=new JSONObject(py.getModule("apk_native.control_semantics_test").callAttr("run",opening.getAbsolutePath()).toString());
        if(!controls.getBoolean("passed")) throw new IllegalStateException("dynamic_control_semantics");
        JSONObject resultsProof=new JSONObject(py.getModule("apk_native.result_controls_test").callAttr("run").toString());
        if(!resultsProof.getBoolean("passed")) throw new IllegalStateException("dynamic_result_semantics");
        JSONObject resultProbe=new JSONObject(py.getModule("json").callAttr("dumps",
            py.getModule("apk_native.result_probe_test").callAttr("run")).toString());
        if(!resultProbe.getBoolean("passed")) throw new IllegalStateException("dynamic_result_probe");
        JSONObject turnControls=new JSONObject(py.getModule("json").callAttr("dumps",
            py.getModule("apk_native.turn_controls_test").callAttr("run")).toString());
        if(!turnControls.getBoolean("passed")) throw new IllegalStateException("dynamic_turn_controls");
        JSONObject executorReuse=new JSONObject(py.getModule("json").callAttr("dumps",
            py.getModule("apk_native.executor_reuse_test").callAttr("run")).toString());
        if(!executorReuse.getBoolean("passed")) throw new IllegalStateException("executor_reuse_checks");
        JSONObject effectCache=new JSONObject(py.getModule("json").callAttr("dumps",
            py.getModule("apk_native.effects_cache_test").callAttr("run")).toString());
        if(!effectCache.getBoolean("passed")) throw new IllegalStateException("effect_cache_checks");
        JSONObject unknownFrontline=new JSONObject(py.getModule("json").callAttr("dumps",
            py.getModule("apk_native.unknown_frontline_test").callAttr("run")).toString());
        if(!unknownFrontline.getBoolean("passed")) throw new IllegalStateException("bounded_unknown_frontline_checks");
        JSONObject frontlineTolerance=new JSONObject(py.getModule("json").callAttr("dumps",
            py.getModule("apk_native.frontline_tolerance_test").callAttr("run")).toString());
        if(!frontlineTolerance.getBoolean("passed")) throw new IllegalStateException("frontline_tolerance_checks");
        JSONObject effectPipeline=new JSONObject(py.getModule("json").callAttr("dumps",
            py.getModule("apk_native.effect_pipeline_test").callAttr("run")).toString());
        if(!effectPipeline.getBoolean("passed")) throw new IllegalStateException("effect_pipeline_checks");
        JSONObject executorEffect=new JSONObject(py.getModule("json").callAttr("dumps",
            py.getModule("apk_native.executor_effect_test").callAttr("run")).toString());
        if(!executorEffect.getBoolean("passed")) throw new IllegalStateException("executor_effect_checks");
        JSONObject turnBackend=TurnRegionChecks.run(test,target);
        JSONObject startupGate=GameEntryGateChecks.run();
        if(startupGate.getInt("failure_count")!=0)throw new IllegalStateException("startup_gate_checks");
        JSONObject departureFacts=ForegroundDepartureChecks.run();
        if(!departureFacts.getBoolean("passed"))throw new IllegalStateException("startup_departure_facts");
        JSONObject handoff=new JSONObject(py.getModule("json").callAttr("dumps",
            py.getModule("apk_native.opening_handoff_test").callAttr("run",opening.getAbsolutePath())).toString());
        if(!handoff.getBoolean("passed")) throw new IllegalStateException("dynamic_opening_handoff");
        JSONObject offers=new JSONObject(py.getModule("json").callAttr("dumps",
            py.getModule("apk_native.offer_semantics_test").callAttr("run",menu.getAbsolutePath())).toString());
        if(!offers.getBoolean("passed")) throw new IllegalStateException("dynamic_offer_semantics");
        File promotion=new File(directory,"code128-promotion-review.jpg");
        NativePipelineChecks.copy(test,"dynamic-menu-probe/code128-promotion-review.jpg",promotion);
        JSONObject offerOcr=NativeOriginalOcr.inspect(target,promotion,720);
        JSONObject offerPacket=new JSONObject(packet.toString()).put("png_path",promotion.getAbsolutePath());
        JSONObject offer=new JSONObject(py.getModule("apk_native.menu").get("NativeMenuRecognizer")
            .call(menu.getAbsolutePath(),new SavedBridge(offerOcr)).callAttr("observe",
                py.getModule("cv2").callAttr("imread",promotion.getAbsolutePath()),
                py.getModule("json").callAttr("loads",offerPacket.toString())).toString());
        java.nio.file.Files.write(new File(directory,"actual-offer-debug.json").toPath(),
            new JSONObject().put("ocr",offerOcr).put("observation",offer).toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        boolean generic="generic_popup".equals(offer.getString("state"));
        if(!generic && !"pass_popup".equals(offer.getString("state"))) throw new IllegalStateException("actual_offer_not_recognized");
        String offerAction=generic ? "menu_dismiss_generic" : "menu_dismiss_pass";
        JSONArray offerBounds=offer.getJSONObject("targets").getJSONArray(offerAction);
        JSONArray point=new JSONArray().put(offerBounds.getDouble(0)+offerBounds.getDouble(2)/2)
            .put(offerBounds.getDouble(1)+offerBounds.getDouble(3)/2);
        JSONObject plan=new JSONObject(offerPacket.toString()).put("state",offer.getString("state")).put("context",offerAction)
            .put("mode","casual").put("first_deck_selected",false).put("kind","tap").put("duration_ms",60)
            .put("target_bounds",offerBounds).put("from",point).put("to",point).put("popup_basis",offer.optString("popup_basis"));
        if(generic)plan.put("generic_popup_evidence",offer.getJSONObject("generic_popup_evidence"));
        String rejected=MenuDispatchGuard.validate(plan,offerPacket,-1,false,false,0,100000,0,"menu","casual","com.android1939.kards",1);
        if(rejected!=null) throw new IllegalStateException("actual_offer_dispatch_guard:"+rejected);
        JSONArray semanticBounds=new JSONArray(py.getModule("apk_native.menu").callAttr("semantic_offer_target",
            py.getModule("cv2").callAttr("imread",promotion.getAbsolutePath()),
            py.getModule("json").callAttr("loads",offerOcr.getJSONArray("items").toString())).toString());
        JSONArray semanticPoint=new JSONArray().put(semanticBounds.getDouble(0)+semanticBounds.getDouble(2)/2)
            .put(semanticBounds.getDouble(1)+semanticBounds.getDouble(3)/2);
        JSONObject semanticPlan=new JSONObject(plan.toString()).put("state","pass_popup").put("context","menu_dismiss_pass")
            .put("popup_basis","current_offer_title_subtitle_price").put("target_bounds",semanticBounds)
            .put("from",semanticPoint).put("to",semanticPoint);
        rejected=MenuDispatchGuard.validate(semanticPlan,offerPacket,-1,false,false,0,100000,0,"menu","casual","com.android1939.kards",1);
        if(rejected!=null)throw new IllegalStateException("actual_semantic_offer_guard:"+rejected);
        JSONObject dailyTests=new JSONObject(py.getModule("json").callAttr("dumps",
            py.getModule("apk_native.daily_semantics_test").callAttr("run",menu.getAbsolutePath())).toString());
        if(!dailyTests.getBoolean("passed"))throw new IllegalStateException("daily_semantic_tests");
        File dailyFile=new File(directory,"code129-daily-review.jpg");
        NativePipelineChecks.copy(test,"dynamic-menu-probe/code129-daily-review.jpg",dailyFile);
        JSONObject dailyOcr=NativeOriginalOcr.inspect(target,dailyFile,720);
        JSONObject dailyProof=new JSONObject(py.getModule("json").callAttr("dumps",
            py.getModule("apk_native.menu").callAttr("semantic_daily_popup",
                py.getModule("cv2").callAttr("imread",dailyFile.getAbsolutePath()),
                py.getModule("json").callAttr("loads",dailyOcr.getJSONArray("items").toString()))).toString());
        JSONArray dailyBounds=dailyProof.getJSONArray("target_bounds");
        JSONArray dailyPoint=new JSONArray().put(dailyBounds.getDouble(0)+dailyBounds.getDouble(2)/2)
            .put(dailyBounds.getDouble(1)+dailyBounds.getDouble(3)/2);
        JSONObject dailyPacket=new JSONObject(offerPacket.toString()).put("png_path",dailyFile.getAbsolutePath());
        JSONObject dailyPlan=new JSONObject(plan.toString()).put("png_path",dailyFile.getAbsolutePath()).put("state","login_popup_cleanup")
            .put("context","menu_clear_login_popup").put("login_popup_evidence",dailyProof)
            .put("target_bounds",dailyBounds).put("from",dailyPoint).put("to",dailyPoint);
        rejected=MenuDispatchGuard.validate(dailyPlan,dailyPacket,-1,false,false,0,100000,0,"menu","casual","com.android1939.kards",1);
        if(rejected!=null)throw new IllegalStateException("actual_daily_guard:"+rejected);
        JSONObject lowerDaily=new JSONObject(dailyPlan.toString());
        lowerDaily.getJSONObject("login_popup_evidence").put("buttons",new JSONArray().put(
            new JSONObject().put("score",.94).put("bounds",new JSONArray("[616,585,49,35]"))));
        rejected=MenuDispatchGuard.validate(lowerDaily,dailyPacket,-1,false,false,0,100000,0,"menu","casual","com.android1939.kards",1);
        if(rejected!=null)throw new IllegalStateException("lower_daily_guard:"+rejected);
        lowerDaily.getJSONObject("login_popup_evidence").getJSONArray("buttons").getJSONObject(0)
            .put("bounds",new JSONArray("[616,650,49,35]"));
        rejected=MenuDispatchGuard.validate(lowerDaily,dailyPacket,-1,false,false,0,100000,0,"menu","casual","com.android1939.kards",1);
        if(!"login_popup_unverified".equals(rejected))throw new IllegalStateException("overlapping_daily_guard:"+rejected);
        JSONObject closeTests=new JSONObject(py.getModule("json").callAttr("dumps",
            py.getModule("apk_native.generic_close_test").callAttr("run")).toString());
        if(!closeTests.getBoolean("passed"))throw new IllegalStateException("current_close_shape_tests");
        File starterFile=new File(directory,"code130-starter-original.png");
        NativePipelineChecks.copy(test,"dynamic-menu-probe/code130-starter-original.png",starterFile);
        JSONObject currentClose=new JSONObject(py.getModule("json").callAttr("dumps",
            py.getModule("apk_native.generic_popup").callAttr("inspect",
                py.getModule("cv2").callAttr("imread",starterFile.getAbsolutePath()),
                py.getModule("json").callAttr("loads","{}"))).toString());
        if(!"current_close_x_geometry".equals(currentClose.getString("basis")))
            throw new IllegalStateException("actual_template_free_close_missing");
        JSONArray closeBounds=currentClose.getJSONObject("close").getJSONArray("bounds");
        JSONArray closePoint=new JSONArray().put(closeBounds.getDouble(0)+closeBounds.getDouble(2)/2)
            .put(closeBounds.getDouble(1)+closeBounds.getDouble(3)/2);
        JSONObject closePacket=new JSONObject(offerPacket.toString()).put("png_path",starterFile.getAbsolutePath());
        JSONObject closePlan=new JSONObject(plan.toString()).put("png_path",starterFile.getAbsolutePath()).put("state","generic_popup")
            .put("context","menu_dismiss_generic").put("generic_popup_evidence",currentClose)
            .put("target_bounds",closeBounds).put("from",closePoint).put("to",closePoint);
        rejected=MenuDispatchGuard.validate(closePlan,closePacket,-1,false,false,0,100000,0,"menu","casual","com.android1939.kards",1);
        if(rejected!=null)throw new IllegalStateException("actual_current_close_guard:"+rejected);
        return new JSONObject().put("passed",true).put("source_kind","code125_failure_review_JPEG")
            .put("ocr",ocr).put("observations",results).put("semantic_checks",semantics).put("control_checks",controls)
            .put("result_checks",resultsProof)
            .put("periodic_result_probe_checks",resultProbe)
            .put("turn_control_checks",turnControls).put("turn_control_backend",turnBackend)
            .put("executor_reuse_checks",executorReuse)
            .put("effect_cache_checks",effectCache)
            .put("bounded_unknown_frontline_checks",unknownFrontline)
            .put("frontline_tolerance_checks",frontlineTolerance)
            .put("effect_pipeline_checks",effectPipeline)
            .put("executor_effect_checks",executorEffect)
            .put("startup_gate_checks",startupGate).put("startup_departure_checks",departureFacts)
            .put("handoff_checks",handoff)
            .put("offer_checks",offers).put("actual_offer",offer).put("actual_offer_guard_passed",true)
            .put("actual_semantic_offer_target",semanticBounds).put("actual_semantic_offer_guard_passed",true)
            .put("daily_checks",dailyTests).put("actual_daily_ocr",dailyOcr).put("actual_daily_proof",dailyProof)
            .put("actual_daily_guard_passed",true)
            .put("lower_daily_guard_passed",true).put("overlapping_daily_guard_rejected",true)
            .put("close_shape_checks",closeTests).put("actual_current_close",currentClose)
            .put("actual_current_close_guard_passed",true)
            .put("device_inputs",0).put("captures",0);
    }
}
