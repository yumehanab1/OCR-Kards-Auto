"""Planning, evidence and real Runtime fake-bridge checks; device inputs zero."""
import base64
import copy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock
import zlib

import numpy as np
import cv2

import apk_battle_runtime as runtime
import apk_simple_deploy as simple


def row(count):
    hq = {"row_kind": "hq", "cx": 640 - 72 * count, "y": 436}
    cards = [hq] + [{"row_kind": "unit", "type": "infantry", "cx": hq["cx"] + i * 144,
                      "y": 436, "n_stats": 3} for i in range(1, count + 1)]
    return {"count": count, "reason": "complete_support_row", "cards": cards,
            "hq": hq, "transition": "", "choice_modal": False,
            "refusal_regions": [{"field": "hq_full_shield", "roi": [630, 520, 650, 540]}]}


def synthetic_shield(frame):
    yy, xx = np.indices((20, 20))
    frame[520:540, 630:650] = np.repeat((((xx // 3 + yy // 3) % 2) * 180)[:, :, None], 3, axis=2)


@lru_cache(maxsize=1)
def refusal_fixtures():
    folder = Path(__file__).resolve().parent / "deploy-refusal-fixtures"
    manifest = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    frames = {}
    for item in manifest["fixtures"]:
        raw = (folder / item["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise AssertionError("refusal_fixture_hash_changed:" + item["file"])
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if frame is None or frame.shape != (720, 1280, 3):
            raise AssertionError("refusal_fixture_invalid:" + item["file"])
        frames[item["frame_id"]] = frame
    return manifest, frames


def saved_refusal_group(source=104):
    manifest, all_frames = refusal_fixtures()
    group = next(g for g in manifest["groups"] if g["ids"][0] == source)
    return [all_frames[i].copy() for i in group["ids"]], copy.deepcopy(group["observations"])


def inspect_saved(frames, observations):
    sequence = iter(observations)
    return simple.inspect_pair(*frames, observer=lambda frame: next(sequence))


@lru_cache(maxsize=1)
def code38_semantic_patches():
    """Lossless local comparison samples; whole-frame replay is kept separately."""
    packed = zlib.decompress(base64.b64decode(_CODE38_PATCH_PAYLOAD))
    if hashlib.sha256(packed).hexdigest() != _CODE38_PATCH_PAYLOAD_SHA256:
        raise AssertionError("code38_patch_payload_hash_changed")
    size = int.from_bytes(packed[:4], "little")
    manifest = json.loads(packed[4:4+size].decode("utf-8"))
    data = packed[4+size:]
    frames = {}
    for key, entry in manifest["frames"].items():
        frame = np.zeros((720, 1280, 3), np.uint8)
        for patch in entry["patches"]:
            raw = data[patch["offset"]:patch["offset"]+patch["bytes"]]
            if hashlib.sha256(raw).hexdigest() != patch["sha256"]:
                raise AssertionError("code38_semantic_crop_hash_changed:" + key)
            x0, y0, x1, y1 = patch["box"]
            frame[y0:y1, x0:x1] = np.frombuffer(raw, np.uint8).reshape(y1-y0, x1-x0, 3)
        frames[key] = frame
    return manifest, frames


def unit(origin=(489, 657)):
    return {"cx": 465, "cy": 635, "kind": "unit", "state": "orange", "apk_grab_point": list(origin),
            "apk_availability": {"allowed": True, "basis": "orange_unit_geometry_v1",
                                 "cost": None, "credits": None}}


class SimpleDeployTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((720, 1280, 3), np.uint8)
        synthetic_shield(self.frame)
        self.info = {"frame_id": 1, "captured_elapsed_ms": 1000, "foreground_generation": 1,
                     "turn_id": 2}
        self.ledger = simple.FailedLayoutLedger()

    def plan(self, units=(), count=0, raw=(), info=None):
        return simple.make_plan(self.frame, info or self.info, list(units), list(raw),
                                runtime.Runtime.approved_grab_point, self.ledger, row=row(count))

    def validate(self, plan, frame=None, info=None, gesture=None, units=(), count=0):
        return simple.validate_plan(plan, self.frame if frame is None else frame, info or self.info,
            gesture or {"from": plan["origin"], "to": plan["target"]}, list(units),
            runtime.Runtime.approved_grab_point, row=row(count))

    def test_known_orange_unit_is_preferred_to_middle(self):
        plan, _ = self.plan([unit()])
        self.assertEqual((plan["mode"], plan["origin"], plan["target"]),
                         ("approved_unit", [489, 657], [440, 500]))
        self.assertFalse(plan["selected_identity_verified"])

    def test_missing_strict_grab_uses_explicit_unknown_middle(self):
        plan, reason = self.plan()
        self.assertEqual(plan["origin"], [640, 665])
        self.assertEqual(plan["badge"]["kind"], "unknown")
        self.assertEqual(plan["mode"], "blind_middle")
        self.assertIn("unknown", reason)
        self.assertIsNone(plan["cost"])

    def test_counts_zero_through_three_allow_and_four_refuses(self):
        for count in range(4):
            self.assertIsNotNone(self.plan(count=count)[0])
        self.assertEqual(self.plan(count=4), (None, "support_row_full"))

    def test_unknown_row_never_becomes_zero(self):
        with mock.patch("apk_deploy_target._row", return_value=(None, "moving", {"hq": None})):
            observed = simple.support_observation(self.frame)
            plan, reason = simple.make_plan(self.frame, self.info, [], [],
                runtime.Runtime.approved_grab_point, self.ledger)
        self.assertIsNone(observed["count"])
        self.assertIsNone(plan)
        self.assertEqual(reason, "support_count_unknown:moving")

    def test_hq_is_excluded_from_structural_count(self):
        for count in range(5):
            observed = row(count)
            with mock.patch("apk_deploy_target._row", return_value=(observed["cards"], observed["reason"], observed)):
                self.assertEqual(simple.support_observation(self.frame)["count"], count)

    def test_exact_plan_revalidates_without_material_test(self):
        plan, _ = self.plan()
        with mock.patch("apk_deploy_target.inspect_clear", side_effect=AssertionError("old material gate")):
            self.assertIsNone(self.validate(plan))

    def test_pixel_mutation_cannot_reuse_plan(self):
        plan, _ = self.plan()
        changed = self.frame.copy()
        changed[0, 0] = 255
        self.assertEqual(self.validate(plan, frame=changed), "simple_plan_pixels_changed")

    def test_capture_generation_turn_and_id_changes_refuse(self):
        plan, _ = self.plan()
        for key in ("frame_id", "captured_elapsed_ms", "foreground_generation", "turn_id"):
            self.assertEqual(self.validate(plan, info=dict(self.info, **{key: self.info[key] + 1})),
                             "simple_plan_capture_changed")

    def test_target_origin_and_consumed_plan_refuse(self):
        plan, _ = self.plan()
        for gesture in ({"from": [641, 665], "to": [440, 500]},
                        {"from": [640, 665], "to": [440, 505]}):
            self.assertEqual(self.validate(plan, gesture=gesture), "simple_plan_coordinates_changed")
        plan["consumed"] = True
        self.assertEqual(self.validate(plan), "simple_plan_missing_or_consumed")

    def test_dispatch_must_reprove_support_count_and_origin(self):
        plan, _ = self.plan([unit()])
        self.assertEqual(self.validate(plan), "simple_origin_not_unique_current_unit")
        self.assertEqual(self.validate(plan, units=[unit(), unit()]), "simple_origin_not_unique_current_unit")
        self.assertEqual(self.validate(plan, units=[unit()], count=4), "simple_support_count_unknown_or_full")
        self.assertEqual(self.validate(plan, units=[unit()], count=1), "simple_support_count_changed")

    def test_failed_middle_same_turn_cannot_loop_even_if_color_changes(self):
        raw = [{"cx": 640, "cy": 640, "kind": "unknown", "state": "gray"}]
        plan, _ = self.plan(raw=raw)
        self.ledger.failed(plan)
        raw[0]["state"] = "orange"
        self.assertEqual(self.plan(raw=raw), (None, "middle_layout_already_failed"))

    def test_real_next_turn_can_retry_same_layout_now_affordable(self):
        plan, _ = self.plan()
        self.ledger.failed(plan)
        self.assertIsNone(self.plan()[0])
        next_plan, _ = self.plan(info=dict(self.info, turn_id=3))
        self.assertIsNotNone(next_plan)
        self.assertEqual(next_plan["origin"], plan["origin"])

    def test_failed_middle_same_turn_stays_blocked_after_hand_consumption_and_relayout(self):
        before = [{"cx": 500, "cy": 640, "kind": "unknown"},
                  {"cx": 640, "cy": 645, "kind": "unknown"},
                  {"cx": 780, "cy": 640, "kind": "unknown"}]
        after = [{"cx": 570, "cy": 640, "kind": "unknown"},
                 {"cx": 710, "cy": 640, "kind": "unknown"}]
        plan, _ = self.plan(raw=before)
        self.ledger.failed(plan)
        self.assertNotEqual(simple.hand_layout(before), simple.hand_layout(after))
        self.assertEqual(self.plan(raw=after, info=dict(self.info, frame_id=2)),
                         (None, "middle_layout_already_failed"))

    def test_failed_middle_does_not_block_new_approved_orange_at_same_origin(self):
        raw = [{"cx": 640, "cy": 640, "kind": "unknown"}]
        blind, _ = self.plan(raw=raw)
        self.ledger.failed(blind)
        approved, _ = self.plan([unit(simple.MIDDLE_ORIGIN)], raw=raw)
        self.assertIsNotNone(approved)
        self.assertEqual(approved["mode"], "approved_unit")
        self.assertEqual(approved["origin"], blind["origin"])
        self.assertEqual(simple.retry_key(approved), simple.retry_key(blind))

    def test_failed_middle_reopens_on_real_next_turn_after_hand_relayout(self):
        blind, _ = self.plan(raw=[{"cx": 640, "cy": 640, "kind": "unknown"}])
        self.ledger.failed(blind)
        after = [{"cx": 570, "cy": 640, "kind": "unknown"},
                 {"cx": 710, "cy": 640, "kind": "unknown"}]
        self.assertIsNone(self.plan(raw=after)[0])
        next_plan, _ = self.plan(raw=after, info=dict(self.info, turn_id=3))
        self.assertIsNotNone(next_plan)
        self.assertEqual(next_plan["mode"], "blind_middle")
        self.assertEqual(next_plan["origin"], blind["origin"])

    def test_approved_failure_keeps_original_turn_layout_origin_scope(self):
        raw = [{"cx": 490, "cy": 635, "kind": "unit"}]
        approved, _ = self.plan([unit()], raw=raw)
        self.ledger.failed(approved)
        self.assertIsNone(self.plan([unit()], raw=raw)[0])
        changed = [{"cx": 540, "cy": 640, "kind": "unit"}]
        next_plan, _ = self.plan([unit()], raw=changed)
        self.assertIsNotNone(next_plan)
        self.assertEqual(next_plan["mode"], "approved_unit")
        self.assertEqual(next_plan["origin"], approved["origin"])

    def test_failed_known_origin_selects_other_unit_without_blind_replay(self):
        first, _ = self.plan([unit()])
        self.ledger.failed(first)
        self.assertEqual(self.plan([unit()]), (None, "deployment_layout_attempts_exhausted"))
        next_plan, _ = self.plan([unit(), unit((850, 665))])
        self.assertEqual(next_plan["mode"], "approved_unit")
        self.assertEqual(next_plan["origin"], [850, 665])

    def evidence(self, counts=(0, 1, 1), hand=True, support=True, rows=None):
        previous, current = self.frame.copy(), self.frame.copy()
        if hand:
            previous[610:700, 250:1050] = 100
            current[610:700, 250:1050] = 100
        if support:
            previous[430:570, 400:850] = 100
            current[430:570, 400:850] = 100
        snapshots = iter(rows or [row(n) for n in counts])
        return simple.inspect_pair(self.frame, previous, current, observer=lambda f: next(snapshots))

    def test_real_hand_and_persistent_unit_gain_confirm_without_identity(self):
        result = self.evidence()
        self.assertTrue(result["confirmed"], result)
        self.assertFalse(result["no_effect"])
        self.assertFalse(result["selected_identity_verified"])

    def test_consumed_order_hand_change_cannot_confirm_unit(self):
        result = self.evidence(counts=(0, 0, 0), support=False)
        self.assertFalse(result["confirmed"])
        self.assertFalse(result["no_effect"])
        self.assertEqual(result["reason"], "hand_changed_without_persistent_unit_gain")

    def test_count_gain_without_hand_change_or_real_support_change_refuses(self):
        for hand, support in ((False, True), (True, False)):
            self.assertFalse(self.evidence(hand=hand, support=support)["confirmed"])

    def test_stable_unchanged_pair_is_separate_refusal(self):
        result = self.evidence(counts=(0, 0, 0), hand=False, support=False)
        self.assertTrue(result["no_effect"])
        self.assertFalse(result["confirmed"])

    def test_same_unit_stat_visibility_improving_cannot_create_gain(self):
        rows = [row(1), row(1), row(1)]
        for observed, n_stats in zip(rows, (1, 2, 3)):
            observed["cards"][1]["n_stats"] = n_stats
        result = self.evidence(rows=rows)
        self.assertFalse(result["confirmed"])
        self.assertFalse(result["no_effect"])
        self.assertEqual(result["before_support"], result["after_support"])

    def test_single_type_on_any_frame_cannot_prove_numeric_refusal(self):
        for index in range(3):
            with self.subTest(index=index):
                rows = [row(1), row(1), row(1)]
                rows[index]["cards"][1]["n_stats"] = 1
                with mock.patch.object(simple, "unchanged_support_fields",
                        side_effect=AssertionError("numeric evidence unavailable")):
                    result = self.evidence(rows=rows, hand=False, support=False)
                self.assertFalse(result["confirmed"])
                self.assertFalse(result["no_effect"])
                self.assertEqual(result["reason"], "support_numeric_fields_unavailable_for_refusal")

    def test_transient_unit_gain_or_support_count_unknown_never_confirms(self):
        self.assertFalse(self.evidence(counts=(0, 1, 0))["confirmed"])
        rows = [row(0), row(1), dict(row(1), count=None, reason="incomplete")]
        self.assertEqual(self.evidence(rows=rows)["reason"], "support_row_incomplete")

    def test_choice_transition_and_moving_geometry_block_evidence(self):
        for change in ({"transition": "animation"}, {"choice_modal": True}):
            rows = [row(0), row(1), dict(row(1), **change)]
            self.assertEqual(self.evidence(rows=rows)["reason"], "transition_or_choice_modal")
        rows = [row(0), row(1), row(1)]
        rows[2]["cards"][0]["y"] += 5
        self.assertEqual(self.evidence(rows=rows)["reason"], "post_input_pixels_or_geometry_still_moving")

    def test_exact_saved_ranked_pixels_confirm_real_gain_without_source_identity(self):
        from apk_deploy_verify_test import fixtures
        frames, snapshots = fixtures()
        rows = iter([dict(item, reason=item["row_reason"],
                          count=len([c for c in item["cards"] if c.get("row_kind") == "unit"]))
                     for item in snapshots])
        result = simple.inspect_pair(*frames, observer=lambda frame: next(rows))
        self.assertTrue(result["confirmed"], result)
        self.assertEqual((result["before_support"], result["after_support"]), (3, 4))
        self.assertFalse(result["selected_identity_verified"])

    def test_code36_three_stable_hover_failures_are_confirmed_refusals(self):
        for source in (77, 104, 126):
            frames, rows = saved_refusal_group(source)
            original = [f.copy() for f in frames]
            result = inspect_saved(frames, rows)
            self.assertTrue(result["no_effect"], result)
            self.assertFalse(result["confirmed"])
            self.assertTrue(result["refusal_semantics"]["unchanged"])
            self.assertTrue(all(change > simple.SUPPORT_MOTION_MAX for change in result["support_changes"]))
            self.assertTrue(all(np.array_equal(a, b) for a, b in zip(frames, original)))

    def test_code36_two_actual_unit_gains_still_confirm(self):
        for source in (72, 99):
            frames, rows = saved_refusal_group(source)
            result = inspect_saved(frames, rows)
            self.assertTrue(result["confirmed"], result)
            self.assertFalse(result["no_effect"])

    def test_stable_hp_change_with_same_units_and_hand_is_not_refusal(self):
        frames, rows = saved_refusal_group()
        fields = rows[0]["refusal_regions"]
        old_hp = next(f["roi"] for f in fields if f["field"] == "unit_0_stat_2")
        donor_hp = next(f["roi"] for f in fields if f["field"] == "unit_1_stat_2")
        x0, y0, x1, y1 = old_hp
        a, b, c, d = donor_hp
        donor = cv2.resize(frames[0][b:d, a:c], (x1-x0, y1-y0))
        for frame in frames[1:]:
            frame[y0:y1, x0:x1] = donor
        result = inspect_saved(frames, rows)
        self.assertFalse(result["no_effect"], result)
        self.assertEqual(result["reason"], "support_semantic_field_changed_or_unknown")

    def test_stable_hp_color_change_is_not_refusal(self):
        frames, rows = saved_refusal_group()
        x0, y0, x1, y1 = next(f["roi"] for f in rows[0]["refusal_regions"] if f["field"] == "unit_0_stat_2")
        for frame in frames[1:]:
            patch = frame[y0:y1, x0:x1]
            hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
            patch[(hsv[:, :, 2] >= 160) & (hsv[:, :, 1] < 80)] = (40, 220, 40)
        result = inspect_saved(frames, rows)
        self.assertFalse(result["no_effect"], result)
        self.assertEqual(result["reason"], "support_semantic_field_changed_or_unknown")

    def test_stable_operation_change_is_not_refusal(self):
        frames, rows = saved_refusal_group()
        x0, y0, x1, y1 = next(f["roi"] for f in rows[0]["refusal_regions"] if f["field"] == "unit_0_operation")
        for frame in frames[1:]:
            frame[y0+3:y1-3, x0+3:x1-3] = 0
        result = inspect_saved(frames, rows)
        self.assertFalse(result["no_effect"], result)
        self.assertEqual(result["reason"], "support_semantic_field_changed_or_unknown")

    def test_stable_hq_shield_change_is_not_refusal(self):
        frames, rows = saved_refusal_group()
        x0, y0, x1, y1 = next(f["roi"] for f in rows[0]["refusal_regions"] if f["field"] == "hq_full_shield")
        for frame in frames[1:]:
            frame[y0+3:y1-3, x0+3:x1-3] = 0
        result = inspect_saved(frames, rows)
        self.assertFalse(result["no_effect"], result)
        self.assertEqual(result["reason"], "support_semantic_field_changed_or_unknown")

    def test_small_persistent_hand_effect_below_gain_threshold_is_not_refusal(self):
        frames, rows = saved_refusal_group()
        for frame in frames[1:]:
            frame[620:640, 600:620] = (255, 255, 255)
        result = inspect_saved(frames, rows)
        self.assertTrue(all(simple.REFUSAL_HAND_CHANGE_MAX < c < simple.HAND_CHANGE_MIN for c in result["hand_changes"]))
        self.assertFalse(result["no_effect"], result)

    def test_unknown_semantics_and_source_geometry_drift_cannot_count_refusal(self):
        frames, rows = saved_refusal_group()
        rows[0]["refusal_regions"] = []
        self.assertFalse(inspect_saved(frames, rows)["no_effect"])
        frames, rows = saved_refusal_group()
        for row_ in rows[1:]:
            row_["cards"][0]["cx"] = rows[0]["cards"][0]["cx"] + 4
        self.assertFalse(inspect_saved(frames, rows)["no_effect"])


class TypeSamplingRegressionTests(unittest.TestCase):
    def patches(self, source=96):
        manifest, frames = code38_semantic_patches()
        group = next(group for group in manifest["groups"] if group["ids"][0] == source)
        row_ = copy.deepcopy(group["observations"][0])
        row_["refusal_regions"] = [copy.deepcopy(group["type_region"])]
        return [frames[str(fid)].copy() for fid in group["ids"]], row_

    def test_real_code38_type_edges_pass_without_lowering_original_threshold(self):
        for source in (96, 136):
            frames, row_ = self.patches(source)
            originals = [frame.copy() for frame in frames]
            roi = row_["refusal_regions"][0]["roi"]
            original_scores = [simple.compare_patch(frames[0], post, roi) for post in frames[1:]]
            self.assertTrue(all(score < .93 for score in original_scores), original_scores)
            result = simple.unchanged_support_fields(*frames, row_)
            self.assertTrue(result["unchanged"], result)
            field = result["fields"][0]
            self.assertEqual(field["integer_scores"], original_scores)
            self.assertTrue(field["type_subpixel_search"])
            self.assertTrue(all(score > .97 for score in field["scores"]), field)
            self.assertEqual(simple.REFUSAL_PATCH_CORRELATION_MIN, .93)
            self.assertEqual(simple.REFUSAL_PATCH_SEARCH_RADIUS, 3)
            self.assertTrue(all(np.array_equal(a, b) for a, b in zip(frames, originals)))

    def test_true_donor_type_attack_hp_and_hp_color_changes_still_disagree(self):
        manifest, frames = code38_semantic_patches()
        for negative in manifest["negatives"]:
            source = frames[str(negative["source_id"])].copy()
            post = frames[negative["label"]].copy()
            row_ = copy.deepcopy(negative["observations"][0])
            row_["refusal_regions"] = copy.deepcopy(negative["regions"])
            result = simple.unchanged_support_fields(source, post, post.copy(), row_)
            self.assertFalse(result["unchanged"], (negative["label"], result))
            self.assertEqual(result["reason"], "support_semantic_field_changed_or_unknown")
            changed = next(field for field in result["fields"]
                           if field["field"] == negative["changed_field"])
            self.assertTrue(all(score < .93 for score in changed["scores"]), changed)
            if negative["changed_field"] != "unit_0_stat_1":
                self.assertNotIn("type_subpixel_search", changed)

    def test_two_stat_or_unknown_unit_type_cannot_enable_fractional_sampling(self):
        for variant in ("two_stat", "unknown_type"):
            frames, row_ = self.patches()
            unit_ = next(card for card in row_["cards"] if card.get("row_kind") == "unit")
            if variant == "two_stat":
                unit_["stat_boxes"] = unit_["stat_boxes"][1:]
            else:
                unit_["type"] = "unknown"
            with mock.patch("mobile_board._type_stat_plate", return_value=True) as proof:
                result = simple.unchanged_support_fields(*frames, row_)
            self.assertFalse(result["unchanged"], result)
            self.assertNotIn("type_subpixel_search", result["fields"][0])
            proof.assert_not_called()

    def test_type_plate_must_be_proved_on_source_pixels(self):
        frames, row_ = self.patches()
        with mock.patch("mobile_board._type_stat_plate", return_value=False) as proof:
            result = simple.unchanged_support_fields(*frames, row_)
        self.assertFalse(result["unchanged"], result)
        self.assertNotIn("type_subpixel_search", result["fields"][0])
        proof.assert_called_once()

    def test_numeric_roi_cannot_gain_permission_from_type_field_name(self):
        manifest, frames = code38_semantic_patches()
        negative = next(case for case in manifest["negatives"] if "attack1-to-attack3" in case["label"])
        row_ = copy.deepcopy(negative["observations"][0])
        roi = next(field["roi"] for field in negative["regions"] if field["field"] == "unit_0_stat_0")
        row_["refusal_regions"] = [{"field": "unit_0_stat_1", "roi": roi}]
        post = frames[negative["label"]]
        result = simple.unchanged_support_fields(frames["96"], post, post, row_)
        self.assertFalse(result["unchanged"], result)
        self.assertNotIn("type_subpixel_search", result["fields"][0])

    def test_shift_outside_three_pixels_cannot_be_rescued_by_type_sampling(self):
        frames, row_ = self.patches()
        roi = row_["refusal_regions"][0]["roi"]
        shifted = cv2.warpAffine(frames[1], np.float32([[1, 0, 3], [0, 1, 0]]), (1280, 720))
        x0, y0, x1, y1 = roi
        mx, my = np.meshgrid(np.arange(x0, x1, dtype=np.float32),
                             np.arange(y0, y1, dtype=np.float32))
        outside = cv2.remap(shifted, mx+4.5, my+.25, cv2.INTER_LINEAR)
        diagnostic = float(cv2.matchTemplate(outside, frames[0][y0:y1, x0:x1],
                                            cv2.TM_CCOEFF_NORMED)[0, 0])
        self.assertGreater(diagnostic, .97)
        result = simple.unchanged_support_fields(frames[0], shifted, shifted, row_)
        self.assertFalse(result["unchanged"], result)
        self.assertTrue(all(score < .93 for score in result["fields"][0]["scores"]))

    def test_integer_pass_does_not_run_subpixel_sampling(self):
        frames, row_ = self.patches()
        roi = row_["refusal_regions"][0]["roi"]
        with mock.patch.object(simple.cv2, "remap", side_effect=AssertionError("unexpected interpolation")):
            score = simple.compare_patch(frames[0], frames[0].copy(), roi, type_subpixel=True)
        self.assertGreater(score, .99)


class SimpleDeployRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = 1000
        self.calls = []
        self.reply = {"accepted": True, "completed": True, "reason": "completed"}
        bridge = types.SimpleNamespace(elapsedRealtime=lambda: self.clock, isCancelled=lambda: False,
            emit=lambda e: None, dispatch=lambda request: (self.calls.append(json.loads(request)) or json.dumps(self.reply)))
        self.rt = runtime.Runtime(bridge, self.temp.name, self.temp.name,
                                  runtime.options_from_json('{"read_only":false,"max_inputs":10}'))
        self.frame = np.zeros((720, 1280, 3), np.uint8)
        synthetic_shield(self.frame)
        self.rt.last_frame = self.frame
        self.rt.last_id = 1
        self.rt.last_info = {"state": "in_game", "button": "white", "choice_modal": False,
            "transition_reason": "", "captured_elapsed_ms": self.clock, "frame_id": 1,
            "source_width": 1920, "source_height": 1080, "foreground_generation": 1}
        self.rt.engine = types.SimpleNamespace(turns_seen=2, _combat_decision_context={},
                                               _allow_deploy_attempt=lambda *args: True)
        self.rt.mb = types.SimpleNamespace(BOARD_SAMPLE_GAP=.25, BOARD_MOTION_MAX=.008,
                                           board_motion=lambda *args: 0)
        self.rt.mh = types.SimpleNamespace(_LAST_DEPLOY_ATTEMPT=None, _LAST_DEPLOY_PENDING=None)
        self.rt._find_raw_hand = mock.Mock(return_value=[])
        self.rt._core_find_hand = self.rt._find_raw_hand
        self.rt.filter_deploy_units = mock.Mock(return_value=[])
        self.rt.capture = self.capture
        self.rt.context = "deploy"
        self.row_patch = mock.patch.object(simple, "support_observation", return_value=row(0))
        self.row_patch.start()
        self.observe_patch = mock.patch.object(simple, "observe", return_value=row(0))
        self.observe_patch.start()
        self.regions_patch = mock.patch.object(simple, "refusal_regions", return_value=row(0)["refusal_regions"])
        self.regions_patch.start()
        self.sleep_patch = mock.patch.object(runtime.time, "sleep", side_effect=self.sleep)
        self.sleep_patch.start()

    def tearDown(self):
        self.sleep_patch.stop()
        self.row_patch.stop()
        self.observe_patch.stop()
        self.regions_patch.stop()
        self.rt.events.close()
        self.temp.cleanup()

    def sleep(self, seconds):
        self.clock += int(seconds * 1000)

    def capture(self):
        self.rt.last_id += 1
        self.rt.last_frame = self.frame.copy()
        self.rt.last_info = dict(self.rt.last_info, frame_id=self.rt.last_id, captured_elapsed_ms=self.clock)
        return self.rt.last_frame

    def run_hook(self, evidence=None):
        if evidence is None:
            return self.rt.wrap_hook("deploy", self.rt.simple_deploy)(self.frame)
        with mock.patch.object(simple, "inspect_pair", return_value=evidence):
            return self.rt.wrap_hook("deploy", self.rt.simple_deploy)(self.frame)

    def test_live_blind_plan_reaches_bridge_and_bypasses_old_material_gate(self):
        with mock.patch("apk_deploy_target.inspect_clear", side_effect=AssertionError("old surface guard")):
            result = self.run_hook()
        self.assertFalse(result[0])
        self.assertEqual(len(self.calls), 1)
        packet = self.calls[0]
        self.assertEqual((packet["from"], packet["to"], packet["duration_ms"]), ([640, 665], [440, 500], 900))
        self.assertEqual(packet["path_points"], [[640, 665], [640, 575], [440, 500]])
        self.assertEqual(self.rt.report["hooks"][-1]["verification"], "confirmed_refusal")

    def test_completed_stable_refusal_does_not_poison_campaign_or_claim_success(self):
        self.run_hook()
        for key in ("unconfirmed_inputs", "unconfirmed_skipped", "actions_confirmed", "failed_inputs"):
            self.assertEqual(self.rt.report[key], 0, key)
        self.assertEqual(self.rt.report["deployment_refusals_confirmed"], 1)
        self.assertEqual(self.rt.report["game_inputs"], 1)
        self.assertTrue(self.rt.mh._LAST_DEPLOY_ATTEMPT["input_sent"])
        self.assertEqual(self.rt.mh._LAST_DEPLOY_ATTEMPT["badge"]["kind"], "unknown")
        self.assertIsNone(self.rt.mh._LAST_DEPLOY_PENDING)
        self.assertGreaterEqual(self.rt.report["hooks"][-1]["deployment_boundary_evidence"]["late_refusal_observation"], True)

    def test_refusal_same_turn_does_not_dispatch_again_next_turn_can(self):
        self.run_hook()
        self.run_hook()
        self.assertEqual(len(self.calls), 1)
        self.rt.engine.turns_seen += 1
        self.run_hook()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.rt.report["deployment_refusals_confirmed"], 2)

    def test_confirmed_gain_counts_as_action_without_identity_claim(self):
        evidence = {"confirmed": True, "no_effect": False, "reason": "persistent_support_unit_gain_and_hand_change",
                    "selected_identity_verified": False}
        self.assertTrue(self.run_hook(evidence)[0])
        self.assertEqual(self.rt.report["actions_confirmed"], 1)
        self.assertEqual(self.rt.report["unconfirmed_inputs"], 0)
        self.assertFalse(self.rt.report["inputs"][0]["deployment_plan"]["selected_identity_verified"])

    def test_unknown_consumed_order_remains_unconfirmed_and_bounded(self):
        evidence = {"confirmed": False, "no_effect": False, "reason": "hand_changed_without_persistent_unit_gain"}
        self.assertFalse(self.run_hook(evidence)[0])
        self.assertEqual(self.rt.report["unconfirmed_inputs"], 1)
        self.assertEqual(self.rt.report["failed_inputs"], 0)
        self.assertEqual(self.rt.report["deployment_refusals_confirmed"], 0)
        self.assertEqual(len(self.calls), 1)

    def test_unknown_deployments_across_turns_continue_without_same_turn_replay(self):
        evidence = {"confirmed": False, "no_effect": False, "reason": "support_row_incomplete"}
        for turn in (6, 7, 8):
            self.rt.engine.turns_seen = turn
            self.assertFalse(self.run_hook(dict(evidence))[0])
            self.assertEqual(self.rt.report["hooks"][-1]["verification"], "unconfirmed")
            self.assertFalse(self.run_hook(dict(evidence))[0])
            self.assertEqual(len(self.calls), turn - 5)
        self.assertEqual(self.rt.report["unconfirmed_inputs"], 3)
        self.assertEqual(self.rt.report["actions_confirmed"], 0)
        self.assertEqual(self.rt.report["unconfirmed_skipped"], 0)
        self.assertEqual(self.rt.failed_inputs, 0)
        self.assertTrue(all(p["reply"]["accepted"] and p["reply"]["completed"]
                            for p in self.rt.report["inputs"]))

    def test_interrupted_deployment_observation_still_counts_failure(self):
        with mock.patch.object(simple, "inspect_pair", side_effect=runtime.Stop("cancelled")):
            with self.assertRaisesRegex(runtime.Stop, "cancelled"):
                self.run_hook()
        self.assertEqual(self.rt.failed_inputs, 1)
        self.assertEqual(self.rt.report["unconfirmed_inputs"], 1)
        self.assertTrue(self.rt.report["hooks"][-1]["terminated"])

    def test_unbound_unknown_evidence_still_counts_failure(self):
        evidence = {"confirmed": False, "no_effect": False, "reason": "support_row_incomplete"}
        with mock.patch.object(simple, "inspect_pair", return_value=evidence):
            result = self.rt.simple_deploy(self.frame)
        self.rt._deployment_boundary_evidence["source_frame_id"] = -1
        self.rt._record_hook("deploy", 0, 1, result)
        self.assertEqual(self.rt.failed_inputs, 1)
        self.assertEqual(self.rt.report["unconfirmed_inputs"], 1)

    def test_accepted_incomplete_never_replays_or_counts_refusal(self):
        self.reply.update(completed=False, reason="gesture_cancelled")
        with self.assertRaisesRegex(runtime.Stop, "gesture_not_completed"):
            self.run_hook()
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.rt.mh._LAST_DEPLOY_ATTEMPT["input_sent"])
        self.assertEqual(self.rt.report["unconfirmed_inputs"], 1)
        self.assertEqual(self.rt.failed_inputs, 1)
        self.assertEqual(self.rt.report["deployment_refusals_confirmed"], 0)

    def test_java_age_rejection_replans_without_claiming_input(self):
        self.reply.update(accepted=False, completed=False, reason="frame_age_expired")
        with self.assertRaises(runtime.Replan):
            self.run_hook()
        self.assertFalse(self.rt.mh._LAST_DEPLOY_ATTEMPT["input_sent"])
        self.assertEqual(self.rt.report["game_inputs"], 0)
        self.assertIsNone(self.rt._simple_deployment_plan)

    def test_full_or_unknown_support_has_no_dispatch_and_no_pending(self):
        for support in (row(4), dict(row(0), count=None, reason="incomplete")):
            with mock.patch.object(simple, "support_observation", return_value=support):
                result = self.run_hook()
            self.assertFalse(result[0])
        self.assertEqual(self.calls, [])
        self.assertIsNone(self.rt.mh._LAST_DEPLOY_PENDING)

    def test_known_unit_hook_uses_approved_origin(self):
        self.rt.filter_deploy_units.return_value = [unit()]
        self.run_hook()
        self.assertEqual(self.calls[0]["from"], [489, 657])
        self.assertEqual(self.rt.report["inputs"][0]["deployment_plan"]["mode"], "approved_unit")

    def test_core_attempt_budget_does_not_authorize_blind_retry(self):
        self.rt.filter_deploy_units.return_value = [unit()]
        self.rt.engine._allow_deploy_attempt = lambda *args: False
        self.assertEqual(self.run_hook(), (False, "deployment_retry_budget_exhausted"))
        self.assertEqual(self.calls, [])

    def test_fresh_hand_motion_skips_this_drag_without_blocking_other_actions(self):
        self.frame[610:700, 250:1050] = 100
        before = np.zeros_like(self.frame)
        self.assertEqual(self.rt.wrap_hook("deploy", self.rt.simple_deploy)(before),
                         (False, "deployment_hand_still_moving"))
        self.assertEqual(self.calls, [])
        self.assertIsNone(self.rt.mh._LAST_DEPLOY_PENDING)

    def test_unrelated_board_motion_does_not_block_fresh_hand_deployment(self):
        self.rt.mb.board_motion = mock.Mock(side_effect=AssertionError("unrelated whole-board gate"))
        self.run_hook()
        self.assertEqual(len(self.calls), 1)
        self.rt.mb.board_motion.assert_not_called()

    def modal_sequence(self, last_modal_post=None, moving=False, consumed=False):
        original = self.rt.capture
        self.modal_posts = 0
        gate = runtime.ChoiceModalGate(.008)
        def modal_capture():
            frame = original()
            if self.calls:
                self.modal_posts += 1
                present = last_modal_post is None or self.modal_posts <= last_modal_post
                self.rt.last_info["choice_modal"] = present
                state = gate.observe(present, self.clock / 1000, .03 if moving else 0)
                self.rt.last_info["choice_gate"] = state
                if consumed:
                    frame[610:700, 250:1050] = 100
                if state in ("confirmed", "timeout"):
                    raise runtime.Stop("choice_modal_" + state)
            return frame
        self.rt.capture = modal_capture
        simple.observe.side_effect = lambda frame: dict(row(0), choice_modal=self.rt.last_info["choice_modal"])

    def test_persistent_stable_choice_uses_capture_gate_without_targeting(self):
        self.modal_sequence()
        with self.assertRaisesRegex(runtime.Stop, "^choice_modal_confirmed$"):
            self.run_hook()
        self.assertGreaterEqual(self.modal_posts, 7)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.rt.report["unconfirmed_inputs"], 1)

    def test_draw_animation_outlasts_five_pairs_and_clears_without_replay(self):
        self.modal_sequence(last_modal_post=7, moving=True)
        result = self.run_hook()
        self.assertEqual(result, (False, "stable_no_deployment_effect"))
        evidence = self.rt.report["hooks"][-1]["deployment_boundary_evidence"]
        self.assertTrue(evidence["animation_observation_extended"])
        self.assertGreater(evidence["post_observation_pair"], 5)
        self.assertFalse(evidence["confirmed"])
        self.assertEqual(self.rt.report["deployment_refusals_confirmed"], 1)
        self.assertEqual(len(self.calls), 1)

    def test_consumed_order_after_animation_keeps_unknown_unit_outcome(self):
        self.modal_sequence(last_modal_post=7, moving=True, consumed=True)
        self.assertFalse(self.run_hook()[0])
        hook = self.rt.report["hooks"][-1]
        self.assertEqual(hook["detail"], "hand_changed_without_persistent_unit_gain")
        self.assertFalse(hook["deployment_boundary_evidence"]["confirmed"])
        self.assertEqual(self.rt.report["unconfirmed_inputs"], 1)
        self.assertEqual(self.rt.report["actions_confirmed"], 0)
        self.assertEqual(self.rt.report["deployment_refusals_confirmed"], 0)
        self.assertEqual(len(self.calls), 1)

    def test_continuously_moving_display_is_bounded_and_remains_unknown(self):
        self.modal_sequence(moving=True)
        self.assertEqual(self.run_hook(), (False, "transition_or_choice_modal"))
        evidence = self.rt.report["hooks"][-1]["deployment_boundary_evidence"]
        self.assertGreaterEqual(evidence["post_observation_elapsed_ms"], 12000)
        self.assertLess(evidence["post_observation_elapsed_ms"], 12500)
        self.assertEqual(self.rt.report["unconfirmed_inputs"], 1)
        self.assertEqual(self.rt.report["actions_confirmed"], 0)
        self.assertEqual(len(self.calls), 1)


# Lossless code38 semantic ROI crops and +/-3px context, not full screenshots.
# Original PNG/donor hashes and crop hashes are inside the verified payload.
_CODE38_PATCH_PAYLOAD_SHA256 = "49674f62bde0b119ab3d1a54701505bcd1f546fc6e3e9dfd5fc65500149ec2dd"
_CODE38_PATCH_PAYLOAD = (
    "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"
    "kyPFVSk5Amg7YiWaABstQivUKoUszNbQs4UsDNAiFWYjtoZomug/UGNUPL5arVGLUHivlc0L626v6/2QizxyuGox8ZDUcDFTC5Qi"
    "FiXSCtVCsZrD10J1osQqlRKKJiZtNiiBhxGch8lJoH5FWXhV80avE7yqemtESqgGWj6HxWFxKYrisVRQUvmYpVU8rkakRdPkUGKx"
    "gFQeV4hxRCzkC1RqNqXksCn05dTW+nqNYETi/DO1M5vtY35lCbu3nNPB7ptsm5F1r+j6lMYB9fogtTmsMw/rd0bWLCOrlmHD3pBu"
    "d4Da7ldv9apMPYqNHiX57JYZu+XrXVJDt9QwoNke0u72KzfbZuWtk5L6tp6i2qbCmsackqqswtpy3sCXqeWFXYc+eGkIX69Gbpm0"
    "Fr1bj90jmc4ekTbOHo3RO6S1yF38Nyc3hpMbffjGQNK1PnhtCJFjHEgPvdOmgy6JmtU7WsVtza9sYQ8uzpgOKG9U6zvVuE/UrrDS"
    "EVTYfHKbT2HzK+1+pSOgcgRVzpDahRQmCT9zn2iOI2p3RIXfO0OyI6/0wCM9OF459MptfonFqXAEZfbAhHFPMDpbxW0fNeypjyM4"
    "3zEjEY1M8QfGmtt7Gr50Nojb68VfkT6Lvn4Wf21obW9o7Whs62z62o0fNHf0tHT2tnT2sbr6kdjdSIOcnkHhyFT7zJJ4bGZ2w6IP"
    "XuDJR7Smxq+DMnvQELoapYw5ZZWfiko+Fha9zytg0ru8fKTk13jKRyr8kJ6SZz4WFmcVl2aXVnD7RlAyWxffJ417LV1jak9sNXw9"
    "ol7F5b9k5yTT2+zc1K9PZ7ISZ7ISn1k573Pz8sor3+XmMV+RPovaUOY7V78u7Nr5w/OU/3w1dNWzpEBGUm5I0tPXnNwaoP3QWEVT"
    "y7uc3AwpyAKvu29Yrv5UWMScxJmm9h6JxWW+/L5kcYknJLrAhSF4+XV6iTxJdvpzJlJT69eNUOzg7vuaP9zY+vVdbn4ya/mV1QPL"
    "Mspx3Chui2eE/lOtoHXefLh5/k165G+bkevQgIOXbZPzb3PSpDA3wScygvscPvx69O23vat7Yf8w8zzvcvIqm1mSbcuqL9TY2pZ2"
    "eXZODV88vb63FrlZsQfb5pSMlC8Tsxk/SxVXLxQZ/SdHj78d3H4bkKxASlZRsWhwZNUb3D67YnV0PavBnNLGlnH9pjZwIbF6vy5Q"
    "usAl+iPaXlJKWr1n5eCeDaJWgycIKUePv+rcPvHgyCSl37u6wxn5vi27pOz54+WWV45qN9Yit8uHvk6JXh+80vvPBUMTzxsVaTx5"
    "+Z3Tc9un10TEt3iy3n+HOBwcPvzoXZCgSJ9f+6m4dFi9iqFjyertlq3pglda7ym3b5hUwbMfN4i+bJ+niUhN1vsfyFfqVcljtNhR"
    "zdrG2cOS1dOvMulC1xpPDP33hQ6Sk9szLzl8/NWWcf/H3+JyH38VDgw/XZj11DghZYxa37r8LneGpzcPVyP3KtdJfWv787LF5V9G"
    "J5I3t337N+YA7c0UjqFpoY7KGppelILKmjRs7Vz/pnJH5I6QMfagdIXRvJ93c+Tl6/jUZuQso8QgpW18qqy+qbyh+YXapFNOacX0"
    "+s7Oza+UN4YGtn76iEG4hid8+cclZdKd/WdSfnTPLT5vKk/ZycrJLauc2djbuf7VfPVjNXyzfvpNduSraOEmf5Da8et4AvPZVbIu"
    "bKTcSBtjd/Zkjmnpl+eWV81t7psvfyAZTm6RF9mhr6KZk/l7+iu7q8dy85BR72harM6uF2+evDCvonp+6wBj8ubZN0x8xtNHqdVT"
    "3sR+8akw0i5u7R7cfbMxIjDOPP5qffjB6+lPK6uszKGPlmLFOLZx+mCM3EPK8sFxWWPLMynZzAGvd2D7jHQZ69132Z718P4HBKFV"
    "vH2xXhKDOSPFdP5tPfZgPP2GJLG4SxuaXy7hrJyK5pbt8yv0Gq3L1zW7sBk9x/G4WosWmPH8aXmpJCVmOv++ARHRR2PscWnPWVzf"
    "lFkCiYNqNtd8dkkGk8Xl4to62f4h8qI8tH8oKEw+ScZ8xEiZI3n5juysRR/WIg+LO/biuoZ4KWUUQlZOLU+4d30PKV8nphOzwA8M"
    "xVWslxpMskIra5gSQzKc3K+e3M+bbYU19Ym6yI7LSvye3zdguX44uP8uHBzBeWg9TKH1L0npQst+QUoiL+sxaFmQcmegpRTV1j9v"
    "J8yZeqF45+IGgmq5Apx8n5s/olCjy8xvbH0qKs5oKhl5QTeBLqcP3RrCkHJUmJSSldbXMLnQbexq6/SyHO2Q/isOjMGIxnGcX1GZ"
    "8ftkKqj+PLd1uH76AHVRH76DoIVte1G8XtKqBpPL14kZzPXm2IXa5iqsrmXOZxWVzK1vbsUua7j8Z20yfnl5MwcPDynIji50i7S8"
    "76kTtiUKNjul5ecW19VXsbml9Y1lDY3QzeIZzMvHODZjWGd1dn/IL8qUQh+UNbEXtm2rMdIfdcEbbehm5TAA9eldXsFbRgtK1j79"
    "+eZZD3qTlY2SxI+RWfqv2W/om7+JZyQ3u7S8sa0LHUR/ghq50QZvNP4rpSvWI1E1tHWVt3AKquuySsqRPhWXZJWUQeHEuJdbUZ1T"
    "VoEEpTG7pBxzRzb5TVlWUelHoo4WfygoQkLDgFzollBg+lcohT2kD11r/ZcQgaT2XqwcBqc3rOP67UG5oXdZ072o7FpQIHXOyzvp"
    "g465FaSv05K2ycUvEwut43PisVnh8BQUBv7AOKd3mAU9uXdYMDQpGJ7sXVYv77nV7qgueK3xXig9F8rjc5X7TOE8XbFHFY6Ywh6R"
    "2SJy5thFn8Rf3adK96n6+FzhiK4chWVHUPLDUmtg2eqX2cLLh6GVI5Jk9rDcfqJwnCidEYX9RH18qg1cQYrMGZPaIitHJ0jSw5P4"
    "gTVMjm0nctzTHlvGDxxRqe0ECSKYG64chpatQSkk4qnsEYUzimO5Myp3xmT2E5kjonBFcXOl50zhOVuyBhcPggt7voVd3+Kef4Ek"
    "35IlQA72A0v7waWD0KIFB/5FC37gm9/xTKzbF/e887tecnLPt2jxSw4CksPgsjUgsdIHh8ElkkLkwewny/aT/OrmP//y6U+/fPzL"
    "+9y3eVVv86vffCh486nozcfCd3mVn0qbsssaC+vY9e1DwinF1wXtoG5vSL83YtjrlK7xJ1bqe6bL+H359eISTl8xpze3SvyxoP4v"
    "b/P+9OdP//Kvb/71zx/+/JdP2YW1xfXcv7zL+cvbrDfv0DtKPpQ0vMst/1hc9z6/4kNBRSW3nd0/3adYkxx4tYFLaG5QRZDQ1zD9"
    "QTtdOvD1KU2sgbn6jolSbm9RU3dR/de3WaW0lF/+9U9v373Pzy1pKGe1vcsu/lBUm1PFySqtz61uKWhsLeV0fP46yB+em1w/ULoj"
    "OnL/S6ABEvRDzXEUn6vBS+PJjTFyqw9dqY5jk8YD3shSU89UrXgwr7LlT2+y/uVP7/7lT7/8+c2nT7kVFdzOt5+KPpU25je2lbZ8"
    "qRZ2fe4ca5fo5radaDAa7zkUwuX942HVqmBwjN0z2NzRC+Jjdw3w+kcH5doV6zHYZz16B85atvpGDbu84YXyptb3WSV//iX7X//8"
    "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"
    "LswSVnJKW7kVHdn5VTmiWk55W26LhF8/ImybFnVJhY3feDW97PIOVmkbp6qPW9MvbBjkf+3mlrZnCco/fc7+97/T/vj3lz/++PLn"
    "p8wJg41fVvdXBvuvDO7nLEGGoOILGwZaXlpO3pdsYWZuZY6oIYMHeKSioK6rvFdSMzzXPqsfUJr6lg3NU4rKAVlRx1he4xCnvDW/"
    "eSS3boBT0soubPzzc9anv3L+9cfnf/+Z8SWNM2V05JY3fErL+fOvjE9pLCwOvwzUpbHy4fqFnc8uqhU1dLdMzE0aLIrTwLo3rL+M"
    "bAZIesTLRzAX5yyugdXtmm+y4rbR/PqBwhZxfm3vlyzBH39m/OvP9H/9+/OXdJ5k+7igtv1LFu9LFj+dDfWWl5VbmiOq4ZQ2AGQW"
    "1Xf0zqvnDs7haRuwGF090Weg/rABrAXEmM8AScAQUrluxvUHDeL56oHp8q5xXv7XT59z/viU8e9PaZ8+Z0m2HUVNfemcAqh8bnnr"
    "afDpLBg5uX0wuq/RRw5QMOBi183C/vHQiubbkgoE7g2YDvJFbrJ2TM20T8oGF5Xze0fr7ltY4mGe117cbbmuziP/+H/8L/+P//nn"
    "pwzQUtz6LUNQyipp4le1H1/fWXw3m2denQem6yeN62Z+1zGi1DUMiMFW5BWXgpHfJVtYODjRum9AY25FFUwI7AJRRVtnx+TMhHZL"
    "eQLg8QVezOAJnj7+Cvz635/+ypbunFX0TGYKK7Lyqwqbh6y+K/2pT3UWwChXf1hmsraMTolqG3lFJVl8xEE5+YW5ZZWV7T3VHX2l"
    "ze3ZdJJ3TgaHz8orAEty2rAPdQs/B3C0HXh0vfyPz2n8afPZ16H5HFFdVl6VqHVk69yz6vDpfGGtJyTfsXdI5IW1DTBrMbcrYf5H"
    "fh6cyvhpTG9VEh1W1z8sXttQnHg3rjAId+/6KT1bIDGf1YyvCVsnBdWdtcNzikMnkh67goD+GofHi+qa2FEnGTyBLSmvbO3ok80N"
    "LynESnX7+GRZU0suZuPlRZdsND75JeXtEzLlqR8NJP+DsKxWunteM6kp+aasHVsZXDWungRUzuDcrqOu9xu3qDRbIKSI/TN5/Lax"
    "iVWrY/PCvx96wGTc4afd4P2G26ewOtrHJjJ5fKa7bF5F9ZjagL6vgUjb5Jz8wF07pakUq4c0B7I9sO0flCeB4RVNYXUtHTFHStEm"
    "Hjde3qCHZDSvHOV7efT9p+35b/hX64g4ztpNKGug6ub2HFBvCza3bM/ZINM3SHVzh14FRpE8QkE6x6cLK6tjLs2wBG96LolTJfpw"
    "2l9/HEa+x/wVKZdFvduXjz+J5woRlFX0ypdgOYYSSXZOa8eWmmd0itObNeet6vxmVKlr7OnPK6uIeVsNzi8d3D8d3EWsYLrcP/XL"
    "52t7+rslsjnTnuP7r2j2tx9d1EFPTpy7prSxdWbbArOExHxSN7rQJtfCFL1su5jbPemakte0duSWlMa0VHd0d05IWkfG+qSz8Chu"
    "YVE6hucXQOtTyRqoEvVIZ5JoW1h5hf3zCr0vLN09qxme71negqVheutQvLbZNDD0taU9t7g0lnIlO1eYk5uXxRdSIbFpjISAsZR5"
    "UJ+dk5KkfC7wMk3DY9qL4LQJyzKwal52XI4oN7om5VWt7WX1jbzCorR3aefZbKognEJRNP0farFFvjf0Dyad1kFxylrawR6bNp82"
    "jK8MqXZWjvwjSn2bWFJS3yREtC54100RLNjGwaGB2YUxpRoTl5MOAN0M+nP0oCfuQZ0jzC9rbl/3BMc3D9tntGO6Q1hnh1d1YtUW"
    "DCiYslIzU1PSPDy6fn5hug5BN6C4lTBL45m7trc/yVU1S5Bb2dEDmAhQntTkGFSaZvddatedWG0Es0GyuQ+zSrJ3a1RaRsfsL3/b"
    "nv9mOvou7lkACCS9EhSka3puFSfPZ/mBa2bvfPXkSuu+H9MYYUhOGw4Kaxvf0UI6A1TX2tHJ2tGp6Spof3mjtGz5r3skM3HXU1pL"
    "QbdsUXV+BT0Zo2kcVyQ0CZOJj2u2OyWzueVVaUn+jdGmKayu+drZ3TIs7pmWSTe2LA/PFD3UduC2rqefqQWm64bBUZgPDYGnZfSS"
    "Cqrd9yrQsrHXPCoRVlTHqbdykr0omWxmuaXlKxZ7jGZnfE3DTKMA9/AomGdg+UYj6vxOe/GgdoenNvfBXExNuABvlSPMo/OZJmad"
    "EyvWjqPcRFNafSbJTck85IVVD7TM23ygRXPxoPVGpjYPavqGYNX4nGjYQ1vAkB+YXRyQz9f3DWRGU81CkWe3d0hZYMj816RGl8nl"
    "MX0OM2HOHICyRBaPAqtnQY07vO59khgs/QtrvJIy5tEb1M+MYdvy8EJl3tG7fLU9fYVf60S1dfX9gwZvgGajevs1odKmx90j6ZDn"
    "/vlVsHnAgFSehTTuh3VPBL31zHaotOg6S7cCTGJUGlbKy13n9CwfWKFFcKKOOttbn157ZfI0hjcsLKklja2wpoOWJUdg7Syk9TxC"
    "pU0brWBpDy5rC2saqOWP6mkFVV8V1iPr0/d45krSr6K5h5AySHFoQw4chqM1IIvOKfna2ZXeHwF7ePX0Vut+0Fw8So02rSe8eOhq"
    "HZOycY+FG5uRShqaFnYPoLvCA0EdGZhv8P7Qkzc8frnBVFLXwAxLgUm1rKVDZrTo0XXtcRYWr5MbTFjvAS1Wvf8JIMC08RDACKew"
    "OOY5AD/kF5e2jIhntkyzpp2VQ9vS3qF82yzRbkQd+Dkx/3lYx6Guhla0UBDcs/I9zFq8S0dQaUEYlaBl3fO47ouoXEGYbQD40ARu"
    "0fFCxYaQcGbkfItG3DAdjDlZucL86tpu2QKsVus+MJkiWu/93KEPOsAaAJDja+mWVesCG+kRMKbaFRpf3y5v7YKekEaPoLiPK+VX"
    "84XN3HNAbMjOF5W3dg7Mry1ZnNqL+41LhN5gas7uu5esntUjv+LoUm4+Up3fa9yRde+LPvB9zYmKanqHcssrs3AXCHspjBEMpMJ8"
    "o3WwsmOINFmtcvIK86tqGobGJnU7Kuct1Dw0Oh6D+iMwfc0hrHMpjnzKI//czrEKqw6K86zzvegun8GkAUA3qjLAaOWXVmQL8+FR"
    "3dKFWfPR7O5xj3xJWFEF5mteVW39oFisMmBC5It7nf9pwx+htfgiandIun28aHGtohYfagG8dhZSux7Xvc/45atXfeBF7b5bsDiH"
    "FfqGb2MgE1oTIEewQySbe3UDI81iiVi9BT0TKhneirz/kw4jW/FmHZNlhKaMdoCoCrsXZNl6ITcfy7btxOfWhjdmB3rSmo/gkxm8"
    "ccyQBBwoO8fy3eNZlJO5/dP5g3N4k4VDF14tzkWrC9Dxst0DS4nm4n580yrbOVk8dC/bwEK+BEAK6FUNTeN/1l2+6PzPMFqhk2s8"
    "EQ2eO9/DpAqAd43khVQ7g6qzW8CS6ot7jfdR48XvqOg0H9dr5CgZfXGdoY+TxA920w920w920w920w920w920w920w920w920w92"
    "0w920w920//Uk8T/A7GsKv8="
)

if __name__ == "__main__":
    unittest.main()
