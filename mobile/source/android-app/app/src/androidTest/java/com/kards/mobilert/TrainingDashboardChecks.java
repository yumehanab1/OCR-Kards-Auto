package com.kards.mobilert;

import android.app.Activity;
import android.os.Looper;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

/** Detached view checks with fake callbacks; no service, game launch or device input. */
public final class TrainingDashboardChecks {
    private final JSONArray checks = new JSONArray();
    private int failures;

    /** The caller runs this on the UI thread; the Activity's content is never replaced. */
    public static JSONObject run(Activity activity) throws Exception {
        if (activity == null || Looper.myLooper() != Looper.getMainLooper()) {
            throw new IllegalArgumentException("An Activity and its main thread are required");
        }
        TrainingDashboardChecks test = new TrainingDashboardChecks();
        test.interactions(activity);
        test.numericInput(activity);
        return new JSONObject().put("checks", test.checks).put("check_count", test.checks.length())
                .put("failure_count", test.failures).put("device_inputs", 0)
                .put("uses_real_service", false).put("activity_content_replaced", false);
    }

    private void interactions(Activity activity) throws Exception {
        ViewGroup content = activity.findViewById(android.R.id.content);
        View[] originalChildren = new View[content == null ? 0 : content.getChildCount()];
        for (int i = 0; i < originalChildren.length; i++) originalChildren[i] = content.getChildAt(i);

        FakeActions actions = new FakeActions();
        TrainingDashboard dashboard = new TrainingDashboard(activity, actions, "test");
        View view = dashboard.view();
        Button primary = view.findViewById(R.id.panel_start);
        Button manual = view.findViewWithTag("panel_manual_start");
        Button stop = view.findViewById(R.id.panel_stop);
        Button permissions = view.findViewById(R.id.panel_permissions);
        Button details = view.findViewById(R.id.panel_details);
        Button toggle = view.findViewById(R.id.panel_diagnostics_toggle);
        Button casual = view.findViewWithTag("panel_mode_casual");
        Button ranked = view.findViewWithTag("panel_mode_ranked");
        EditText count = view.findViewWithTag("panel_match_count");
        View diagnostics = view.findViewById(R.id.panel_diagnostics);
        check("construction_does_not_invoke_actions", actions.total() == 0);
        check("diagnostics_initially_collapsed", !dashboard.diagnosticsOpen()
                && diagnostics.getVisibility() == View.GONE);
        check("formal_selector_defaults_to_casual_and_excludes_training", casual != null && ranked != null
                && casual.isSelected() && !ranked.isSelected() && "casual".equals(dashboard.selectedMode())
                && view.findViewWithTag("panel_mode_training") == null);
        check("single_game_and_supported_deck_are_visible", containsText(view,
                "开始辅助会自动打开 KARDS，也可选择下方手动入口。\n使用列表中第一个牌组，本次进行 1 局，完成后停止。"));
        check("both_game_entries_and_unlimited_stop_are_explained", containsText(view,
                "选择休闲或排位，填写局数，再选择启动方式。\n开始辅助：自动打开 KARDS。\n手动入口：先启动辅助，再将本应用切到后台，自行打开 KARDS。\n每局使用列表中第一个牌组，确认胜负并回到对战菜单后继续。\n0 为无限循环；点击停止、离开游戏或无法确认画面时停止。\n训练模式仅用于调试，可在下方工具中启动。"));
        check("match_count_defaults_to_one", count != null && "1".contentEquals(count.getText())
                && dashboard.selectedMatchCount() == 1 && actions.countChanges == 0
                && view.findViewWithTag("panel_count_one") == null && view.findViewWithTag("panel_count_two") == null);

        TrainingPanelState empty = TrainingPanelState.from("{}");
        dashboard.render(empty, false, true, false, "");
        check("render_does_not_invoke_actions", actions.total() == 0);
        check("missing_permission_exposes_enabled_authorization_cta", primary.isEnabled()
                && "开启权限".contentEquals(primary.getText()) && !stop.isEnabled());
        primary.performClick();
        check("authorization_cta_only_opens_permissions", actions.permissions == 1 && actions.total() == 1);
        permissions.performClick();
        check("permission_button_only_opens_permissions", actions.permissions == 2 && actions.total() == 2);
        manual.performClick();
        check("manual_entry_without_permission_only_opens_settings", manual.isEnabled()
                && actions.permissions == 3 && actions.total() == 3);

        dashboard.render(empty, true, false, false, "");
        check("missing_game_disables_both_entry_actions", !primary.isEnabled() && !manual.isEnabled() && !stop.isEnabled());
        dashboard.render(empty, true, true, false, "");
        check("ready_environment_enables_selected_mode", primary.isEnabled()
                && "开始休闲辅助".contentEquals(primary.getText()) && !stop.isEnabled());
        primary.performClick();
        check("automatic_start_passes_casual_and_open_game", actions.starts == 1 && "casual".equals(actions.lastStartedMode)
                && actions.lastOpenGame && actions.permissions == 3 && actions.lastMatchCount == 1);
        manual.performClick();
        check("manual_start_passes_casual_without_open_game", actions.starts == 2
                && "casual".equals(actions.lastStartedMode) && !actions.lastOpenGame);
        ranked.performClick();
        check("ranked_selection_changes_only_preference", actions.starts == 2 && actions.modeChanges == 1
                && "ranked".equals(actions.lastSelectedMode) && !casual.isSelected() && ranked.isSelected()
                && "开始排位辅助".contentEquals(primary.getText()));
        primary.performClick();
        check("automatic_start_passes_ranked_and_open_game", actions.starts == 3
                && "ranked".equals(actions.lastStartedMode) && actions.lastOpenGame);
        manual.performClick();
        check("manual_start_passes_ranked_without_open_game", actions.starts == 4
                && "ranked".equals(actions.lastStartedMode) && !actions.lastOpenGame);
        ranked.performClick();
        check("reselecting_same_mode_does_not_emit_duplicate_preference", actions.modeChanges == 1);
        count.setText("7");
        check("numeric_match_choice_only_changes_preference", dashboard.selectedMatchCount() == 7
                && actions.countChanges == 1 && actions.starts == 4);
        count.setText("7");
        check("same_match_count_does_not_repeat_callback", actions.countChanges == 1);
        primary.performClick(); manual.performClick();
        check("both_entries_share_arbitrary_match_count", actions.starts == 6 && actions.lastMatchCount == 7 && !actions.lastOpenGame);
        FakeActions restoredActions = new FakeActions();
        TrainingDashboard restored = new TrainingDashboard(activity, restoredActions, "test");
        restored.setSelectedMode(dashboard.selectedMode());
        restored.setSelectedMatchCount(dashboard.selectedMatchCount());
        check("restoring_saved_mode_has_no_game_or_preference_callbacks", "ranked".equals(restored.selectedMode())
                && restoredActions.total() == 0);
        check("restored_count_does_not_start_or_change_preference", restored.selectedMatchCount() == 7 && restoredActions.total() == 0);
        dashboard.setSelectedMode("training");
        check("training_cannot_become_a_formal_selector_option", "casual".equals(dashboard.selectedMode())
                && casual.isSelected() && !ranked.isSelected() && actions.modeChanges == 1);

        TrainingPanelState waiting = TrainingPanelState.from(new JSONObject().put("session_id", "panel-wait-check")
                .put("event", "armed").put("active", true).put("reason", "waiting_for_game")
                .put("match_mode", "casual").put("stage", "menu").toString());
        dashboard.render(waiting, true, true, true, "");
        check("armed_panel_exposes_waiting_game_instead_of_playing", "等待游戏".contentEquals(primary.getText())
                && containsText(view, "●  辅助已待命") && containsText(view, waiting.summary)
                && !containsText(view, "正在自动出牌、移动和攻击。请保持游戏在前台。"));
        check("waiting_panel_keeps_stop_and_disables_both_entries_and_modes", !primary.isEnabled() && !manual.isEnabled() && stop.isEnabled()
                && !casual.isEnabled() && !ranked.isEnabled());
        primary.performClick();
        manual.performClick();
        ranked.performClick();
        count.setText("2");
        check("waiting_panel_cannot_start_twice_or_change_mode", actions.starts == 6 && actions.modeChanges == 1
                && "casual".equals(dashboard.selectedMode()));
        check("busy_disables_match_count_and_direct_edit", !count.isEnabled()
                && dashboard.selectedMatchCount() == 7 && "7".contentEquals(count.getText()) && actions.countChanges == 1);

        TrainingPanelState running = state("engine", true, "capture");
        dashboard.render(running, true, true, true, "10月6日 12:00");
        check("running_allows_stop_but_not_another_start", !primary.isEnabled() && !manual.isEnabled() && stop.isEnabled());
        primary.performClick();
        manual.performClick();
        ranked.performClick();
        check("running_disables_start_and_mode_changes_even_for_direct_click", actions.starts == 6
                && actions.modeChanges == 1 && !ranked.isEnabled() && !casual.isEnabled());
        stop.performClick();
        check("stop_delegates_exactly_once", actions.stops == 1 && actions.starts == 6);

        dashboard.render(state("stopping", false, "user_stop"), true, true, true, "");
        check("cancelled_worker_keeps_both_entry_actions_and_count_disabled", !primary.isEnabled() && !manual.isEnabled()
                && !count.isEnabled() && stop.isEnabled());

        TrainingPanelState finished = state("finished", false, "user_stop");
        dashboard.render(finished, true, true, true, "");
        check("published_result_waits_for_worker_lease_release", !primary.isEnabled() && !manual.isEnabled()
                && !count.isEnabled() && stop.isEnabled());
        dashboard.render(finished, true, true, false, "");
        check("released_worker_restores_both_entries_and_details", primary.isEnabled() && manual.isEnabled()
                && "开始休闲辅助".contentEquals(primary.getText()) && !stop.isEnabled()
                && count.isEnabled() && details.getVisibility() == View.VISIBLE);
        details.performClick();
        check("details_delegates_without_game_action", actions.details == 1 && actions.starts == 6);

        toggle.performClick();
        check("diagnostics_toggle_expands", dashboard.diagnosticsOpen()
                && diagnostics.getVisibility() == View.VISIBLE);
        toggle.performClick();
        check("diagnostics_toggle_collapses", !dashboard.diagnosticsOpen()
                && diagnostics.getVisibility() == View.GONE);
        check("rendering_and_diagnostics_add_no_action_callbacks", actions.stops == 1
                && actions.permissions == 3 && actions.details == 1 && actions.starts == 6 && actions.modeChanges == 1 && actions.countChanges == 1);

        boolean sameContent = activity.findViewById(android.R.id.content) == content;
        if (content != null) {
            sameContent &= content.getChildCount() == originalChildren.length;
            for (int i = 0; sameContent && i < originalChildren.length; i++) {
                sameContent = content.getChildAt(i) == originalChildren[i];
            }
        }
        check("checks_keep_dashboard_detached_and_activity_content_unchanged",
                view.getParent() == null && sameContent);
    }

