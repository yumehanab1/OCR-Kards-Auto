package com.kards.mobilert;

import android.app.Activity;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/** Presentation only. Creating or refreshing this view never starts a session. */
final class TrainingDashboard {
    interface Actions {
        void start(String mode, boolean openGame, int matchCount);
        void modeChanged(String mode);
        void matchCountChanged(int matchCount);
        void stop();
        void permissions();
        void details();
    }

    private static final int PAPER = Color.rgb(245, 245, 239);
    private static final int INK = Color.rgb(32, 47, 40);
    private static final int MUTED = Color.rgb(107, 116, 106);
    private static final int LINE = Color.rgb(224, 229, 218);
    private static final int OLIVE = Color.rgb(41, 62, 48);
    private static final int GOLD = Color.rgb(222, 194, 119);
    private final Activity activity;
    private final Actions actions;
    private final ScrollView scroll;
    private final boolean wide;
    final LinearLayout diagnostics;
    private final TextView heroTitle, heroBody, readiness, gameValue, serviceValue;
    private final TextView gameSymbol, serviceSymbol, resultTitle, resultBody, resultPill;
    private final TextView duration, turns, actionsCount, recordDate;
    private final Button start, manualStart, stop, settings, details, diagnosticsToggle, casual, ranked;
    private final EditText matchCountInput;
    private boolean diagnosticsOpen;
    private String selectedMode = "casual";
    private int selectedMatchCount = 1;
    private boolean primaryCanStart;
    private boolean entryAvailable;
    private boolean manualEntryAvailable;
    private boolean editingCount;
    private String countText = "1";
    private boolean permissionRequired = true;

    TrainingDashboard(Activity activity, Actions actions, String version) {
        this.activity = activity;
        this.actions = actions;
        wide = activity.getResources().getConfiguration().screenWidthDp >= 760
                && activity.getResources().getConfiguration().fontScale < 1.35f;
        scroll = new ScrollView(activity);
        scroll.setBackgroundColor(PAPER);
        scroll.setFillViewport(true);
        scroll.setClipToPadding(true);
        scroll.setOnApplyWindowInsetsListener((v, insets) -> {
            android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars()
                    | WindowInsets.Type.displayCutout());
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return insets;
        });
        LinearLayout root = column();
        int margin = wide ? 32 : 20;
        root.setPadding(dp(margin), dp(wide ? 20 : 16), dp(margin), dp(20));
        scroll.addView(root);

        LinearLayout header = row();
        ImageView mark = new ImageView(activity);
        mark.setImageResource(R.drawable.ic_panel_mark);
        mark.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        header.addView(mark, new LinearLayout.LayoutParams(dp(42), dp(42)));
        LinearLayout brand = column();
        TextView name = text("KARDS 对战助手", 19, INK, true);
        brand.addView(name);
        TextView subtitle = text("休闲与排位，尽在一处", 12, MUTED, false);
        add(brand, subtitle, 3);
        LinearLayout.LayoutParams brandParams = new LinearLayout.LayoutParams(0, -2, 1);
        brandParams.setMarginStart(dp(12));
        header.addView(brand, brandParams);
        TextView versionTag = text("v" + version, 11, MUTED, false);
        versionTag.setPadding(dp(10), dp(6), dp(10), dp(6));
        versionTag.setBackground(shape(Color.rgb(235, 238, 229), 20, 0));
        header.addView(versionTag);
        add(root, header, 0);

