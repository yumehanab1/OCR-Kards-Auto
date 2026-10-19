package com.kards.mobilert;

import android.accessibilityservice.AccessibilityService;
import android.graphics.Bitmap;
import android.hardware.HardwareBuffer;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Display;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicBoolean;

/** Debug-only, zero-input capture comparison. Never starts a campaign or dispatches a gesture. */
final class DebugScreenshotAudit {
    private static final AtomicBoolean RUNNING = new AtomicBoolean();
    private final KardsAccessibilityService service;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final File directory;
    private final GameFloatingControl control;
    private final boolean wasExpanded;
    private boolean finished;
    private int index;

    static String start(KardsAccessibilityService service) throws Exception {
        if (BattleWorkerLease.isOwned() || new JSONObject(service.battleProgressReport()).optBoolean("active"))
            throw new IllegalStateException("capture_audit_requires_inactive");
        if (!GamePackages.isGame(service.currentForegroundPackage()))
            throw new IllegalStateException("capture_audit_requires_game_foreground");
        if (!RUNNING.compareAndSet(false, true)) throw new IllegalStateException("capture_audit_busy");
        try {
            DebugScreenshotAudit audit = new DebugScreenshotAudit(service);
            audit.main.post(audit::next);
            return new JSONObject().put("started",true).put("directory",audit.directory.getAbsolutePath())
                    .put("game_inputs",0).toString();
        } catch (Exception error) { RUNNING.set(false); throw error; }
    }

    private DebugScreenshotAudit(KardsAccessibilityService service) throws Exception {
        this.service=service;control=service.floatingControlForTest();
        wasExpanded=control!=null && control.expandedForTest();
        directory=new File(service.getFilesDir(),"capture-audit/"+System.currentTimeMillis());
        if (!directory.mkdirs()) throw new IllegalStateException("capture_audit_directory");
        if(control!=null)control.showForTest(false); // Freeze polling; each mode owns its window state.
        main.postDelayed(()->finish("capture_audit_timeout"),60000);
    }
    private void next() {
        if(finished)return;
        if(index>=18){finish("");return;}
        if(BattleWorkerLease.isOwned() || !GamePackages.isGame(service.currentForegroundPackage())) {
            finish("foreground_or_worker_changed");return;
        }
        final int number=++index;
        final String mode=number<=6?"visible":number<=12?"hidden":"detached";
        if(control!=null && number==13)control.update(false);
        if("hidden".equals(mode) && control!=null)control.withoutOverlay(release->capture(number,mode,release));
        else capture(number,mode,()->{});
    }
    private void capture(int number,String mode,Runnable release) {
        final long requested=SystemClock.elapsedRealtime();
        try {service.takeScreenshot(Display.DEFAULT_DISPLAY,service.getMainExecutor(),new AccessibilityService.TakeScreenshotCallback(){
            @Override public void onFailure(int code) {
                release.run();
                try {save(number,new JSONObject().put("mode",mode).put("error",code));}
                catch(Exception ignored){}
                main.postDelayed(DebugScreenshotAudit.this::next,700);
            }
            @Override public void onSuccess(AccessibilityService.ScreenshotResult shot) {
                final HardwareBuffer buffer=shot.getHardwareBuffer();
                if(finished){if(buffer!=null)buffer.close();release.run();return;}
                Bitmap wrapped=null;
                try {
                    final long callback=SystemClock.elapsedRealtime();
                    wrapped=Bitmap.wrapHardwareBuffer(buffer,shot.getColorSpace());
                    if(wrapped==null)throw new IllegalStateException("wrap_failed");
                    final Bitmap hardware=wrapped;
                    final JSONObject row=new JSONObject().put("number",number).put("mode",mode)
                            .put("requested_elapsed_ms",requested).put("callback_elapsed_ms",callback)
                            .put("platform_timestamp_ms",shot.getTimestamp())
                            .put("buffer_format",buffer.getFormat()).put("buffer_usage",buffer.getUsage())
                            .put("width",buffer.getWidth()).put("height",buffer.getHeight())
                            .put("color_space",String.valueOf(shot.getColorSpace()));
                    copy(number,"immediate",hardware,row);
                    main.postDelayed(()->{
                        try {
                            copy(number,"delayed100",hardware,row);
                            row.put("completed_elapsed_ms",SystemClock.elapsedRealtime());save(number,row);
                        } catch(Exception error){finish(error.toString());}
                        finally {hardware.recycle();buffer.close();release.run();}
                        if(!finished)main.postDelayed(DebugScreenshotAudit.this::next,700);
                    },100);
                } catch(Exception error){
                    if(wrapped!=null)wrapped.recycle();if(buffer!=null)buffer.close();release.run();finish(error.toString());
                }
            }
        });} catch(RuntimeException error){release.run();finish(error.toString());}
    }
    private void copy(int number,String label,Bitmap hardware,JSONObject row) throws Exception {
        long started=SystemClock.elapsedRealtime();
        Bitmap software=hardware.copy(Bitmap.Config.ARGB_8888,false);
        if(software==null)throw new IllegalStateException("copy_failed");
        try {
            int[] pixels=new int[software.getWidth()*software.getHeight()];
            software.getPixels(pixels,0,software.getWidth(),0,0,software.getWidth(),software.getHeight());
            int nonblack=0,minAlpha=255,maxAlpha=0;
            for(int pixel:pixels){if((pixel&0xffffff)!=0)nonblack++;int alpha=pixel>>>24;minAlpha=Math.min(minAlpha,alpha);maxAlpha=Math.max(maxAlpha,alpha);}
            row.put(label,new JSONObject().put("nonblack_pixels",nonblack).put("alpha_min",minAlpha)
                    .put("alpha_max",maxAlpha).put("elapsed_ms",SystemClock.elapsedRealtime()-started));
            try(FileOutputStream output=new FileOutputStream(new File(directory,String.format(java.util.Locale.ROOT,"%02d-%s.png",number,label)))){OriginalPng.write(software,output);}
        } finally {software.recycle();}
    }
    private void save(int number,JSONObject row) throws Exception {
        try(FileOutputStream output=new FileOutputStream(new File(directory,String.format(java.util.Locale.ROOT,"%02d.json",number)))) {
            output.write(row.toString(2).getBytes(StandardCharsets.UTF_8));
        }
    }
    private void finish(String error) {
        if(finished)return;
        finished=true;RUNNING.set(false);
        try {save(0,new JSONObject().put("finished",true).put("error",error).put("game_inputs",0).put("frames",index));}
        catch(Exception ignored){}
        if(control!=null){control.setExpanded(wasExpanded);control.restoreAfterTest();}
    }
}