    private void numericInput(Activity activity) throws Exception {
        FakeActions actions = new FakeActions();
        TrainingDashboard dashboard = new TrainingDashboard(activity, actions, "test");
        View view = dashboard.view();
        EditText count = view.findViewWithTag("panel_match_count");
        Button primary = view.findViewById(R.id.panel_start);
        Button manual = view.findViewWithTag("panel_manual_start");
        dashboard.render(TrainingPanelState.from("{}"), true, true, false, "");
        check("numeric_keyboard_keeps_pasted_invalid_text", !(count.getKeyListener() instanceof android.text.method.DigitsKeyListener)
                && (count.getInputType() & android.text.InputType.TYPE_MASK_CLASS) == android.text.InputType.TYPE_CLASS_NUMBER);
        for (String text : new String[]{"", "-1", "1.5", "2147483648", "1e3", "+1", " 1 ", "abc"}) {
            int changes = actions.countChanges, starts = actions.starts;
            count.setText(text);
            primary.performClick(); manual.performClick();
            check("invalid_count_refuses_both_entries_" + checks.length(), !dashboard.validMatchCount()
                    && !primary.isEnabled() && !manual.isEnabled() && count.getError() != null
                    && text.equals(dashboard.matchCountText()) && actions.countChanges == changes && actions.starts == starts);
            boolean refused = false;
            try { dashboard.selectedMatchCount(); } catch (IllegalStateException invalid) { refused = true; }
            check("invalid_count_never_falls_back_to_saved_value_" + checks.length(), refused);
        }
        for (int value : new int[]{0, 3, 7, Integer.MAX_VALUE}) {
            count.setText(Integer.toString(value));
            int starts = actions.starts;
            primary.performClick();
            boolean automatic = actions.starts == starts + 1 && actions.lastMatchCount == value && actions.lastOpenGame;
            manual.performClick();
            check("valid_numeric_count_shared_by_both_entries_" + value, automatic && actions.starts == starts + 2
                    && actions.lastMatchCount == value && !actions.lastOpenGame && count.getError() == null);
            JSONObject options = MainActivity.battleOptions(false, "casual", value);
            check("panel_casual_uses_source_pipeline_" + value, options.getBoolean("native_menu"));
            check("panel_limits_detailed_evidence_"+value,!options.getBoolean("retain_full_evidence"));
            check("multi_or_unlimited_options_preserve_target_and_per_round_budget_" + value,
                    options.getInt("match_count") == value && options.getInt("max_seconds") == 1800
                    && options.getInt("max_inputs") == 200 && options.getBoolean("post_match_settle"));
            FakeActions restoredActions = new FakeActions();
            TrainingDashboard restored = new TrainingDashboard(activity, restoredActions, "test");
            restored.setSelectedMatchCount(value);
            check("restoring_valid_numeric_setting_does_not_start_" + value,
                    restored.selectedMatchCount() == value && restoredActions.total() == 0);
        }
        JSONObject single = MainActivity.battleOptions(false, "ranked", 1);
        check("panel_ranked_uses_source_pipeline", single.getBoolean("native_menu"));
        check("panel_training_keeps_existing_engine", !MainActivity.battleOptions(false, "training", 1).getBoolean("native_menu"));
        check("one_match_preserves_single_round_budget", single.getInt("match_count") == 1
                && single.getInt("max_seconds") == 1200 && single.getInt("max_inputs") == 120
                && single.getBoolean("post_match_settle"));
        JSONObject readOnly = MainActivity.battleOptions(true, "training", 1);
        check("panel_readonly_training_keeps_existing_inspection", !readOnly.getBoolean("native_menu"));
        check("diagnostic_read_only_still_has_no_input", readOnly.getInt("max_seconds") == 60 && readOnly.getInt("max_inputs") == 0);
        boolean refused = false;
        try { MainActivity.battleOptions(false, "casual", -1); } catch (IllegalArgumentException invalid) { refused = true; }
        check("options_builder_refuses_negative_count", refused);
        int callbacks = actions.total();
        dashboard.restoreMatchCountText("");
        check("recreation_preserves_invalid_draft_without_callbacks", dashboard.matchCountText().isEmpty()
                && !dashboard.validMatchCount() && !primary.isEnabled() && !manual.isEnabled() && actions.total() == callbacks);
        dashboard.restoreMatchCountText("0");
        check("recreation_preserves_unlimited_setting_without_callbacks", dashboard.selectedMatchCount() == 0
                && actions.total() == callbacks && primary.isEnabled() && manual.isEnabled());
        count.setText("0003");
        check("leading_zero_integer_preserves_its_value", dashboard.selectedMatchCount() == 3 && dashboard.validMatchCount());
    }