        LinearLayout workspace = wide ? row() : column();
        workspace.setGravity(Gravity.TOP);
        LinearLayout hero = card(OLIVE, 24);
        LinearLayout heroTop = row();
        TextView eyebrow = text("对战控制台", 12, GOLD, true);
        heroTop.addView(eyebrow, new LinearLayout.LayoutParams(0, -2, 1));
        readiness = text("●  检查运行环境", 11, Color.rgb(215, 229, 205), false);
        heroTop.addView(readiness);
        hero.addView(heroTop);
        heroTitle = text("准备好下一场对战", wide ? 29 : 27, Color.WHITE, true);
        add(hero, heroTitle, 22);
        heroBody = text(idleDescription(), 14,
                Color.rgb(211, 220, 206), false);
        heroBody.setLineSpacing(dp(4), 1);
        add(hero, heroBody, 10);
        LinearLayout modes = row();
        casual = button("休闲对局", OLIVE, Color.WHITE, Color.rgb(115, 134, 113));
        casual.setTag("panel_mode_casual");
        ranked = button("排位对战", OLIVE, Color.WHITE, Color.rgb(115, 134, 113));
        ranked.setTag("panel_mode_ranked");
        casual.setOnClickListener(v -> selectModeFromUser("casual", casual));
        ranked.setOnClickListener(v -> selectModeFromUser("ranked", ranked));
        modes.addView(casual, new LinearLayout.LayoutParams(0, -2, 1));
        LinearLayout.LayoutParams rankedParams = new LinearLayout.LayoutParams(0, -2, 1);
        rankedParams.setMarginStart(dp(10));
        modes.addView(ranked, rankedParams);
        add(hero, modes, 21);
        LinearLayout matchCounts = row();
        TextView countLabel = text(activity.getString(R.string.match_count_label), 14, Color.WHITE, true);
        matchCounts.addView(countLabel, new LinearLayout.LayoutParams(-2, -2));
        matchCountInput = new EditText(activity);
        matchCountInput.setTag("panel_match_count");
        matchCountInput.setSingleLine(true);
        // Offer a numeric keyboard without a DigitsKeyListener that silently
        // strips signs/decimal points from pasted invalid input.
        matchCountInput.setRawInputType(InputType.TYPE_CLASS_NUMBER);
        matchCountInput.setSaveEnabled(false); // MainActivity preserves the raw draft explicitly.
        matchCountInput.setTextSize(16);
        matchCountInput.setTextColor(INK);
        matchCountInput.setPadding(dp(14), dp(8), dp(14), dp(8));
        matchCountInput.setMinHeight(dp(48));
        matchCountInput.setBackground(shape(Color.rgb(245, 245, 239), 11, 0));
        matchCountInput.setContentDescription(activity.getString(R.string.match_count_accessibility));
        matchCountInput.setText(countText);
        LinearLayout.LayoutParams countParams = new LinearLayout.LayoutParams(0, -2, 1);
        countParams.setMarginStart(dp(14));
        matchCounts.addView(matchCountInput, countParams);
        add(hero, matchCounts, 12);
        add(hero, text(activity.getString(R.string.match_count_hint), 11,
                Color.rgb(179, 195, 173), false), 7);
        LinearLayout controls = row();
        start = button("开始休闲辅助", GOLD, INK, 0);
        start.setId(R.id.panel_start);
        start.setEnabled(false);
        start.setOnClickListener(v -> {
            if (!start.isEnabled()) return;
            if (permissionRequired) actions.permissions();
            else if (primaryCanStart && validMatchCount()) actions.start(selectedMode, true, selectedMatchCount());
        });
        controls.addView(start, new LinearLayout.LayoutParams(0, -2, 1));
        stop = button("停止", OLIVE, Color.rgb(224, 231, 218), Color.rgb(115, 134, 113));
        stop.setId(R.id.panel_stop);
        stop.setOnClickListener(v -> actions.stop());
        LinearLayout.LayoutParams stopParams = new LinearLayout.LayoutParams(dp(88), -2);
        stopParams.setMarginStart(dp(10));
        controls.addView(stop, stopParams);
        add(hero, controls, 22);
        manualStart = button("仅启动辅助 · 手动打开游戏", OLIVE, Color.rgb(224, 231, 218), Color.rgb(115, 134, 113));
        manualStart.setTag("panel_manual_start");
        manualStart.setEnabled(false);
        manualStart.setOnClickListener(v -> {
            if (!manualStart.isEnabled()) return;
            if (permissionRequired) actions.permissions();
            else if (manualEntryAvailable && validMatchCount()) actions.start(selectedMode, false, selectedMatchCount());
        });
        add(hero, manualStart, 10);
        TextView stopHint = text("进入游戏后，返回此面板或切出游戏会停止操作", 11,
                Color.rgb(179, 195, 173), false);
        add(hero, stopHint, 10);

