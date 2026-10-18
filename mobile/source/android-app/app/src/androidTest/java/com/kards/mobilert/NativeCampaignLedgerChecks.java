package com.kards.mobilert;

import android.content.Context;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import org.json.JSONArray;
import org.json.JSONObject;

/** Replays unchanged real closed-match ledgers, with no game input. */
final class NativeCampaignLedgerChecks {
    private static JSONObject read(Context context,String name) throws Exception {
        try (InputStream input=context.getAssets().open("campaign-native-regression/"+name+".json")) {
            return new JSONObject(new String(TestStreams.readAll(input),StandardCharsets.UTF_8));
        }
    }
    static JSONObject run(Context context) throws Exception {
        JSONArray rows=new JSONArray();int checks=0;
        MatchCampaignPlan plan=new MatchCampaignPlan(new JSONObject().put("match_count",4),"casual");
        for (String name:new String[]{"choice","end-timeout","current-own","terminal-result"}) {
            JSONObject result=read(context,name+"-engine"),settle=read(context,name+"-settle");String original=result.toString();
            String reason=plan.continuationReason(1,result,settle,false,false,1800000,200);
            if (reason!=null || !original.equals(result.toString())) throw new IllegalStateException("real_ledger_continuation:"+name+":"+reason);checks++;
            JSONObject broken=new JSONObject(original);
            broken.getJSONArray("inputs").getJSONObject(0).getJSONObject("reply").put("completed",false);
            if (plan.continuationReason(1,broken,settle,false,false,1800000,200)==null) throw new IllegalStateException("real_ledger_incomplete_receipt");checks++;
            broken=new JSONObject(original).put("pending_end_turn_inputs",1);
            if (plan.continuationReason(1,broken,settle,false,false,1800000,200)==null) throw new IllegalStateException("real_ledger_pending_end");checks++;
            if ("current-own".equals(name) || "terminal-result".equals(name)) {
                int index=-1;
                for(int i=0;i<result.getJSONArray("hooks").length();i++)
                    if("unconfirmed".equals(result.getJSONArray("hooks").getJSONObject(i).opt("final_verification"))) index=i;
                if(index<0)throw new IllegalStateException("current_own_fixture_missing_unknown");
                for(String mutation:new String[]{"missing_outcome","reason_mismatch","frame_mismatch","unknown_counter"}) {
                    broken=new JSONObject(original);JSONObject hook=broken.getJSONArray("hooks").getJSONObject(index);
                    if("missing_outcome".equals(mutation))hook.remove("end_turn_outcome");
                    if("reason_mismatch".equals(mutation))hook.getJSONObject("end_turn_outcome").put("reason","unrecognized");
                    if("frame_mismatch".equals(mutation))hook.getJSONObject("end_turn_outcome").put("source_frame_id",-1);
                    if("unknown_counter".equals(mutation))broken.put("end_turns_unconfirmed",0);
                    if(plan.continuationReason(1,broken,settle,false,false,1800000,200)==null)throw new IllegalStateException("current_own_invalid_ledger:"+mutation);checks++;
                }
                if(!"campaign_cancelled".equals(plan.continuationReason(1,result,settle,true,false,1800000,200)))throw new IllegalStateException("current_own_cancel");checks++;
                if(!"campaign_input_status_uncertain".equals(plan.continuationReason(1,result,settle,false,true,1800000,200)))throw new IllegalStateException("current_own_uncertain");checks++;
                if(plan.continuationReason(1,new JSONObject(original).put("result_verified",false),settle,false,false,1800000,200)==null)throw new IllegalStateException("current_own_result_unverified");checks++;
                if(plan.continuationReason(1,result,new JSONObject(settle.toString()).put("final_state","unknown"),false,false,1800000,200)==null)throw new IllegalStateException("current_own_return_unverified");checks++;
                if("terminal-result".equals(name)) {
                    broken=new JSONObject(original).put("stop_reason","result_defeat");
                    if(plan.continuationReason(1,broken,settle,false,false,1800000,200)==null)throw new IllegalStateException("terminal_result_kind_mismatch");checks++;
                    broken=new JSONObject(original);JSONObject hook=broken.getJSONArray("hooks").getJSONObject(index);
                    hook.put("detail","session_stopped_before_turn_confirmation:cancelled");
                    hook.getJSONObject("end_turn_outcome").put("reason","session_stopped_before_turn_confirmation:cancelled");
                    if(plan.continuationReason(1,broken,settle,false,false,1800000,200)==null)throw new IllegalStateException("terminal_result_cancel_reason");checks++;
                }
            }
            rows.put(new JSONObject().put("source",name).put("input_count",result.getInt("game_inputs"))
                    .put("ordinary_unknown",result.getInt("unconfirmed_inputs"))
                    .put("end_unknown",result.getInt("end_turns_unconfirmed")).put("unchanged",true));
        }
        return new JSONObject().put("passed",true).put("checks",checks).put("rows",rows).put("device_inputs",0);
    }
}
