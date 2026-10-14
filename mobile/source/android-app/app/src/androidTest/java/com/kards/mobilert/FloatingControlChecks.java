package com.kards.mobilert;

import android.app.Instrumentation;
import android.graphics.Bitmap;
import android.graphics.Rect;
import org.json.JSONObject;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** No gameplay, real game launches or touch dispatch. Capture only the helper Activity. */
final class FloatingControlChecks {
    private static void require(boolean value,String why) { if(!value)throw new AssertionError(why); }
    static JSONObject model() throws Exception {
        for(int[] shape:new int[][]{{2772,1240},{1280,720},{2400,1080},{1080,2400}}) {
            Rect c=GameFloatingControl.bounds(shape[0],shape[1],1.9375f,false);
            Rect e=GameFloatingControl.bounds(shape[0],shape[1],1.9375f,true);
            require(c.right==shape[0] && c.left>=shape[0]*.915-1 && c.bottom<shape[1]*.61,"edge placement");
            require(e.right==shape[0] && e.top<=c.top && e.bottom==c.bottom,"expands upwards");
        }
        require(FloatingStatus.from("bad","").phase.equals("未启动"),"invalid state");
        JSONObject p=new JSONObject().put("active",true).put("stage","battle").put("session_id","test")
                .put("completed_matches",2).put("round_inputs",8);
        require(FloatingStatus.from(p.toString(),"部署").phase.equals("部署"),"action status");
        require(FloatingStatus.from(p.toString(),"").detail.contains("触控 8"),"touches not successes");
        p.put("engine",new JSONObject().put("kind","native_observation").put("value",new JSONObject().put("state","unknown")));
        require(FloatingStatus.from(p.toString(),"攻击").phase.equals("画面未知"),"unknown dominates stale action");
        p.getJSONObject("engine").getJSONObject("value").put("state","opponent_turn");
        require(FloatingStatus.from(p.toString(),"攻击").phase.equals("对方回合"),"enemy turn");
        p.put("engine",new JSONObject().put("stop_reason","result_victory").put("result_verified",false));
        require(!FloatingStatus.from(p.toString(),"").phase.equals("胜利"),"unverified victory");
        p.getJSONObject("engine").put("result_verified",true);p.put("active",false);
        require(FloatingStatus.from(p.toString(),"").phase.equals("胜利"),"verified victory");
        p.getJSONObject("engine").put("stop_reason","result_defeat");
        require(FloatingStatus.from(p.toString(),"").phase.equals("失败"),"verified defeat");
        p.put("event","stopping");require(FloatingStatus.from(p.toString(),"").phase.equals("正在停止"),"stopping");
        return new JSONObject().put("passed",true).put("geometry_profiles",4).put("unknown_remains_unknown",true);
    }
    private static Bitmap frame(Instrumentation instrumentation,KardsAccessibilityService service,
                                GameFloatingControl control,boolean expectHidden) throws Exception {
        CountDownLatch done=new CountDownLatch(1);AtomicReference<Bitmap> image=new AtomicReference<>();
        AtomicReference<String> error=new AtomicReference<>();
        instrumentation.runOnMainSync(()->service.requestNativeFrame(new FrameSource.Callback() {
            @Override public void onFrame(FrameSnapshot s) {
                try {
                    if(expectHidden && !control.hiddenForTest())error.set("overlay visible during capture");
                    image.set(s.bitmap().copy(Bitmap.Config.ARGB_8888,false));
                } finally {s.close();done.countDown();}
            }
            @Override public void onFailure(String why) {error.set(why);done.countDown();}
        }));
        require(done.await(8,TimeUnit.SECONDS),"capture timeout");
        require(error.get()==null,"capture failure: "+error.get());return image.get();
    }
    static JSONObject platform(Instrumentation instrumentation) throws Exception {
        KardsAccessibilityService service=KardsAccessibilityService.instance();
        for(int i=0;service==null && i<50;i++){Thread.sleep(100);service=KardsAccessibilityService.instance();}
        final KardsAccessibilityService connected=service;
        require(service!=null,"accessibility service required for overlay check");
        GameFloatingControl control=service.floatingControlForTest();require(control!=null,"missing overlay");
        AtomicReference<String> foreground=new AtomicReference<>();
        instrumentation.runOnMainSync(()->foreground.set(connected.currentForegroundPackage()));
        require(foreground.get().equals(service.getPackageName()),"test must be on helper Activity, never KARDS");
        Bitmap baseline=frame(instrumentation,service,control,false);Bitmap compact=null,expanded=null;
        try {
            instrumentation.runOnMainSync(()->control.showForTest(false));
            instrumentation.waitForIdleSync();Thread.sleep(200);
            instrumentation.runOnMainSync(()->require(control.windowIdForTest()!=-1,"overlay window not attached"));
            compact=frame(instrumentation,service,control,true);
            instrumentation.runOnMainSync(()->control.showForTest(true));
            instrumentation.waitForIdleSync();Thread.sleep(200);
            expanded=frame(instrumentation,service,control,true);
            AtomicReference<Rect> region=new AtomicReference<>();
            instrumentation.runOnMainSync(()->region.set(control.boundsForTest()));
            Rect r=region.get();long sum=0,samples=0;
            require(baseline.getWidth()==expanded.getWidth() && baseline.getHeight()==expanded.getHeight(),"capture size changed");
            for(int y=r.top+4;y<r.bottom-4;y+=3)for(int x=r.left+4;x<r.right-4;x+=3) {
                int a=baseline.getPixel(x,y),b=expanded.getPixel(x,y),c=compact.getPixel(x,y);
                for(int shift:new int[]{0,8,16}) {
                    sum+=Math.abs(((a>>shift)&255)-((b>>shift)&255));
                    sum+=Math.abs(((a>>shift)&255)-((c>>shift)&255));samples+=2;
                }
            }
            double mean=(double)sum/samples;require(mean<1.0,"control contaminated source pixels: "+mean);
            AtomicReference<Runnable> first=new AtomicReference<>(),second=new AtomicReference<>();
            CountDownLatch leases=new CountDownLatch(2);
            instrumentation.runOnMainSync(()->{
                control.withoutOverlay(release->{first.set(release);leases.countDown();});
                control.withoutOverlay(release->{second.set(release);leases.countDown();});
            });
            require(leases.await(2,TimeUnit.SECONDS),"hide leases not prepared");
            instrumentation.runOnMainSync(()->{first.get().run();first.get().run();});instrumentation.waitForIdleSync();
            instrumentation.runOnMainSync(()->require(control.hiddenForTest(),"first release restored nested lease"));
            instrumentation.runOnMainSync(()->second.get().run());instrumentation.waitForIdleSync();
            instrumentation.runOnMainSync(()->{
                require(!control.hiddenForTest(),"control not restored");
                require(connected.currentForegroundPackage().equals(connected.getPackageName()),"overlay changed foreground");
                require(!connected.startFromFloatingControl(true),"started current battle outside KARDS");
                require(!connected.startFromFloatingControl(false),"started menu outside KARDS");
                require(!BattleWorkerLease.isOwned(),"negative starts acquired worker");
            });
            return new JSONObject().put("passed",true).put("source_capture_count",3)
                    .put("overlay_region_mean_pixel_delta",mean).put("nested_and_duplicate_release",true)
                    .put("non_game_start_refusals",2).put("game_launches",0).put("touches",0);
        } finally {
            baseline.recycle();if(compact!=null)compact.recycle();if(expanded!=null)expanded.recycle();
            instrumentation.runOnMainSync(control::restoreAfterTest);
        }
    }