        LinearLayout preparation = card(Color.WHITE, 22);
        preparation.addView(text("运行准备", 17, INK, true));
        add(preparation, text("首次使用，只需完成以下准备", 12, MUTED, false), 6);
        LinearLayout gameRow = readinessRow("KARDS", "检查游戏安装情况");
        gameSymbol = (TextView) gameRow.getChildAt(0);
        gameValue = (TextView) ((LinearLayout) gameRow.getChildAt(1)).getChildAt(1);
        add(preparation, gameRow, 23);
        add(preparation, divider(), 16);
        LinearLayout serviceRow = readinessRow("无障碍权限", "用于识别画面和执行操作");
        serviceSymbol = (TextView) serviceRow.getChildAt(0);
        serviceValue = (TextView) ((LinearLayout) serviceRow.getChildAt(1)).getChildAt(1);
        serviceValue.setId(R.id.panel_service_state);
        add(preparation, serviceRow, 16);
        settings = button("管理权限", Color.rgb(239, 242, 233), OLIVE, 0);
        settings.setId(R.id.panel_permissions);
        settings.setOnClickListener(v -> actions.permissions());
        add(preparation, settings, 22);

        if (wide) {
            workspace.addView(hero, new LinearLayout.LayoutParams(0, -2, 1.65f));
            LinearLayout.LayoutParams readyParams = new LinearLayout.LayoutParams(0, -2, 1);
            readyParams.setMarginStart(dp(18));
            workspace.addView(preparation, readyParams);
        } else {
            workspace.addView(hero, new LinearLayout.LayoutParams(-1, -2));
            add(workspace, preparation, 14);
        }
        add(root, workspace, 24);

        LinearLayout result = card(Color.WHITE, 22);
        LinearLayout resultHeader = row();
        resultHeader.addView(text("最近运行", 17, INK, true), new LinearLayout.LayoutParams(0, -2, 1));
        recordDate = text("", 11, MUTED, false);
        resultHeader.addView(recordDate);
        result.addView(resultHeader);
        LinearLayout resultLine = row();
        resultTitle = text("还没有对局记录", 18, INK, true);
        resultTitle.setId(R.id.panel_result_title);
        resultLine.addView(resultTitle, new LinearLayout.LayoutParams(0, -2, 1));
        resultPill = text("等待开始", 11, MUTED, false);
        resultPill.setPadding(dp(10), dp(6), dp(10), dp(6));
        resultPill.setBackground(shape(PAPER, 20, 0));
        resultLine.addView(resultPill);
        add(result, resultLine, 17);
        resultBody = text("完成一场对局后，在这里查看运行结果。", 13, MUTED, false);
        add(result, resultBody, 8);
        add(result, divider(), 18);
        boolean largeStats = activity.getResources().getConfiguration().fontScale >= 1.35f;
        LinearLayout stats = largeStats ? column() : row();
        duration = stat(stats, "运行时长");
        turns = stat(stats, "进行回合");
        actionsCount = stat(stats, "已确认行动");
        add(result, stats, 16);
        details = button("查看本局详情  →", Color.WHITE, OLIVE, 0);
        details.setId(R.id.panel_details);
        details.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
        details.setPadding(0, dp(6), 0, dp(6));
        details.setOnClickListener(v -> actions.details());
        add(result, details, 8);
        add(root, result, 16);

        LinearLayout guide = card(Color.rgb(237, 240, 229), 20);
        guide.addView(text("对战模式", 15, INK, true));
        TextView steps = text("选择休闲或排位，填写局数，再选择启动方式。\n开始辅助：自动打开 KARDS。\n手动入口：先启动辅助，再将本应用切到后台，自行打开 KARDS。\n每局使用列表中第一个牌组，确认胜负并回到对战菜单后继续。\n0 为无限循环；点击停止、离开游戏或无法确认画面时停止。\n训练模式仅用于调试，可在下方工具中启动。", 13, MUTED, false);
        steps.setLineSpacing(dp(8), 1);
        add(guide, steps, 12);
        add(root, guide, 16);

