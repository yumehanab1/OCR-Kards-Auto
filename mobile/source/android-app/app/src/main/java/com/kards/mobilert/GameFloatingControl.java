package com.kards.mobilert;

import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

/** Non-focusable accessibility overlay. Hide leases cover captures and input callbacks. */
final class GameFloatingControl {
    private final KardsAccessibilityService service;
    private final WindowManager windows;
    private final Handler main=new Handler(Looper.getMainLooper());
    private final FrameLayout root;
    private TextView compact, headline, details;
    private Button attach, start, stop;
    private boolean expanded, attached, destroyed, gameVisible;
    private int hidden;
    private String action="", message="";
    private long actionAt;
    private final Runnable tick=new Runnable() { public void run() {
        if(destroyed)return;
        update("com.android1939.kards".equals(service.currentForegroundPackage()));
        main.postDelayed(this,700);
    }};

    GameFloatingControl(KardsAccessibilityService service) {
        this.service=service; windows=service.getSystemService(WindowManager.class);
        root=new FrameLayout(service); root.setElevation(dp(5));
        rebuild(); main.post(tick);
    }
    private int dp(int n) { return Math.round(n*service.getResources().getDisplayMetrics().density); }
    static Rect bounds(int w,int h,float density,boolean expanded) {
        int width=Math.min(Math.round((expanded?270:86)*density),Math.round(w*(expanded?.26f:.085f)));
        int height=Math.min(Math.round((expanded?240:86)*density),Math.round(h*(expanded?.40f:.16f)));
        // The confirmed end label sits at y≈.667 on the current long-screen layout;
        // standard layouts use the higher control. Keep a gap above either.
        int bottom=Math.round(h*((float)w/h>=2.1f?.60f:.43f));
        return new Rect(w-width,Math.max(0,bottom-height),w,bottom);
    }
    private WindowManager.LayoutParams layout() {
        Rect screen=windows.getCurrentWindowMetrics().getBounds();
        Rect area=bounds(screen.width(),screen.height(),service.getResources().getDisplayMetrics().density,expanded);
        WindowManager.LayoutParams p=new WindowManager.LayoutParams(area.width(),area.height(),
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN, PixelFormat.TRANSLUCENT);
        p.gravity=Gravity.TOP|Gravity.RIGHT; p.x=0; p.y=area.top;
        p.setTitle("KARDS局内控制"); return p;
    }
    private TextView text(int size) {
        TextView v=new TextView(service);v.setTextColor(Color.WHITE);v.setTextSize(size);
        return v;
    }
    private Button button(String title,Runnable callback) {
        Button b=new Button(service);b.setText(title);b.setTextSize(12);b.setAllCaps(false);
        b.setMinHeight(0);b.setMinimumHeight(0);b.setPadding(dp(4),0,dp(4),0);
        b.setOnClickListener(v->callback.run()); return b;
    }
    private void rebuild() {
        root.removeAllViews();
        GradientDrawable background=new GradientDrawable();background.setColor(Color.rgb(25,35,45));
        background.setCornerRadius(dp(12));background.setStroke(dp(1),Color.rgb(90,115,130));root.setBackground(background);
        if(!expanded) {
            compact=text(11);compact.setGravity(Gravity.CENTER);compact.setPadding(dp(3),dp(2),dp(3),dp(2));
            compact.setOnClickListener(v->setExpanded(true));root.addView(compact);
        } else {
            ScrollView scroll=new ScrollView(service);LinearLayout column=new LinearLayout(service);
            column.setOrientation(LinearLayout.VERTICAL);column.setPadding(dp(8),dp(5),dp(8),dp(5));
            headline=text(13);details=text(11);column.addView(headline);column.addView(details);
            LinearLayout row=new LinearLayout(service);
            attach=button("接管当前局",()->start(true));stop=button("停止",service::cancelBattle);
            row.addView(attach,new LinearLayout.LayoutParams(0,dp(38),1));
            row.addView(stop,new LinearLayout.LayoutParams(0,dp(38),1));column.addView(row);
            start=button("从菜单开局",()->start(false));column.addView(start);
            column.addView(button("收起 ›",()->setExpanded(false)));
            scroll.addView(column);root.addView(scroll);
        }
    }
    private void start(boolean currentBattle) {
        message=service.startFromFloatingControl(currentBattle)?"":BattleStartAttempt.userMessage(service.lastStartAttempt());
        update(gameVisible);
    }
    void setExpanded(boolean value) {
        expanded=value;message="";rebuild();if(attached)windows.updateViewLayout(root,layout());update(gameVisible);
    }
    void noteAction(String context) { action=FloatingStatus.action(context);actionAt=SystemClock.elapsedRealtime(); }
    void update(boolean visible) {
        if(destroyed)return;gameVisible=visible;
        FloatingStatus state=FloatingStatus.from(service.battleProgressReport(),
                SystemClock.elapsedRealtime()-actionAt<3000?action:"");
        if(expanded) {
            headline.setText((state.active?"● 运行中":"● 已停止")+" · "+state.phase);
            details.setText(state.detail+(message.isEmpty()?"":"\n"+message));
            boolean busy=BattleWorkerLease.isOwned();attach.setEnabled(!busy);start.setEnabled(!busy);stop.setEnabled(busy);
        } else {compact.setText(state.compact);compact.setTextColor(state.active?Color.rgb(136,236,179):Color.rgb(250,217,150));}
        if(attached) {
            WindowManager.LayoutParams old=(WindowManager.LayoutParams)root.getLayoutParams(),next=layout();
            if(old.width!=next.width || old.height!=next.height || old.y!=next.y)windows.updateViewLayout(root,next);
        }
        if(visible&&!attached) {
            try { root.setVisibility(hidden>0?View.INVISIBLE:View.VISIBLE);windows.addView(root,layout());attached=true; }
            catch(RuntimeException e) { android.util.Log.w("KardsOverlay","Cannot attach control",e); }
        } else if(!visible&&attached) {windows.removeView(root);attached=false;}
        if(attached)root.setVisibility(hidden>0?View.INVISIBLE:View.VISIBLE);
    }
    private int windowId() {
        android.view.accessibility.AccessibilityNodeInfo node=root.createAccessibilityNodeInfo();
        try {return node.getWindowId();} finally {node.recycle();}
    }
    boolean ownsWindow(int id) { return attached && id!=-1 && id==windowId(); }
    void withoutOverlay(Consumer<Runnable> work) {
        // A lease is idempotent and nested captures/inputs cannot restore each other's overlay.
        boolean wait=attached;hidden++;if(attached)root.setVisibility(View.INVISIBLE);
        AtomicBoolean released=new AtomicBoolean();
        Runnable release=()->{
            if(!released.compareAndSet(false,true))return;
            main.post(()->{hidden--;if(!destroyed)update(gameVisible);});
        };
        main.postDelayed(release,10_000); // missing system callback cannot leave controls permanently hidden
        Runnable begin=()->{try{work.accept(release);}catch(RuntimeException e){release.run();throw e;}};
        // Visibility must reach SurfaceFlinger before screenshot or gesture submission.
        if(wait)main.postDelayed(begin,80);else begin.run();
    }
    void destroy() { destroyed=true;main.removeCallbacks(tick);if(attached){windows.removeView(root);attached=false;} }
    // Device tests use the real window manager without launching or touching the game.
    void showForTest(boolean expanded) { setExpanded(expanded);update(true);main.removeCallbacks(tick); }
    boolean hiddenForTest() { return hidden>0 && root.getVisibility()!=View.VISIBLE; }
    boolean expandedForTest() { return expanded; }
    int windowIdForTest() { return windowId(); }
    void restoreAfterTest() { update(false);main.post(tick); }
    Rect boundsForTest() { WindowManager.LayoutParams p=layout();Rect s=windows.getCurrentWindowMetrics().getBounds();return new Rect(s.width()-p.width,p.y,s.width(),p.y+p.height); }
}
