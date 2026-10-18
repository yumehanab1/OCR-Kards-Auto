package com.kards.mobilert;

import org.json.JSONObject;

/** Presentation of live facts only; a completed touch is not a confirmed game effect. */
final class FloatingStatus {
    final boolean active;
    final String phase, compact, detail;
    FloatingStatus(boolean active, String phase, String compact, String detail) {
        this.active=active; this.phase=phase; this.compact=compact; this.detail=detail;
    }
    static String action(String context) {
        switch(context) {
            case "deploy": return "部署";
            case "move_front": case "movefront": return "移动";
            case "attack_hq": case "attack_unit": return "攻击";
            case "end_turn": return "结束回合";
            case "choice_select": return "选择卡牌";
            case "settle": return "结算补点";
            default: return "操作中";
        }
    }
    static FloatingStatus from(String raw, String recentAction) {
        try {
            JSONObject p=new JSONObject(raw);
            boolean active=Boolean.TRUE.equals(p.opt("active"));
            boolean stopping="stopping".equals(p.optString("event"));
            String stage=p.optString("stage"), phase="等待画面";
            JSONObject e=p.optJSONObject("engine"), v=e==null?null:e.optJSONObject("value");
            String screen=v==null?"":v.optString("state");
            JSONObject result=e!=null && "finished".equals(e.optString("kind"))?v:e;
            if("menu".equals(stage)) phase="准备开局";
            else if("opening".equals(stage)) phase="起手确认";
            else if("settle".equals(stage)) phase="结算回页";
            else if("battle".equals(stage)) phase="观察战场";
            if("unknown".equals(screen)) phase="画面未知";
            else if("queue".equals(screen)) phase="等待匹配";
            else if("deck_list".equals(screen) || "deck_ready".equals(screen)) phase="选择牌组";
            else if("mulligan".equals(screen)) phase="起手确认";
            else if("home".equals(screen) || "mode_menu".equals(screen)) phase="准备开局";
            else if("opponent_turn".equals(screen)) phase="对方回合";
            else if(screen.startsWith("result_")) phase="结算核验";
            else if(active && !recentAction.isEmpty()) phase=recentAction;
            if(active && "overlay_wait".equals(p.optString("event")))phase="等待遮挡消失";
            if(active && "capture_retry".equals(p.optString("event")))phase=
                    "capture_black_frame".equals(p.optString("reason"))?"截图黑屏·重试":
                    "compat_capture_incomplete_frame".equals(p.optString("reason"))?"截图不完整·重试":"等待新截图";
            boolean verified=result!=null && Boolean.TRUE.equals(result.opt("result_verified"));
            String reason=result==null?"":result.optString("stop_reason");
            if(verified && "result_victory".equals(reason)) phase="胜利";
            else if(verified && "result_defeat".equals(reason)) phase="失败";
            if(verified && active && "settle".equals(stage))
                phase+=("结算补点".equals(recentAction)?"·补点":"·回页");
            if(stopping) phase="正在停止";
            else if(!active && !verified) phase=p.has("session_id")?"已停止":"未启动";
            String run=stopping?"停止中":active?"运行":"停止";
            int closed=Math.max(0,p.optInt("completed_matches",0));
            int inputs=Math.max(0,p.optInt("round_inputs",0));
            int target=p.optInt("match_count",1);
            long seconds=Math.max(0,p.optLong("elapsed_ms",0))/1000;
            JSONObject totals=p.optJSONObject("round_totals");
            String unknown=totals!=null && totals.has("unconfirmed_inputs")
                    ?String.valueOf(totals.optInt("unconfirmed_inputs")):"—";
            String detail="已完成 "+closed+" / "+(target==0?"不限":target)+" 局"
                    +"\n本局触控 "+inputs+" 次 · 用时 "+seconds/60+"分"+seconds%60+"秒"
                    +"\n已结束局普通效果未知 "+unknown;
            if(!active) {
                String stop=TrainingPanelState.from(raw).stopReason;
                if(!stop.isEmpty()) detail+="\n"+stop;
            }
            return new FloatingStatus(active,phase,run+"\n"+phase+"\n"+closed+"局 · "+inputs+"次",detail);
        } catch(Exception ignored) { return new FloatingStatus(false,"未启动","停止\n未启动\n点击展开","打开游戏后可启停辅助"); }
    }
}