    private static TrainingPanelState state(String event, boolean active, String reason) throws Exception {
        return TrainingPanelState.from(new JSONObject().put("session_id", "panel-interaction-check")
                .put("event", event).put("active", active).put("reason", reason)
                .put("elapsed_ms", 1000).toString());
    }

    private static boolean containsText(View view, String expected) {
        if (view instanceof TextView && expected.contentEquals(((TextView) view).getText())) return true;
        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;
            for (int i = 0; i < group.getChildCount(); i++) {
                if (containsText(group.getChildAt(i), expected)) return true;
            }
        }
        return false;
    }

    private void check(String name, boolean passed) throws Exception {
        checks.put(new JSONObject().put("name", name).put("passed", passed));
        if (!passed) failures++;
    }

    private static final class FakeActions implements TrainingDashboard.Actions {
        int stops, permissions, details, starts, modeChanges, countChanges, lastMatchCount;
        String lastStartedMode, lastSelectedMode;
        boolean lastOpenGame;
        @Override public void start(String mode, boolean openGame, int matchCount) {
            starts++; lastStartedMode = mode; lastOpenGame = openGame; lastMatchCount = matchCount;
        }
        @Override public void modeChanged(String mode) { modeChanges++; lastSelectedMode = mode; }
        @Override public void matchCountChanged(int count) { countChanges++; }
        @Override public void stop() { stops++; }
        @Override public void permissions() { permissions++; }
        @Override public void details() { details++; }
        int total() { return stops + permissions + details + starts + modeChanges + countChanges; }
    }
}