    static JSONObject gameForeground(Instrumentation instrumentation) throws Exception {
        KardsAccessibilityService candidate=KardsAccessibilityService.instance();
        for(int i=0;candidate==null && i<50;i++){Thread.sleep(100);candidate=KardsAccessibilityService.instance();}
        final KardsAccessibilityService service=candidate;require(service!=null,"service required");
        GameFloatingControl control=service.floatingControlForTest();
        AtomicReference<Long> generation=new AtomicReference<>();
        instrumentation.runOnMainSync(()->{
            require(service.currentForegroundPackage().equals("com.android1939.kards"),"game must be foreground");
            require(!BattleWorkerLease.isOwned(),"no battle worker during read-only UI check");
            generation.set(service.gameForegroundGeneration());control.showForTest(false);
        });
        instrumentation.waitForIdleSync();Thread.sleep(200);
        instrumentation.runOnMainSync(()->{
            require(service.currentForegroundPackage().equals("com.android1939.kards"),"collapsed control stole foreground");
            control.setExpanded(true);
        });
        instrumentation.waitForIdleSync();Thread.sleep(200);
        Bitmap b=null;
        try {
            b=frame(instrumentation,service,control,true);
            instrumentation.waitForIdleSync();
            instrumentation.runOnMainSync(()->{
                require(service.currentForegroundPackage().equals("com.android1939.kards"),"expanded control stole foreground");
                require(service.gameForegroundGeneration()==generation.get(),"overlay invalidated game admission generation");
                require(control.expandedForTest(),"capture collapsed panel");
                require(!BattleWorkerLease.isOwned(),"expanding or capturing automatically started a game");
            });
            return new JSONObject().put("passed",true).put("foreground_generation_unchanged",true)
                    .put("expanded_preserved",true).put("capture_hidden",true).put("game_inputs",0);
        } finally {if(b!=null)b.recycle();instrumentation.runOnMainSync(control::restoreAfterTest);}
    }
}