        diagnosticsToggle = button("工具与诊断   ＋", PAPER, MUTED, 0);
        diagnosticsToggle.setId(R.id.panel_diagnostics_toggle);
        diagnosticsToggle.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
        diagnosticsToggle.setPadding(dp(2), dp(8), dp(2), dp(8));
        diagnosticsToggle.setOnClickListener(v -> setDiagnosticsOpen(!diagnosticsOpen));
        add(root, diagnosticsToggle, 10);
        diagnostics = card(Color.WHITE, 18);
        diagnostics.setId(R.id.panel_diagnostics);
        diagnostics.setVisibility(View.GONE);
        root.addView(diagnostics, new LinearLayout.LayoutParams(-1, -2));
        TextView footer = text("本地运行  ·  无需额外运行环境", 11, MUTED, false);
        footer.setGravity(Gravity.CENTER);
        add(root, footer, 14);
        updateModeButtons();
        matchCountInput.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence value, int from, int count, int after) { }
            @Override public void onTextChanged(CharSequence value, int from, int before, int count) { }
            @Override public void afterTextChanged(Editable value) {
                if (editingCount) return;
                if (!matchCountInput.isEnabled()) {
                    restoreMatchCountText(countText);
                    return;
                }
                countText = value.toString();
                Integer parsed = parseMatchCount(countText);
                if (parsed != null && selectedMatchCount != parsed) {
                    selectedMatchCount = parsed;
                    actions.matchCountChanged(parsed);
                }
                updateCountValidation();
                if (manualEntryAvailable) heroBody.setText(idleDescription());
            }
        });
    }

    View view() { return scroll; }
    String selectedMode() { return selectedMode; }
    int selectedMatchCount() {
        Integer value = parseMatchCount(countText);
        if (value == null) throw new IllegalStateException("invalid_match_count");
        return value;
    }
    String matchCountText() { return countText; }
    boolean validMatchCount() { return parseMatchCount(countText) != null; }
    static Integer parseMatchCount(String raw) {
        if (raw == null || !raw.matches("[0-9]+")) return null;
        try { return Integer.valueOf(raw); }
        catch (NumberFormatException invalid) { return null; }
    }
    void setSelectedMatchCount(int count) {
        if (count < 0) throw new IllegalArgumentException("invalid_match_count");
        restoreMatchCountText(Integer.toString(count));
    }
    void restoreMatchCountText(String raw) {
        countText = raw == null ? "" : raw;
        Integer parsed = parseMatchCount(countText);
        if (parsed != null) selectedMatchCount = parsed;
        editingCount = true;
        matchCountInput.setText(countText);
        editingCount = false;
        updateCountValidation();
        if (manualEntryAvailable) heroBody.setText(idleDescription());
    }
    private void updateCountValidation() {
        matchCountInput.setError(validMatchCount() ? null : activity.getString(R.string.match_count_invalid));
        start.setEnabled(entryAvailable && validMatchCount());
        manualStart.setEnabled(manualEntryAvailable && validMatchCount());
        start.setAlpha(start.isEnabled() ? 1f : .48f);
        manualStart.setAlpha(manualStart.isEnabled() ? 1f : .48f);
    }
    private String idleDescription() {
        Integer count = parseMatchCount(countText);
        return "开始辅助会自动打开 KARDS，也可选择下方手动入口。\n使用列表中第一个牌组，"
                + (count == null ? "填写有效局数后开始。" : count == 0 ? "无限循环，直到你停止。"
                   : "本次进行 " + count + " 局，完成后停止。");
    }
    void setSelectedMode(String mode) {
        selectedMode = "ranked".equals(mode) ? "ranked" : "casual";
        updateModeButtons();
        if (primaryCanStart) start.setText("ranked".equals(selectedMode) ? "开始排位辅助" : "开始休闲辅助");
    }

    private void selectModeFromUser(String mode, Button source) {
        if (!source.isEnabled() || selectedMode.equals(mode)) return;
        setSelectedMode(mode);
        actions.modeChanged(mode);
    }

    private void updateModeButtons() {
        styleMode(casual, "casual".equals(selectedMode), "休闲对局");
        styleMode(ranked, "ranked".equals(selectedMode), "排位对战");
    }

    private void styleMode(Button button, boolean selected, String label) {
        button.setSelected(selected);
        button.setTextColor(selected ? INK : Color.rgb(224, 231, 218));
        button.setBackground(ripple(selected ? Color.rgb(224, 230, 209) : OLIVE, 11,
                selected ? Color.rgb(224, 230, 209) : Color.rgb(115, 134, 113)));
        button.setContentDescription(label + (selected ? "，已选择" : "，未选择"));
    }
    boolean diagnosticsOpen() { return diagnosticsOpen; }
    void setDiagnosticsOpen(boolean open) {
        diagnosticsOpen = open;
        diagnostics.setVisibility(open ? View.VISIBLE : View.GONE);
        diagnosticsToggle.setText(open ? "工具与诊断   −" : "工具与诊断   ＋");
        diagnosticsToggle.setContentDescription(open ? "收起工具与诊断" : "展开工具与诊断");
    }

    void render(TrainingPanelState state, boolean connected, boolean gameInstalled, boolean busy, String date) {
        gameSymbol.setText(gameInstalled ? "✓" : "!");
        gameValue.setText(gameInstalled ? "已安装" : "未检测到游戏，可使用下方手动入口");
        serviceSymbol.setText(connected ? "✓" : "!");
        serviceValue.setText(connected ? "已连接 · 可以识别和操作" : "未开启 · 点击下方完成授权");
        serviceSymbol.setTextColor(connected ? OLIVE : Color.rgb(145, 102, 41));
        settings.setText(connected ? "管理权限" : "开启无障碍权限");
        boolean stopping = "stopping".equals(state.statusKind) || (busy && !state.active);
        boolean waiting = state.active && "waiting".equals(state.statusKind);
        readiness.setText(stopping ? "●  正在停止" : waiting ? "●  辅助已待命" : state.active ? "●  辅助运行中"
                : !connected ? "○  等待授权" : !gameInstalled ? "●  可手动打开游戏" : "●  权限已就绪");
        heroTitle.setText(stopping ? "正在结束本次辅助" : state.active ? state.title
                : !connected ? "开启你的对战助手" : !gameInstalled ? "可以手动启动辅助" : "准备好下一场对战");
        heroBody.setText(stopping ? "正在收尾并保存运行记录。\n结束后可以再次开始。" : state.active ? state.summary
                : idleDescription());
        permissionRequired = !connected;
        primaryCanStart = !state.active && !stopping && !busy && gameInstalled && connected;
        start.setText(stopping ? "正在停止…" : waiting ? "等待游戏" : state.active ? "正在运行" : !connected ? "开启权限"
                : "ranked".equals(selectedMode) ? "开始排位辅助" : "开始休闲辅助");
        manualEntryAvailable = !state.active && !stopping && !busy;
        entryAvailable = manualEntryAvailable && gameInstalled;
        updateCountValidation();
        casual.setEnabled(!state.active && !stopping && !busy);
        ranked.setEnabled(!state.active && !stopping && !busy);
        matchCountInput.setEnabled(!state.active && !stopping && !busy);
        matchCountInput.setAlpha(matchCountInput.isEnabled() ? 1f : .6f);
        casual.setAlpha(casual.isEnabled() ? 1f : .6f);
        ranked.setAlpha(ranked.isEnabled() ? 1f : .6f);
        stop.setEnabled(state.active || busy);
        stop.setAlpha(stop.isEnabled() ? 1f : .36f);
        resultTitle.setText(state.hasSession ? state.title : "还没有对局记录");
        resultBody.setText(state.hasSession ? state.summary : "从第一场对局开始，记录会自动保存在这里。");
        resultPill.setText(state.hasSession ? state.modeLabel : "等待开始");
        resultPill.setTextColor(state.interrupted ? Color.rgb(143, 88, 44) : OLIVE);
        duration.setText(state.durationDisplay);
        turns.setText(state.turnCount);
        actionsCount.setText(state.actionCount);
        recordDate.setText(state.hasSession ? date : "");
        details.setVisibility(state.hasSession ? View.VISIBLE : View.GONE);
    }

    void message(String title, String body) {
        heroTitle.setText(title);
        heroBody.setText(body);
        heroTitle.announceForAccessibility(title);
    }

    void styleDiagnosticsButton(Button button) {
        button.setAllCaps(false);
        button.setTextSize(13);
        button.setTextColor(INK);
        button.setMinHeight(dp(48));
        button.setPadding(dp(12), dp(9), dp(12), dp(9));
        button.setBackground(ripple(Color.rgb(241, 244, 236), 10, 0));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.topMargin = dp(8);
        button.setLayoutParams(params);
    }

    private LinearLayout readinessRow(String title, String body) {
        LinearLayout row = row();
        TextView symbol = text("✓", 17, OLIVE, true);
        symbol.setGravity(Gravity.CENTER);
        symbol.setBackground(shape(Color.rgb(238, 243, 229), 12, 0));
        row.addView(symbol, new LinearLayout.LayoutParams(dp(36), dp(36)));
        LinearLayout label = column();
        label.addView(text(title, 14, INK, true));
        add(label, text(body, 12, MUTED, false), 5);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, -2, 1);
        params.setMarginStart(dp(12));
        row.addView(label, params);
        return row;
    }

    private TextView stat(LinearLayout parent, String label) {
        if (parent.getOrientation() == LinearLayout.VERTICAL) {
            LinearLayout cell = row();
            cell.addView(text(label, 13, MUTED, false), new LinearLayout.LayoutParams(0, -2, 1));
            TextView value = text("—", 21, INK, true);
            cell.addView(value);
            add(parent, cell, parent.getChildCount() == 0 ? 0 : 16);
            return value;
        }
        LinearLayout cell = column();
        cell.setPadding(0, 0, dp(10), 0);
        TextView value = text("—", 23, INK, true);
        cell.addView(value);
        add(cell, text(label, 11, MUTED, false), 5);
        parent.addView(cell, new LinearLayout.LayoutParams(0, -2, 1));
        return value;
    }

    private View divider() {
        View line = new View(activity);
        line.setMinimumHeight(dp(1));
        line.setBackgroundColor(LINE);
        return line;
    }

    private LinearLayout card(int color, int padding) {
        LinearLayout view = column();
        view.setPadding(dp(padding), dp(padding), dp(padding), dp(padding));
        view.setBackground(shape(color, 18, color == Color.WHITE ? LINE : 0));
        return view;
    }

    private TextView text(String value, int size, int color, boolean bold) {
        TextView view = new TextView(activity);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        view.setFontFeatureSettings("kern");
        view.setTypeface(Typeface.create("sans-serif", bold ? Typeface.BOLD : Typeface.NORMAL));
        view.setIncludeFontPadding(false);
        return view;
    }

    private Button button(String label, int background, int foreground, int stroke) {
        Button button = new Button(activity);
        button.setText(label);
        button.setTextSize(14);
        button.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        button.setAllCaps(false);
        button.setTextColor(foreground);
        button.setMinHeight(dp(50));
        button.setMinimumHeight(dp(50));
        button.setPadding(dp(16), dp(12), dp(16), dp(12));
        button.setStateListAnimator(null);
        button.setBackground(ripple(background, 11, stroke));
        return button;
    }

    private GradientDrawable shape(int color, int radius, int stroke) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(color);
        shape.setCornerRadius(dp(radius));
        if (stroke != 0) shape.setStroke(dp(1), stroke);
        return shape;
    }

    private RippleDrawable ripple(int color, int radius, int stroke) {
        return new RippleDrawable(ColorStateList.valueOf(0x204C6648), shape(color, radius, stroke), null);
    }

    private LinearLayout row() {
        LinearLayout view = new LinearLayout(activity);
        view.setOrientation(LinearLayout.HORIZONTAL);
        view.setGravity(Gravity.CENTER_VERTICAL);
        return view;
    }

    private LinearLayout column() {
        LinearLayout view = new LinearLayout(activity);
        view.setOrientation(LinearLayout.VERTICAL);
        return view;
    }

    private void add(LinearLayout parent, View child, int top) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.topMargin = dp(top);
        parent.addView(child, params);
    }

    private int dp(int value) { return Math.round(value * activity.getResources().getDisplayMetrics().density); }
}
