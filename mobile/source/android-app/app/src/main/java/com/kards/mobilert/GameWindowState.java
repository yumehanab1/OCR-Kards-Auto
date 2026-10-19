package com.kards.mobilert;

import android.graphics.Rect;
import java.util.List;
import java.util.ArrayList;

/** Window metadata only. Never inspects text or notification content. */
final class GameWindowState {
    static final String GAME=GamePackages.DEFAULT;
    static final String OCCLUDED="temporary_game_window_occluded";
    static final class Window {
        final int id,type,layer;final String owner;final Rect bounds;final boolean active,focused,ownOverlay;
        Window(int id,int type,int layer,String owner,Rect bounds,boolean active,boolean focused,boolean ownOverlay) {
            this.id=id;this.type=type;this.layer=layer;this.owner=owner;this.bounds=new Rect(bounds);
            this.active=active;this.focused=focused;this.ownOverlay=ownOverlay;
        }
    }
    final Window game;final boolean occluded;final String foreground;
    final List<Rect> obstructions=new ArrayList<>();
    GameWindowState(Window game,boolean occluded,String foreground) {this.game=game;this.occluded=occluded;this.foreground=foreground;}
    static GameWindowState inspect(List<Window> windows,boolean locked) {
        return inspect(windows,locked,null);
    }
    static GameWindowState inspect(List<Window> windows,boolean locked,Window previousGame) {
        if(locked)return new GameWindowState(null,false,"");
        Window application=null;
        for(Window window:windows) {
            if(window.ownOverlay || window.type!=1 || window.bounds.isEmpty()
                    || "com.android.systemui".equals(window.owner))continue;
            if(application==null || window.layer>application.layer)application=window;
        }
        if(application==null && previousGame!=null && GamePackages.isGame(previousGame.owner) && !windows.isEmpty()) {
            boolean onlySystem=true,systemUi=false;
            for(Window window:windows) {
                if(window.ownOverlay)continue;
                if("com.android.systemui".equals(window.owner))systemUi=true;
                else if(window.type!=3)onlySystem=false;
            }
            if(onlySystem && systemUi) {
                // A fully expanded shade hides underlying app windows from
                // accessibility. Previous identity grants WAITING only.
                return new GameWindowState(previousGame,true,previousGame.owner);
            }
        }
        if(application==null || !GamePackages.isGame(application.owner))
            return new GameWindowState(null,false,application==null?"":application.owner);
        boolean blocked=false;
        ArrayList<Rect> obstructions=new ArrayList<>();
        for(Window window:windows) {
            if(window.id==application.id || window.ownOverlay || window.layer<=application.layer
                    || !Rect.intersects(window.bounds,application.bounds))continue;
            Rect visible=new Rect(window.bounds);visible.intersect(application.bounds);
            obstructions.add(visible);
            boolean thinBar=window.type!=1 && !window.active && !window.focused
                    && (visible.height()<=application.bounds.height()*.08
                        || visible.width()<=application.bounds.width()*.04);
            if(!thinBar)blocked=true;
        }
        GameWindowState result=new GameWindowState(application,blocked,application.owner);
        result.obstructions.addAll(obstructions);return result;
    }
    boolean blocksPath(float[][] points) {
        if(occluded)return true;
        for(int i=0;i<points.length;i++) {
            float[] a=points[i],b=points[Math.max(0,i-1)];
            Rect span=new Rect((int)Math.floor(Math.min(a[0],b[0]))-8,(int)Math.floor(Math.min(a[1],b[1]))-8,
                    (int)Math.ceil(Math.max(a[0],b[0]))+9,(int)Math.ceil(Math.max(a[1],b[1]))+9);
            for(Rect box:obstructions)if(Rect.intersects(span,box))return true;
        }
        return false;
    }
}
