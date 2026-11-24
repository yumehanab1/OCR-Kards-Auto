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
    private Button attach, start, stop, collapse;
    private ScrollView expandedScroll;
    private LinearLayout actionButtons;
    private boolean expanded, destroyed, gameVisible;
    private volatile boolean attached;
    private volatile int attachedWindowId=-1;
    private volatile Rect attachedBounds;
    private int hidden;
    private String action="", message="";
    private long actionAt;
    private final Runnable tick=new Runnable() { public void run() {
        if(destroyed)return;
        update(GamePackages.isGame(service.currentForegroundPackage()));
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
        Rect screen=DisplayBounds.get(windows);
        Rect area=bounds(screen.width(),screen.height(),service.getResources().getDisplayMetrics().density,expanded);
        WindowManager.LayoutParams p=new WindowManager.LayoutParams(area.width(),area.height(),
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                        | (hidden>0?WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE:0), PixelFormat.TRANSLUCENT);
        // Keep the attached View visible so hiding does not tear down its Surface.
        // Window alpha and touch flags hide the compositor layer and block input.
        p.alpha=hidden>0?0f:1f;
        p.gravity=Gravity.TOP|Gravity.RIGHT; p.x=0; p.y=area.top;
        p.setTitle("KARDS局内控制"); return p;
    }
    private TextView text(int size) {
        TextView v=new TextView(service);v.setTextColor(Color.WHITE);v.setTextSize(size);
        return v;
    }
    private Button button(String title,Runnable callback) {
        Button b=new Button(service);b.setText(title);b.setTextSize(12);b.setAllCaps(false);
        b.setSingleLine(true);b.setGravity(Gravity.CENTER);b.setPadding(dp(4),0,dp(4),0);
        android.graphics.Paint.FontMetricsInt font=b.getPaint().getFontMetricsInt();
        int height=Math.max(dp(38),font.bottom-font.top+dp(12));
        b.setMinHeight(height);b.setMinimumHeight(height);
        // All four controls need an explicit row height. WRAP_CONTENT combined
        // with platform Button insets collapsed the two standalone controls.
        b.setLayoutParams(new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,height));
        b.setOnClickListener(v->callback.run()); return b;
    }
    private void arrangeActionButtons() {
        if(actionButtons==null || attach==null || stop==null)return;
        int contentWidth=Math.max(0,layout().width-2*dp(8));
        int halfWidth=contentWidth/2;
        boolean twoColumns=true;
        for(Button button:new Button[]{attach,stop}) {
            int titleWidth=(int)Math.ceil(button.getPaint().measureText(button.getText().toString()));
            int required=titleWidth+button.getCompoundPaddingLeft()+button.getCompoundPaddingRight()+2;
            if(required>halfWidth)twoColumns=false;
        }
        actionButtons.setOrientation(twoColumns?LinearLayout.HORIZONTAL:LinearLayout.VERTICAL);
        int height=attach.getLayoutParams().height;
        for(Button button:new Button[]{attach,stop})button.setLayoutParams(new LinearLayout.LayoutParams(
                twoColumns?0:LinearLayout.LayoutParams.MATCH_PARENT,height,twoColumns?1:0));
    }
     private void rebuild() {
         root.removeAllViews();actionButtons=null;
         GradientDrawable background=new GradientDrawable();background.setColor(Color.argb(230,24,38,28));
         background.setCornerRadius(dp(12));background.setStroke(dp(1),Color.rgb(55,82,60));root.setBackground(background);
         if(!expanded) {
             compact=text(11);compact.setGravity(Gravity.CENTER);compact.setPadding(dp(4),dp(3),dp(4),dp(3));
             compact.setOnClickListener(v->setExpanded(true));root.addView(compact);
         } else {
             ScrollView scroll=new ScrollView(service);LinearLayout column=new LinearLayout(service);
             expandedScroll=scroll;
             column.setOrientation(LinearLayout.VERTICAL);column.setPadding(dp(10),dp(8),dp(10),dp(6));
             headline=text(13);headline.setTypeface(android.graphics.Typeface.create("sans-serif-medium",android.graphics.Typeface.NORMAL));
             details=text(11);details.setTextColor(Color.rgb(175,195,170));details.setLineSpacing(dp(2),1);
             column.addView(headline);column.addView(details);
             actionButtons=new LinearLayout(service);
             attach=button("接管当前局",()->start(true));stop=button("停止",service::cancelBattle);
             actionButtons.addView(attach);actionButtons.addView(stop);arrangeActionButtons();
             column.addView(actionButtons,new LinearLayout.LayoutParams(
                     LinearLayout.LayoutParams.MATCH_PARENT,LinearLayout.LayoutParams.WRAP_CONTENT));
             start=button("从菜单开局",()->start(false));column.addView(start);
             collapse=button("收起 ↑",()->setExpanded(false));
             collapse.setTextSize(11);collapse.setAllCaps(false);collapse.setGravity(Gravity.CENTER);
             collapse.setTextColor(Color.rgb(140,170,145));collapse.setPadding(dp(4),dp(6),dp(4),dp(6));
             collapse.setBackground(new android.graphics.drawable.ColorDrawable(Color.TRANSPARENT));
             column.addView(collapse,new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,-2));
             scroll.addView(column,new ScrollView.LayoutParams(ScrollView.LayoutParams.MATCH_PARENT,ScrollView.LayoutParams.WRAP_CONTENT));
             root.addView(scroll,new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,FrameLayout.LayoutParams.MATCH_PARENT));
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
    private void updateViewAlpha() {
        float alpha=hidden>0?0f:1f;
        if(root.getAlpha()!=alpha) {root.setAlpha(alpha);root.invalidate();}
    }
    void update(boolean visible) {
        if(destroyed)return;gameVisible=visible;
        updateViewAlpha();
        FloatingStatus state=FloatingStatus.from(service.battleProgressReport(),
                SystemClock.elapsedRealtime()-actionAt<3000?action:"");
         if(expanded) {
             headline.setTextColor(state.active?Color.rgb(152,230,180):Color.rgb(180,195,178));
             headline.setText((state.active?"● 运行中":"● 已停止")+" · "+state.phase);
             details.setText(state.detail+(message.isEmpty()?"":" \n"+message));
             boolean busy=BattleWorkerLease.isOwned();attach.setEnabled(!busy);start.setEnabled(!busy);stop.setEnabled(busy);
         } else {compact.setText(state.compact);compact.setTextColor(state.active?Color.rgb(152,230,180):Color.rgb(245,208,120));}
        if(attached) {
            WindowManager.LayoutParams old=(WindowManager.LayoutParams)root.getLayoutParams(),next=layout();
            if(old.width!=next.width || old.height!=next.height || old.y!=next.y
                    || old.alpha!=next.alpha || old.flags!=next.flags) {
                if(expanded)arrangeActionButtons();windows.updateViewLayout(root,next);
            }
        }
        if(visible&&!attached) {
            try {
                attachedWindowId=-1;root.setVisibility(View.VISIBLE);
                windows.addView(root,layout());attached=true;rememberWindowId();root.post(this::rememberWindowId);
            }
            catch(RuntimeException e) { android.util.Log.w("KardsOverlay","Cannot attach control",e); }
        } else if(!visible&&attached) {windows.removeView(root);attached=false;attachedWindowId=-1;attachedBounds=null;}
        if(attached)rememberWindowId();
    }
    private int windowId() {
        android.view.accessibility.AccessibilityNodeInfo node=root.createAccessibilityNodeInfo();
        try {return node.getWindowId();} finally {node.recycle();}
    }
    private void rememberWindowId() {
        // Alpha-only hiding retains the visible View and its accessibility identity.
        if(!attached || root.getVisibility()!=View.VISIBLE)return;
        int id=windowId();if(id>=0)attachedWindowId=id;
        if(root.getWidth()>0 && root.getHeight()>0) {
            int[] position=new int[2];root.getLocationOnScreen(position);
            attachedBounds=new Rect(position[0],position[1],position[0]+root.getWidth(),position[1]+root.getHeight());
        }
    }
    boolean ownsWindow(int id) { return attached && id!=-1 && id==attachedWindowId; }
    boolean ownsWindow(int id,int type,String owner,Rect area) {
        if(ownsWindow(id))return true;
        Rect actual=attachedBounds;
        // ID registration may lag on phones. Owner alone or geometry alone is
        // insufficient: require our exact owner, overlay type AND attached View bounds.
        return matchesAttachedOverlay(attached,type,service.getPackageName().equals(owner),actual,area);
    }
    static boolean matchesAttachedOverlay(boolean attached,int type,boolean ownOwner,Rect actual,Rect area) {
        return attached && type==android.view.accessibility.AccessibilityWindowInfo.TYPE_ACCESSIBILITY_OVERLAY
                && ownOwner && actual!=null && actual.equals(area);
    }
    void withoutOverlay(Consumer<Runnable> work) {
        // A lease is idempotent and nested captures/inputs cannot restore each other's overlay.
        boolean wait=attached,firstLease=hidden==0;rememberWindowId();hidden++;
        class HideLease implements Runnable {
            final AtomicBoolean released=new AtomicBoolean();
            @Override public void run() {
                if(!released.compareAndSet(false,true))return;
                main.removeCallbacks(this);
                main.post(()->{hidden--;if(hidden==0 && !destroyed)update(gameVisible);});
            }
        }
        HideLease release=new HideLease();
        main.postDelayed(release,10_000); // missing system callback cannot leave controls permanently hidden
        try {
            if(firstLease) {
                // Also clear the rendered View content; WindowManager alpha alone
                // may not be reflected by a display screenshot on every emulator.
                updateViewAlpha();
                if(attached)windows.updateViewLayout(root,layout());
            }
        } catch(RuntimeException error) {release.run();throw error;}
        Runnable begin=()->{try{work.accept(release);}catch(RuntimeException e){release.run();throw e;}};
        // Window alpha and touch flags must reach SurfaceFlinger before submission.
        if(wait)main.postDelayed(begin,80);else begin.run();
    }
    void destroy() { destroyed=true;main.removeCallbacks(tick);if(attached){windows.removeView(root);attached=false;}attachedWindowId=-1;attachedBounds=null; }
    // Device tests use the real window manager without launching or touching the game.
    void showForTest(boolean expanded) { setExpanded(expanded);update(true);main.removeCallbacks(tick); }
    boolean hiddenForTest() { return hidden>0 && attached && root.getAlpha()==0f && windowAlphaForTest()==0f && windowTouchBlockedForTest(); }
    float viewAlphaForTest() { return root.getAlpha(); }
    boolean viewVisibleForTest() { return root.getVisibility()==View.VISIBLE; }
    boolean attachedForTest() { return attached && root.isAttachedToWindow(); }
    float windowAlphaForTest() { return ((WindowManager.LayoutParams)root.getLayoutParams()).alpha; }
    boolean windowTouchBlockedForTest() {
        return (((WindowManager.LayoutParams)root.getLayoutParams()).flags&WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE)!=0;
    }
    boolean expandedForTest() { return expanded; }
    int windowIdForTest() { return windowId(); }
    int cachedWindowIdForTest() { return attachedWindowId; }
    Button[] buttonsForTest() { return new Button[]{attach,stop,start,collapse}; }
    ScrollView scrollForTest() { return expandedScroll; }
    void restoreAfterTest() { update(false);main.post(tick); }
    Rect boundsForTest() { WindowManager.LayoutParams p=layout();Rect s=DisplayBounds.get(windows);return new Rect(s.width()-p.width,p.y,s.width(),p.y+p.height); }
}
