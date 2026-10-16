package com.kards.mobilert;

import android.graphics.Rect;
import java.util.Arrays;
import java.util.Collections;
import org.json.JSONObject;

final class ForegroundDepartureChecks {
    private static GameWindowState.Window window(int id, int type, String owner,
                                                boolean active, boolean focused, boolean ownOverlay) {
        return new GameWindowState.Window(id,type,id,owner,new Rect(0,0,1280,720),
                active,focused,ownOverlay);
    }
    private static void require(boolean condition, String reason) {
        if (!condition) throw new AssertionError(reason);
    }
    static JSONObject run() throws Exception {
        ForegroundDepartureTracker tracker = new ForegroundDepartureTracker();
        GameWindowState.Window game = window(1,1,GameWindowState.GAME,true,true,false);
        GameWindowState.Window replacement = window(2,1,GameWindowState.GAME,true,true,false);
        GameWindowState.Window unknown = window(3,1,"",true,true,false);
        GameWindowState.Window systemUi = window(4,1,"com.android.systemui",true,true,false);
        GameWindowState.Window ownOverlay = window(5,1,"com.kards.mobilert",true,true,true);
        GameWindowState.Window other = window(6,1,"other.app",true,false,false);
        GameWindowState.Window focusedOther = window(7,1,"other.app",false,true,false);
        require(tracker.epoch()==0,"initial_epoch");
        require(tracker.observe(Arrays.asList(game),false)==0,"current_game_not_departure");
        require(tracker.observe(Arrays.asList(replacement),false)==0,"game_window_replacement_not_departure");
        require(tracker.observe(Collections.emptyList(),false)==0,"no_windows_not_departure");
        require(tracker.observe(Arrays.asList(unknown),false)==0,"empty_root_owner_not_external");
        require(tracker.observe(Arrays.asList(systemUi),false)==0,"system_ui_only_not_departure");
        require(tracker.observe(Arrays.asList(game,systemUi,ownOverlay),false)==0,"overlays_not_departure");
        require(tracker.observe(Arrays.asList(ownOverlay),false)==0,"own_overlay_only_not_departure");
        require(tracker.observe(Arrays.asList(window(8,1,"other.app",false,false,false)),false)==0,
                "inactive_unfocused_application_not_departure");
        require(tracker.observe(Arrays.asList(window(9,3,"other.app",true,true,false)),false)==0,
                "nonapplication_not_departure");
        GameWindowState.Window emptyBounds = new GameWindowState.Window(10,1,10,"other.app",new Rect(),true,true,false);
        require(tracker.observe(Arrays.asList(emptyBounds),false)==0,"empty_window_not_departure");
        require(tracker.observe(Arrays.asList(game,other),false)==1,"active_other_application_departure");
        require(tracker.observe(Arrays.asList(other),false)==1,"continuous_departure_not_recounted");
        require(tracker.observe(Arrays.asList(focusedOther),false)==1,"external_window_replacement_same_departure");
        require(tracker.observe(Collections.emptyList(),false)==1,"unknown_does_not_reset_departure");
        require(tracker.observe(Arrays.asList(systemUi,unknown),false)==1,"system_ui_unknown_do_not_reset_departure");
        require(tracker.observe(Arrays.asList(window(11,1,GameWindowState.GAME,false,false,false)),false)==1,
                "inactive_game_does_not_prove_return");
        require(tracker.observe(Arrays.asList(other),false)==1,"same_external_episode_after_unknown");
        require(tracker.observe(Arrays.asList(replacement),false)==1,"current_game_proves_return");
        require(tracker.observe(Arrays.asList(focusedOther),false)==2,"focused_other_after_return_new_departure");
        tracker.observe(Arrays.asList(game),false);
        require(tracker.observe(Arrays.asList(window(12,1,"com.kards.mobilert",true,true,false)),false)==3,
                "own_activity_is_real_external_application");
        tracker.observe(Arrays.asList(game),false);
        require(tracker.observe(Collections.emptyList(),true)==4,"locked_is_departure");
        require(tracker.observe(Arrays.asList(game),true)==4,"continuous_lock_not_recounted");
        require(tracker.observe(Collections.emptyList(),false)==4,"unlock_without_game_does_not_prove_return");
        require(tracker.observe(Arrays.asList(other),false)==5,"external_after_lock_is_new_explicit_fact");
        tracker.observe(Arrays.asList(game),false);
        require(tracker.observe(Arrays.asList(systemUi),true)==6,"lock_after_game_return_new_departure");
        tracker.observe(Arrays.asList(game),false);
        require(tracker.observe(Arrays.asList(other),false)==7,"external_after_second_game_return_new_departure");

        // Launch is armed while the helper Activity is still foreground. A
        // different app or lock must be detectable before any first game frame.
        ForegroundDepartureTracker startup = new ForegroundDepartureTracker();
        GameWindowState.Window helper = window(20,1,"com.kards.mobilert",true,true,false);
        require(startup.observe(Arrays.asList(helper),false)==1,"arming_helper_activity_fact");
        require(startup.observe(Arrays.asList(window(21,1,"com.kards.mobilert",false,true,false)),false)==1,
                "same_owner_replacement_before_game_not_recounted");
        require(startup.observe(Arrays.asList(unknown,systemUi,ownOverlay),false)==1,
                "unknown_system_ui_keep_arming_fact");
        require(startup.observe(Arrays.asList(systemUi),true)==2,"lock_before_first_game_changes_arming_epoch");
        require(startup.observe(Collections.emptyList(),true)==2,"same_startup_lock_not_recounted");
        require(startup.observe(Arrays.asList(unknown,systemUi),false)==2,"unknown_after_lock_keeps_lock_fact");
        require(startup.observe(Arrays.asList(helper),false)==3,"helper_return_after_lock_explicit_fact");
        require(startup.observe(Arrays.asList(other),false)==4,"different_app_before_first_game_changes_epoch");
        require(startup.observe(Arrays.asList(focusedOther),false)==4,"same_external_owner_before_game_not_recounted");
        require(startup.observe(Arrays.asList(unknown,systemUi),false)==4,"unknown_keeps_external_owner_fact");
        require(startup.observe(Arrays.asList(other),false)==4,"same_external_after_unknown_not_recounted");
        require(startup.observe(Arrays.asList(game),false)==4,"first_game_retains_prior_departure_epoch");
        require(startup.observe(Arrays.asList(helper),false)==5,"helper_after_first_game_new_departure");
        return new JSONObject().put("passed",true).put("checks",40).put("device_inputs",0);
    }
}
