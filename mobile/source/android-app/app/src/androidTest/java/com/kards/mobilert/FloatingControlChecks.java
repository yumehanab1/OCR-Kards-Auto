package com.kards.mobilert;

import android.app.Instrumentation;
import android.app.Activity;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.ScrollView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** No gameplay, real game launches or touch dispatch. Capture only the helper Activity. */
final class FloatingControlChecks {
    private static void require(boolean value,String why) { if(!value)throw new AssertionError(why); }
    /** Test-only opaque content prevents dashboard refreshes changing the comparison. */
    private static final class StaticCaptureBackground extends View {
        final CountDownLatch drawn=new CountDownLatch(1);
        private final Paint paint=new Paint();
        int drawCount;
        StaticCaptureBackground(Activity activity) {
            super(activity);
            setWillNotDraw(false);
            setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        }
        @Override public boolean isOpaque() { return true; }
        @Override protected void onDraw(Canvas canvas) {
            canvas.drawColor(Color.rgb(27,61,83));
            int cell=Math.max(12,Math.min(getWidth(),getHeight())/12);
            for(int y=0;y<getHeight();y+=cell)for(int x=0;x<getWidth();x+=cell) {
                int column=x/cell,row=y/cell;
                paint.setColor(Color.rgb(30+(column%5)*23,55+(row%5)*19,75+((column+row)%5)*17));
                canvas.drawRect(x,y,Math.min(getWidth(),x+cell),Math.min(getHeight(),y+cell),paint);
            }
            drawCount++;
            if(drawCount>=2)drawn.countDown();else postInvalidateOnAnimation();
        }
    }
    /** Test assertions must return to the worker so the instrumentation can save its report. */
    private static void onMain(Instrumentation instrumentation,Runnable work) {
        AtomicReference<Throwable> failed=new AtomicReference<>();
        instrumentation.runOnMainSync(()->{try {work.run();}catch(Throwable error){failed.set(error);}});
        Throwable error=failed.get();
        if(error instanceof Error)throw (Error)error;
        if(error instanceof RuntimeException)throw (RuntimeException)error;
        if(error!=null)throw new AssertionError("Main-thread check failed",error);
    }
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
                                GameFloatingControl control,boolean expectHidden,boolean nativePixels) throws Exception {
        return frame(instrumentation,service,control,expectHidden,nativePixels,null);
    }
    private static Bitmap frame(Instrumentation instrumentation,KardsAccessibilityService service,
                                GameFloatingControl control,boolean expectHidden,boolean nativePixels,
                                JSONObject metadata) throws Exception {
        CountDownLatch done=new CountDownLatch(1);AtomicReference<Bitmap> image=new AtomicReference<>();
        AtomicReference<String> error=new AtomicReference<>();
        onMain(instrumentation,()->{
            FrameSource.Callback callback=new FrameSource.Callback() {
            @Override public void onFrame(FrameSnapshot s) {
                try {
                    if(metadata!=null)try {
                        metadata.put("source_width",s.sourceWidth()).put("source_height",s.sourceHeight())
                                .put("bitmap_width",s.width()).put("bitmap_height",s.height())
                                .put("capture_scope",s.captureScope).put("capture_window_id",s.captureWindowId)
                                .put("capture_bounds",rect(s.captureBounds)).put("captured_at_ms",s.capturedAtMillis());
                        if(expectHidden)metadata.put("overlay_window_alpha",control.windowAlphaForTest())
                                .put("overlay_touch_blocked",control.windowTouchBlockedForTest());
                    } catch(Exception failure) {error.set("capture metadata: "+failure);}
                    if(expectHidden && !control.hiddenForTest())error.set("overlay visible during capture");
                    if(expectHidden && (control.windowAlphaForTest()!=0f || !control.windowTouchBlockedForTest()))
                        error.set("overlay compositor layer or touch window visible during capture");
                    if(expectHidden && (control.cachedWindowIdForTest()<0
                            || !control.ownsWindow(control.cachedWindowIdForTest())))
                        error.set("hidden overlay lost its exact attachment identity");
                    image.set(s.bitmap().copy(Bitmap.Config.ARGB_8888,false));
                } finally {s.close();done.countDown();}
            }
            @Override public void onFailure(String why) {error.set(why);done.countDown();}
            };
            if(nativePixels)service.requestNativeFrame(callback);else service.requestFrame(callback);
        });
        require(done.await(8,TimeUnit.SECONDS),"capture timeout");
        require(error.get()==null,"capture failure: "+error.get());return image.get();
    }
    private static JSONArray rect(Rect value) {
        return new JSONArray().put(value.left).put(value.top).put(value.right).put(value.bottom);
    }
    private static JSONObject fixtureState(Instrumentation instrumentation,Activity activity,
                                          ViewGroup parent,StaticCaptureBackground fixture,
                                          KardsAccessibilityService service) {
        AtomicReference<JSONObject> result=new AtomicReference<>();
        onMain(instrumentation,()->{
            try {
                Rect visible=new Rect();boolean visibleRect=fixture.getGlobalVisibleRect(visible);
                int[] location=new int[2];fixture.getLocationOnScreen(location);
                Rect display=service.getSystemService(android.view.WindowManager.class).getCurrentWindowMetrics().getBounds();
                android.view.WindowInsets insets=fixture.getRootWindowInsets();
                android.graphics.Insets bars=insets==null?null:insets.getInsetsIgnoringVisibility(android.view.WindowInsets.Type.systemBars());
                JSONObject state=new JSONObject().put("activity_identity",System.identityHashCode(activity))
                        .put("activity_destroyed",activity.isDestroyed()).put("activity_finishing",activity.isFinishing())
                        .put("activity_window_focus",activity.hasWindowFocus()).put("same_content",activity.findViewById(android.R.id.content)==parent)
                        .put("fixture_attached",fixture.isAttachedToWindow()).put("fixture_shown",fixture.isShown())
                        .put("same_parent",fixture.getParent()==parent).put("last_child",parent.indexOfChild(fixture)==parent.getChildCount()-1)
                        .put("fixture_size",new JSONArray().put(fixture.getWidth()).put(fixture.getHeight()))
                        .put("fixture_location",new JSONArray().put(location[0]).put(location[1]))
                        .put("fixture_visible_rect",rect(visible)).put("fixture_has_visible_rect",visibleRect)
                        .put("display_bounds",rect(display)).put("display_rotation",fixture.getDisplay()==null?-1:fixture.getDisplay().getRotation())
                        .put("system_bar_insets",bars==null?JSONObject.NULL:new JSONArray().put(bars.left).put(bars.top).put(bars.right).put(bars.bottom))
                        .put("density",fixture.getResources().getDisplayMetrics().density)
                        .put("same_service",KardsAccessibilityService.instance()==service)
                        .put("foreground_package",service.currentForegroundPackage()).put("draw_count",fixture.drawCount);
                result.set(state);
            } catch(Exception error) {throw new AssertionError("fixture state",error);}
        });
        return result.get();
    }
    private static String fixtureGeometry(JSONObject state) throws Exception {
        return new JSONArray().put(state.get("activity_identity")).put(state.get("fixture_size"))
                .put(state.get("fixture_location")).put(state.get("fixture_visible_rect"))
                .put(state.get("display_bounds")).put(state.get("display_rotation")).toString();
    }
    private static void requireFixture(JSONObject state,String geometry,String stage) throws Exception {
        require(!state.getBoolean("activity_destroyed") && !state.getBoolean("activity_finishing")
                && state.getBoolean("activity_window_focus") && state.getBoolean("same_content")
                && state.getBoolean("fixture_attached") && state.getBoolean("fixture_shown")
                && state.getBoolean("same_parent") && state.getBoolean("last_child")
                && state.getBoolean("fixture_has_visible_rect") && state.getBoolean("same_service")
                && "com.kards.mobilert".equals(state.getString("foreground_package")),"helper fixture changed at "+stage+": "+state);
        require(geometry.equals(fixtureGeometry(state)),"helper fixture geometry changed at "+stage+": "+state);
    }
    private static Bitmap fixtureFrame(Instrumentation instrumentation,Activity activity,ViewGroup parent,
                                       StaticCaptureBackground fixture,KardsAccessibilityService service,
                                       GameFloatingControl control,boolean hidden,String stage,String geometry,
                                       File directory,JSONArray records) throws Exception {
        JSONObject record=new JSONObject().put("stage",stage);records.put(record);
        JSONObject before=fixtureState(instrumentation,activity,parent,fixture,service);record.put("before",before);
        requireFixture(before,geometry,stage+" before");
        JSONObject metadata=new JSONObject();record.put("frame",metadata);
        Bitmap bitmap=frame(instrumentation,service,control,hidden,false,metadata);
        try {
            File path=new File(directory,stage+".png");
            try(FileOutputStream stream=new FileOutputStream(path)) {
                require(bitmap.compress(Bitmap.CompressFormat.PNG,100,stream),"helper fixture PNG failed");
            }
            record.put("png",path.getName());
            JSONObject after=fixtureState(instrumentation,activity,parent,fixture,service);record.put("after",after);
            requireFixture(after,geometry,stage+" after");
            require("display".equals(metadata.getString("capture_scope")),"helper capture switched scope: "+metadata);
            Rect display=service.getSystemService(android.view.WindowManager.class).getCurrentWindowMetrics().getBounds();
            require(metadata.getInt("source_width")==display.width() && metadata.getInt("source_height")==display.height(),
                    "helper capture source geometry changed: "+metadata);
            return bitmap;
        } catch(Exception|Error failure) {bitmap.recycle();throw failure;}
    }
    private static void saveDiagnostic(File directory,JSONObject diagnostic) throws Exception {
        try(FileOutputStream stream=new FileOutputStream(new File(directory,"diagnostics.json"))) {
            stream.write(diagnostic.toString(2).getBytes(StandardCharsets.UTF_8));
        }
    }
    private static void awaitFixturePresentation(Instrumentation instrumentation,StaticCaptureBackground fixture,
                                                 JSONObject diagnostic) throws Exception {
        CountDownLatch committed=new CountDownLatch(1),subsequentVsyncs=new CountDownLatch(1);
        AtomicReference<Long> commitAt=new AtomicReference<>(),vsyncAt=new AtomicReference<>();
        long started=android.os.SystemClock.elapsedRealtime(),deadline=started+3000;
        JSONObject presentation=new JSONObject().put("requested_elapsed_ms",started).put("timeout_ms",3000)
                .put("required_subsequent_vsyncs",2);
        diagnostic.put("fixture_presentation",presentation);
        Runnable commit=()->{
            commitAt.set(android.os.SystemClock.elapsedRealtime());committed.countDown();
            fixture.postOnAnimation(()->fixture.postOnAnimation(()->{
                vsyncAt.set(android.os.SystemClock.elapsedRealtime());subsequentVsyncs.countDown();
            }));
        };
        onMain(instrumentation,()->{
            require(fixture.isAttachedToWindow() && fixture.isHardwareAccelerated(),"fixture requires attached hardware rendering");
            fixture.getViewTreeObserver().registerFrameCommitCallback(commit);
            // Commit a frame requested after the initial two draws; no screenshot is discarded.
            fixture.invalidate();
        });
        try {
            boolean commitObserved=committed.await(Math.max(0,deadline-android.os.SystemClock.elapsedRealtime()),TimeUnit.MILLISECONDS);
            presentation.put("commit_observed",commitObserved).put("commit_elapsed_ms",commitAt.get()==null?JSONObject.NULL:commitAt.get());
            require(commitObserved,"helper fixture did not commit a frame within 3000ms");
            boolean vsyncObserved=subsequentVsyncs.await(Math.max(0,deadline-android.os.SystemClock.elapsedRealtime()),TimeUnit.MILLISECONDS);
            presentation.put("subsequent_vsyncs_observed",vsyncObserved)
                    .put("vsync_elapsed_ms",vsyncAt.get()==null?JSONObject.NULL:vsyncAt.get())
                    .put("completed_elapsed_ms",android.os.SystemClock.elapsedRealtime());
            require(vsyncObserved,"helper fixture did not reach subsequent vsyncs within 3000ms");
        } finally {onMain(instrumentation,()->fixture.getViewTreeObserver().unregisterFrameCommitCallback(commit));}
    }
    private static void awaitHelperForeground(Instrumentation instrumentation,Activity activity,
                                              KardsAccessibilityService service,File directory,
                                              JSONObject diagnostic) throws Exception {
        JSONArray samples=new JSONArray();diagnostic.put("helper_admission_samples",samples)
                .put("helper_admission_timeout_ms",8000);
        long started=android.os.SystemClock.elapsedRealtime();boolean admitted=false;
        JSONObject last=null;
        do {
            AtomicReference<JSONObject> current=new AtomicReference<>();
            onMain(instrumentation,()->{
                try {
                    boolean alive=activity!=null && !activity.isDestroyed() && !activity.isFinishing();
                    current.set(new JSONObject().put("elapsed_ms",android.os.SystemClock.elapsedRealtime()-started)
                            .put("activity_alive",alive).put("activity_window_focus",alive && activity.hasWindowFocus())
                            .put("activity_shown",alive && activity.getWindow().getDecorView().isShown())
                            .put("same_service",KardsAccessibilityService.instance()==service)
                            .put("foreground_package",service.currentForegroundPackage()));
                } catch(Exception failure) {throw new AssertionError("helper foreground sample",failure);}
            });
            last=current.get();samples.put(last);
            admitted=last.getBoolean("activity_alive") && last.getBoolean("activity_window_focus")
                    && last.getBoolean("activity_shown") && last.getBoolean("same_service")
                    && service.getPackageName().equals(last.getString("foreground_package"));
            if(admitted)break;
            Thread.sleep(100);
        } while(android.os.SystemClock.elapsedRealtime()-started<8000);
        diagnostic.put("helper_admitted",admitted)
                .put("helper_admission_elapsed_ms",android.os.SystemClock.elapsedRealtime()-started);
        saveDiagnostic(directory,diagnostic);
        require(admitted,"helper Activity did not become focused own foreground within 8000ms: "+last);
    }
    private static JSONArray expandedButtons(Instrumentation instrumentation,GameFloatingControl control) {
        JSONArray measured=new JSONArray();
        onMain(instrumentation,()->{
            try {
                require(control.expandedForTest(),"button check requires expanded panel");
                ScrollView scroll=control.scrollForTest();
                require(scroll!=null && scroll.getWidth()>0 && scroll.getHeight()>0,"missing scroll viewport");
                Button[] buttons=control.buttonsForTest();require(buttons.length==4,"four expanded controls required");
                int commonHeight=-1;
                for(Button button:buttons) {
                    require(button!=null && button.isAttachedToWindow() && button.isClickable()
                            && button.hasOnClickListeners(),"button must retain its click control");
                    int minimum=Math.round(38*button.getResources().getDisplayMetrics().density);
                    int height=button.getHeight();
                    require(height>=minimum && height==button.getMeasuredHeight(),"button collapsed below 38dp: "+button.getText());
                    if(commonHeight<0)commonHeight=height;
                    require(height==commonHeight,"expanded controls have different row heights");
                    require(button.getLayout()!=null && button.getLineCount()==1,"button title wrapped or missing");
                    int textHeight=button.getLayout().getHeight();
                    int contentHeight=height-button.getCompoundPaddingTop()-button.getCompoundPaddingBottom();
                    int contentWidth=button.getWidth()-button.getCompoundPaddingLeft()-button.getCompoundPaddingRight();
                    require(textHeight<=contentHeight,"button title vertically clipped: "+button.getText());
                    require(button.getLayout().getEllipsisCount(0)==0
                            && button.getLayout().getLineWidth(0)<=contentWidth+1,"button title horizontally clipped: "+button.getText());
                    button.requestRectangleOnScreen(new Rect(0,0,button.getWidth(),height),true);
                    Rect visible=new Rect();
                    require(button.getGlobalVisibleRect(visible) && visible.height()>=height-1
                            && visible.width()>=button.getWidth()-1,"button cannot be fully scrolled into panel: "+button.getText());
                    measured.put(new JSONObject().put("title",button.getText()).put("width_px",button.getWidth())
                            .put("height_px",height).put("text_height_px",textHeight).put("content_height_px",contentHeight)
                            .put("visible_bounds",new JSONArray().put(visible.left).put(visible.top).put(visible.right).put(visible.bottom)));
                }
                scroll.scrollTo(0,0);
            } catch(Exception error) { throw new AssertionError("expanded button measurement",error); }
        });
        return measured;
    }
    static JSONObject platform(Instrumentation instrumentation,Activity activity,File outputDirectory,
                               JSONObject diagnostic) throws Exception {
        File artifacts=new File(outputDirectory,"floating-capture-check");
        require(artifacts.isDirectory() || artifacts.mkdirs(),"helper capture artifact directory");
        JSONArray captures=new JSONArray();diagnostic.put("captures",captures).put("helper_captures_only",true);
        boolean expectedAssertionCaught=false;
        try {onMain(instrumentation,()->{throw new AssertionError("expected_worker_assertion_probe");});}
        catch(AssertionError error) {expectedAssertionCaught="expected_worker_assertion_probe".equals(error.getMessage());}
        require(expectedAssertionCaught,"main assertion did not return to worker");
        KardsAccessibilityService service=KardsAccessibilityService.instance();
        for(int i=0;service==null && i<50;i++){Thread.sleep(100);service=KardsAccessibilityService.instance();}
        final KardsAccessibilityService connected=service;
        require(service!=null,"accessibility service required for overlay check");
        GameFloatingControl control=service.floatingControlForTest();require(control!=null,"missing overlay");
        awaitHelperForeground(instrumentation,activity,service,artifacts,diagnostic);
        AtomicReference<StaticCaptureBackground> fixture=new AtomicReference<>();
        AtomicReference<ViewGroup> fixtureParent=new AtomicReference<>();
        AtomicReference<Integer> requestedOrientation=new AtomicReference<>();
        Bitmap warmup=null,baseline=null,stableBaseline=null,compact=null,expanded=null;
        try {
            onMain(instrumentation,()->{
                require(activity!=null && !activity.isFinishing() && !activity.isDestroyed(),"helper Activity unavailable");
                requestedOrientation.set(activity.getRequestedOrientation());
                activity.setRequestedOrientation(android.content.pm.ActivityInfo.SCREEN_ORIENTATION_LOCKED);
                ViewGroup content=activity.findViewById(android.R.id.content);
                require(content!=null,"helper content unavailable");
                StaticCaptureBackground background=new StaticCaptureBackground(activity);
                fixture.set(background);fixtureParent.set(content);
                content.addView(background,new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.MATCH_PARENT));
            });
            instrumentation.waitForIdleSync();
            require(fixture.get().drawn.await(3,TimeUnit.SECONDS),"static background did not draw twice");
            instrumentation.waitForIdleSync();
            awaitFixturePresentation(instrumentation,fixture.get(),diagnostic);
            String geometry=fixtureGeometry(fixtureState(instrumentation,activity,fixtureParent.get(),fixture.get(),service));
            diagnostic.put("initial_geometry",geometry).put("original_requested_orientation",requestedOrientation.get())
                    .put("fixed_source_capture_count",5).put("fixed_warmup_capture_count",1)
                    .put("warmup_included_in_comparisons",false);
            warmup=fixtureFrame(instrumentation,activity,fixtureParent.get(),fixture.get(),service,control,false,
                    "warmup",geometry,artifacts,captures);
            baseline=fixtureFrame(instrumentation,activity,fixtureParent.get(),fixture.get(),service,control,false,
                    "baseline",geometry,artifacts,captures);
            stableBaseline=fixtureFrame(instrumentation,activity,fixtureParent.get(),fixture.get(),service,control,false,
                    "baseline-stable",geometry,artifacts,captures);
            onMain(instrumentation,()->control.showForTest(false));
            instrumentation.waitForIdleSync();Thread.sleep(200);
            onMain(instrumentation,()->{
                int id=control.windowIdForTest();require(id!=-1,"overlay window not attached");
                require(control.cachedWindowIdForTest()==id && control.ownsWindow(id),"visible attachment identity missing");
                require(!control.ownsWindow(id+100000) && !control.ownsWindow(-1),"unrelated window claimed as own");
            });
            compact=fixtureFrame(instrumentation,activity,fixtureParent.get(),fixture.get(),service,control,true,
                    "compact",geometry,artifacts,captures);
            onMain(instrumentation,()->control.showForTest(true));
            instrumentation.waitForIdleSync();Thread.sleep(200);
            JSONArray buttons=expandedButtons(instrumentation,control);
            expanded=fixtureFrame(instrumentation,activity,fixtureParent.get(),fixture.get(),service,control,true,
                    "expanded",geometry,artifacts,captures);
            AtomicReference<Rect> region=new AtomicReference<>(),display=new AtomicReference<>();
            onMain(instrumentation,()->{
                region.set(control.boundsForTest());
                display.set(connected.getSystemService(android.view.WindowManager.class).getCurrentWindowMetrics().getBounds());
            });
            // requestFrame normalizes the helper display to 1280x720. Sampling
            // must map the physical overlay rectangle into that bitmap space.
            Rect source=region.get(),screen=display.get();
            double scaleX=(double)expanded.getWidth()/screen.width(),scaleY=(double)expanded.getHeight()/screen.height();
            Rect r=new Rect(Math.max(0,(int)Math.floor(source.left*scaleX)),Math.max(0,(int)Math.floor(source.top*scaleY)),
                    Math.min(expanded.getWidth(),(int)Math.ceil(source.right*scaleX)),
                    Math.min(expanded.getHeight(),(int)Math.ceil(source.bottom*scaleY)));
            long sum=0,samples=0,backgroundSum=0,backgroundSamples=0,compactSum=0,expandedSum=0;
            require(r.width()>8 && r.height()>8,"normalized overlay sample region too small");
            require(expanded.getWidth()==1280 && expanded.getHeight()==720,"helper capture normalization changed");
            require(baseline.getWidth()==expanded.getWidth() && baseline.getHeight()==expanded.getHeight(),"capture size changed");
            require(stableBaseline.getWidth()==baseline.getWidth() && stableBaseline.getHeight()==baseline.getHeight(),"background capture size changed");
            for(int y=r.top+4;y<r.bottom-4;y+=3)for(int x=r.left+4;x<r.right-4;x+=3) {
                int a=baseline.getPixel(x,y),b=expanded.getPixel(x,y),c=compact.getPixel(x,y),d=stableBaseline.getPixel(x,y);
                for(int shift:new int[]{0,8,16}) {
                    backgroundSum+=Math.abs(((a>>shift)&255)-((d>>shift)&255));backgroundSamples++;
                    int expandedDelta=Math.abs(((a>>shift)&255)-((b>>shift)&255));
                    int compactDelta=Math.abs(((a>>shift)&255)-((c>>shift)&255));
                    expandedSum+=expandedDelta;compactSum+=compactDelta;
                    sum+=expandedDelta+compactDelta;samples+=2;
                }
            }
            double backgroundMean=(double)backgroundSum/backgroundSamples;
            double mean=(double)sum/samples;
            diagnostic.put("overlay_source_bounds",rect(source)).put("overlay_sample_bounds",rect(r))
                    .put("background_baseline_mean_pixel_delta",backgroundMean)
                    .put("compact_region_mean_pixel_delta",(double)compactSum/backgroundSamples)
                    .put("expanded_region_mean_pixel_delta",(double)expandedSum/backgroundSamples)
                    .put("combined_region_mean_pixel_delta",mean);
            require(backgroundMean<1.0,"static helper background changed between baselines: "+backgroundMean);
            require(mean<1.0,"control contaminated source pixels: "+mean);
            AtomicReference<Runnable> first=new AtomicReference<>(),second=new AtomicReference<>();
            CountDownLatch leases=new CountDownLatch(2);
            onMain(instrumentation,()->{
                control.withoutOverlay(release->{first.set(release);leases.countDown();});
                control.withoutOverlay(release->{second.set(release);leases.countDown();});
            });
            require(leases.await(2,TimeUnit.SECONDS),"hide leases not prepared");
            onMain(instrumentation,()->require(control.windowAlphaForTest()==0f && control.windowTouchBlockedForTest(),
                    "nested leases did not hide compositor and block touch"));
            onMain(instrumentation,()->{first.get().run();first.get().run();});instrumentation.waitForIdleSync();
            onMain(instrumentation,()->require(control.hiddenForTest() && control.windowAlphaForTest()==0f
                    && control.windowTouchBlockedForTest(),"first release restored nested lease"));
            onMain(instrumentation,()->second.get().run());instrumentation.waitForIdleSync();
            onMain(instrumentation,()->{
                require(!control.hiddenForTest(),"control not restored");
                require(control.windowAlphaForTest()==1f && !control.windowTouchBlockedForTest(),"final release did not restore compositor and touch");
                require(connected.currentForegroundPackage().equals(connected.getPackageName()),"overlay changed foreground");
                require(!connected.startFromFloatingControl(true),"started current battle outside KARDS");
                require(!connected.startFromFloatingControl(false),"started menu outside KARDS");
                require(!BattleWorkerLease.isOwned(),"negative starts acquired worker");
            });
            return new JSONObject().put("passed",true).put("source_capture_count",5)
                    .put("fixed_warmup_capture_count",1).put("warmup_included_in_comparisons",false)
                    .put("helper_capture_mode","normalized_display_1280x720")
                    .put("background_fixture","temporary_opaque_static_content_pattern")
                    .put("background_draws",fixture.get().drawCount).put("background_baseline_mean_pixel_delta",backgroundMean)
                    .put("helper_bitmap_shape",new JSONArray().put(expanded.getHeight()).put(expanded.getWidth()))
                    .put("overlay_source_bounds",new JSONArray().put(source.left).put(source.top).put(source.right).put(source.bottom))
                    .put("overlay_sample_bounds",new JSONArray().put(r.left).put(r.top).put(r.right).put(r.bottom))
                    .put("expanded_button_measurements",buttons)
                    .put("overlay_region_mean_pixel_delta",mean).put("nested_and_duplicate_release",true).put("main_assertion_returned_to_worker",true)
                    .put("window_alpha_and_touch_restored",true)
                    .put("non_game_start_refusals",2).put("game_launches",0).put("touches",0);
        } finally {
            if(warmup!=null)warmup.recycle();
            if(baseline!=null)baseline.recycle();if(stableBaseline!=null)stableBaseline.recycle();
            if(compact!=null)compact.recycle();if(expanded!=null)expanded.recycle();
            try {onMain(instrumentation,()->{
                try {
                    int oldId=control.cachedWindowIdForTest();control.restoreAfterTest();
                    require(control.cachedWindowIdForTest()==-1 && !control.ownsWindow(oldId),"detached overlay retained identity");
                } finally {
                    if(fixtureParent.get()!=null && fixture.get()!=null)fixtureParent.get().removeView(fixture.get());
                    if(requestedOrientation.get()!=null && !activity.isDestroyed())
                        activity.setRequestedOrientation(requestedOrientation.get());
                }
            });} finally {
                saveDiagnostic(artifacts,diagnostic);
            }
        }
    }

    static JSONObject gameForeground(Instrumentation instrumentation) throws Exception {
        KardsAccessibilityService candidate=KardsAccessibilityService.instance();
        for(int i=0;candidate==null && i<50;i++){Thread.sleep(100);candidate=KardsAccessibilityService.instance();}
        final KardsAccessibilityService service=candidate;require(service!=null,"service required");
        GameFloatingControl control=service.floatingControlForTest();
        AtomicReference<Long> generation=new AtomicReference<>();
        onMain(instrumentation,()->{
            require(service.currentForegroundPackage().equals("com.android1939.kards"),"game must be foreground");
            require(!BattleWorkerLease.isOwned(),"no battle worker during read-only UI check");
            generation.set(service.gameForegroundGeneration());control.showForTest(false);
        });
        instrumentation.waitForIdleSync();Thread.sleep(200);
        onMain(instrumentation,()->{
            require(service.currentForegroundPackage().equals("com.android1939.kards"),"collapsed control stole foreground");
            control.setExpanded(true);
        });
        instrumentation.waitForIdleSync();Thread.sleep(200);
        JSONArray buttons=expandedButtons(instrumentation,control);
        Bitmap b=null;
        try {
            b=frame(instrumentation,service,control,true,true);
            instrumentation.waitForIdleSync();
            onMain(instrumentation,()->{
                require(service.currentForegroundPackage().equals("com.android1939.kards"),"expanded control stole foreground");
                require(service.gameForegroundGeneration()==generation.get(),"overlay invalidated game admission generation");
                require(control.expandedForTest(),"capture collapsed panel");
                require(!BattleWorkerLease.isOwned(),"expanding or capturing automatically started a game");
            });
            return new JSONObject().put("passed",true).put("foreground_generation_unchanged",true)
                    .put("expanded_button_measurements",buttons)
                    .put("expanded_preserved",true).put("capture_hidden",true).put("game_inputs",0);
        } finally {if(b!=null)b.recycle();onMain(instrumentation,control::restoreAfterTest);}
    }
}
