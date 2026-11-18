package com.kards.mobilert;

import android.graphics.Rect;
import org.json.JSONObject;
import java.util.Arrays;

final class GameWindowChecks {
    static GameWindowState.Window window(int id,int type,int layer,String owner,Rect bounds,boolean active,boolean focused,boolean own) {
        return new GameWindowState.Window(id,type,layer,owner,bounds,active,focused,own);
    }
    static void require(boolean condition,String reason) {if(!condition)throw new AssertionError(reason);}
    static JSONObject run() throws Exception {
        Rect full=new Rect(0,0,2780,1264);
        GameWindowState.Window game=window(1,1,1,GameWindowState.GAME,full,true,true,false);
        GameWindowState.Window banner=window(2,3,2,"com.android.systemui",new Rect(600,0,2180,300),false,false,false);
        GameWindowState.Window shade=window(3,1,3,"com.android.systemui",full,true,true,false);
        GameWindowState.Window other=window(4,1,4,"other.app",full,true,true,false);
        GameWindowState.Window control=window(5,4,5,"com.kards.mobilert",new Rect(2500,500,2780,800),false,false,true);
        GameWindowState clean=GameWindowState.inspect(Arrays.asList(game,control),false);
        require(clean.game!=null && !clean.occluded,"own_control_isolated");
        GameWindowState notification=GameWindowState.inspect(Arrays.asList(game,banner,control),false);
        require(notification.game!=null && notification.occluded,"banner_wait_not_foreground_exit");
        GameWindowState panel=GameWindowState.inspect(Arrays.asList(game,shade,control),false);
        require(panel.game!=null && panel.occluded,"shade_wait_not_foreground_exit");
        GameEntryGate gate=new GameEntryGate("current_game",clean.foreground,9,10);
        require(gate.check(panel.foreground,9)==null && gate.check(clean.foreground,9)==null,"overlay_keeps_admission");
        GameWindowState switchApp=GameWindowState.inspect(Arrays.asList(game,other),false);
        require(switchApp.game==null && "foreground_changed".equals(gate.check(switchApp.foreground,10)),"real_switch_stops");
        require(GameWindowState.inspect(Arrays.asList(game,shade),true).game==null,"lock_stops");
        GameWindowState.Window bar=window(6,3,6,"com.android.systemui",new Rect(0,0,2780,60),false,false,false);
        require(!GameWindowState.inspect(Arrays.asList(game,bar),false).occluded,"unfocused_thin_bar");
        GameWindowState.Window focused=window(7,3,6,"com.android.systemui",bar.bounds,true,true,false);
        require(GameWindowState.inspect(Arrays.asList(game,focused),false).occluded,"focused_bar_waits");
        GameWindowState.Window edge=window(9,3,6,"system",new Rect(-270,154,93,434),false,false,false);
        GameWindowState handle=GameWindowState.inspect(Arrays.asList(game,edge),false);
        require(!handle.occluded && handle.blocksPath(new float[][]{{40,200}}),"edge_handle_only_blocks_touched_area");
        require(!handle.blocksPath(new float[][]{{400,200},{800,800}}),"unrelated_path_available");
        require(handle.blocksPath(new float[][]{{200,200},{10,200},{400,200}}),"whole_drag_path_covered");
        GameWindowState.Window unknownHandle=window(10,-1,6,"",new Rect(-248,476,56,662),false,false,false);
        GameWindowState unknownEdge=GameWindowState.inspect(Arrays.asList(game,unknownHandle),false);
        require(!unknownEdge.occluded && unknownEdge.blocksPath(new float[][]{{20,500}}),"unknown_edge_only_blocks_visible_path");
        GameWindowState.Window right=window(11,-1,6,"",new Rect(2724,476,3028,662),false,false,false);
        GameWindowState both=GameWindowState.inspect(Arrays.asList(game,unknownHandle,right),false);
        require(!both.occluded && both.game!=null,"left_right_handles_keep_game_active");
        require(both.blocksPath(new float[][]{{2750,500}}) && both.blocksPath(new float[][]{{20,500}}),"both_handle_touch_paths_wait");
        require(!both.blocksPath(new float[][]{{1400,600},{1600,900}}),"both_handles_do_not_block_middle_actions");
        require(both.blocksPath(new float[][]{{2600,500},{2750,500},{2400,800}}),"right_drag_segment_waits");
        GameWindowState.Window unknown=window(8,1,6,"",full,true,true,false);
        require(GameWindowState.inspect(Arrays.asList(game,unknown),false).game==null,"unknown_app_not_admitted");
        require("等待遮挡消失".equals(FloatingStatus.from("{\"active\":true,\"event\":\"overlay_wait\",\"stage\":\"battle\"}","攻击").phase),"wait_visible");
        GameWindowState hidden=GameWindowState.inspect(Arrays.asList(shade),false,game);
        require(hidden.game!=null && hidden.occluded && hidden.blocksPath(new float[][]{{1400,600}}),"system_only_is_waiting_not_permission");
        require(GameWindowState.inspect(Arrays.asList(shade),true,game).game==null,"hidden_game_lock_stops");
        require(GameWindowState.inspect(Arrays.asList(other,shade),false,game).game==null,"other_app_under_shade_stops");
        require(GameWindowState.inspect(java.util.Collections.emptyList(),false,game).game==null,"empty_inventory_not_assumed_notification");
        Rect wide=new Rect(0,0,1612,720);
        GameWindowState.Window phoneGame=window(20,1,1,GameWindowState.GAME,wide,true,true,false);
        Rect widgetArea=new Rect(1475,317,1612,432);
        GameWindowState.Window widget=window(21,4,5,"",widgetArea,false,false,false);
        GameWindowState phone=GameWindowState.inspect(Arrays.asList(phoneGame,widget),false);
        require(phone.game!=null && !phone.occluded,"wide_unknown_edge_widget_is_local");
        require(phone.blocksPath(new float[][]{{1550,360}}),"edge_widget_touch_still_blocked");
        require(!phone.blocksPath(new float[][]{{806,650}}),"wide_opening_confirm_outside_widget");
        require(phone.blocksPath(new float[][]{{1400,360},{1600,360}}),"drag_crossing_widget_still_blocked");
        GameWindowState.Window focusedWidget=window(22,4,5,"",widgetArea,true,true,false);
        require(GameWindowState.inspect(Arrays.asList(phoneGame,focusedWidget),false).occluded,"focused_edge_widget_waits");
        GameWindowState.Window centerWidget=window(23,3,5,"other.widget",new Rect(700,317,837,432),false,false,false);
        require(GameWindowState.inspect(Arrays.asList(phoneGame,centerWidget),false).occluded,"center_popup_still_waits");
        GameWindowState.Window largeEdge=window(24,3,5,"",new Rect(1475,200,1612,500),false,false,false);
        require(GameWindowState.inspect(Arrays.asList(phoneGame,largeEdge),false).occluded,"large_edge_panel_still_waits");
        GameWindowState.Window unknownFull=window(25,3,5,"",wide,false,false,false);
        require(GameWindowState.inspect(Arrays.asList(phoneGame,unknownFull),false).occluded,"unknown_fullscreen_overlay_still_waits");
        GameWindowState.Window externalApp=window(26,1,5,"other.app",widgetArea,false,false,false);
        require(GameWindowState.inspect(Arrays.asList(phoneGame,externalApp),false).game==null,"external_application_not_widget_exemption");
        require(GameWindowState.inspect(Arrays.asList(phoneGame,widget),true).game==null,"wide_widget_does_not_override_lock");
        return new JSONObject().put("passed",true).put("checks",32).put("device_inputs",0);
    }
}
