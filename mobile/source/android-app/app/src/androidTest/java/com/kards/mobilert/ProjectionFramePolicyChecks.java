package com.kards.mobilert;

import org.json.JSONArray;
import org.json.JSONObject;

/** No consent, game launch or input: production lifecycle predicates, not live-frame acceptance. */
final class ProjectionFramePolicyChecks {
    static JSONObject run() throws Exception {
        JSONArray checks = new JSONArray();
        check(checks,"idle_images_never_eligible",!ProjectionFramePolicy.fresh(0,101));
        check(checks,"pre_request_image_rejected",!ProjectionFramePolicy.fresh(100,99));
        check(checks,"same_timestamp_rejected",!ProjectionFramePolicy.fresh(100,100));
        check(checks,"strictly_new_image_eligible",ProjectionFramePolicy.fresh(100,101));
        check(checks,"negative_threshold_rejected",!ProjectionFramePolicy.fresh(-1,101));
        check(checks,"not_ready_geometry_rejected",!ProjectionFramePolicy.ready(false,false));
        check(checks,"later_layout_can_become_ready",ProjectionFramePolicy.ready(false,true));
        check(checks,"revoked_geometry_cannot_revive",!ProjectionFramePolicy.ready(true,true));
        check(checks,"closed_not_ready",!ProjectionFramePolicy.ready(true,false));
        check(checks,"open_before_deadline_delivers",ProjectionFramePolicy.deliver(false,99,100));
        check(checks,"at_deadline_rejected",!ProjectionFramePolicy.deliver(false,100,100));
        check(checks,"after_deadline_rejected",!ProjectionFramePolicy.deliver(false,101,100));
        check(checks,"revoked_pending_frame_rejected",!ProjectionFramePolicy.deliver(true,99,100));
        check(checks,"initializing_source_not_bypassed",ProjectionFramePolicy.useConsentSource(32,true));
        check(checks,"missing_source_not_invented",!ProjectionFramePolicy.useConsentSource(32,false));
        check(checks,"api35_keeps_window_route",!ProjectionFramePolicy.useConsentSource(35,true));
        check(checks,"legacy_live_natural_fallback_can_recover",ProjectionFramePolicy.recoverLogicalMirror(32,false,true,false));
        check(checks,"closed_mirror_cannot_recover",!ProjectionFramePolicy.recoverLogicalMirror(32,true,true,false));
        check(checks,"logical_mirror_not_recreated",!ProjectionFramePolicy.recoverLogicalMirror(32,false,false,false));
        check(checks,"logical_recovery_only_once",!ProjectionFramePolicy.recoverLogicalMirror(32,false,true,true));
        check(checks,"api34_no_consent_display_reuse",!ProjectionFramePolicy.recoverLogicalMirror(34,false,true,false));
        check(checks,"api35_no_consent_display_reuse",!ProjectionFramePolicy.recoverLogicalMirror(35,false,true,false));
        check(checks,"logical_layout_waits_before_original_deadline",ProjectionFramePolicy.awaitLogicalLayout(false,true,99,100));
        check(checks,"logical_layout_never_extends_deadline",!ProjectionFramePolicy.awaitLogicalLayout(false,true,100,100));
        check(checks,"logical_layout_rejects_late",!ProjectionFramePolicy.awaitLogicalLayout(false,true,101,100));
        check(checks,"closed_logical_layout_does_not_wait",!ProjectionFramePolicy.awaitLogicalLayout(true,true,99,100));
        check(checks,"unstarted_logical_layout_does_not_wait",!ProjectionFramePolicy.awaitLogicalLayout(false,false,99,100));
        check(checks,"idle_legacy_preparation_allowed",ProjectionFramePolicy.prepareIdleGeometry(32,false,false,99,100));
        check(checks,"active_request_preparation_forbidden",!ProjectionFramePolicy.prepareIdleGeometry(32,false,true,99,100));
        check(checks,"revoked_idle_preparation_forbidden",!ProjectionFramePolicy.prepareIdleGeometry(32,true,false,99,100));
        check(checks,"idle_preparation_deadline_bounded",!ProjectionFramePolicy.prepareIdleGeometry(32,false,false,100,100));
        check(checks,"late_idle_preparation_forbidden",!ProjectionFramePolicy.prepareIdleGeometry(32,false,false,101,100));
        check(checks,"api34_idle_display_reuse_forbidden",!ProjectionFramePolicy.prepareIdleGeometry(34,false,false,99,100));
        check(checks,"api35_idle_display_reuse_forbidden",!ProjectionFramePolicy.prepareIdleGeometry(35,false,false,99,100));
        return new JSONObject().put("passed",true).put("check_count",checks.length()).put("checks",checks)
                .put("device_inputs",0).put("game_launches",0).put("live_frame_test",false);
    }
    private static void check(JSONArray rows,String name,boolean passed) throws Exception {
        if(!passed)throw new AssertionError(name);
        rows.put(new JSONObject().put("name",name).put("passed",true));
    }
}
