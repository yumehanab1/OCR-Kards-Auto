"""User-authorized APK deployment without material or empty-slot matching.

Unknown middle-hand attempts remain unknown. Confirmation means an observed
hand change and persistent support-unit gain, never a card name or identity.
"""
from __future__ import annotations

from collections import Counter
import hashlib

import cv2
import numpy as np

TARGET = (440, 500)
MIDDLE_ORIGIN = (640, 665)
SUPPORT_ROI = (200, 415, 1120, 595)
HAND_ROI = (200, 595, 1100, 720)
SUPPORT_MOTION_MAX = .008
HAND_MOTION_MAX = .025
HAND_CHANGE_MIN = .02
REFUSAL_HAND_CHANGE_MAX = .001
REFUSAL_PATCH_CORRELATION_MIN = .93
REFUSAL_PATCH_SEARCH_RADIUS = 3
REFUSAL_TYPE_RESIDUAL_OFFSETS = (-.5, -.25, 0., .25, .5)
PLAN_KIND = "simple_support_count_v1"


def valid_frame(frame):
    return (isinstance(frame, np.ndarray) and frame.shape == (720, 1280, 3)
            and frame.dtype == np.uint8)


def pixel_hash(frame):
    return hashlib.blake2b(frame.tobytes(), digest_size=16).hexdigest()


def motion(a, b, roi):
    if not valid_frame(a) or not valid_frame(b):
        return 1.
    x0, y0, x1, y1 = roi
    old = cv2.GaussianBlur(a[y0:y1, x0:x1], (3, 3), 0)
    new = cv2.GaussianBlur(b[y0:y1, x0:x1], (3, 3), 0)
    return float((cv2.absdiff(old, new).max(axis=2) > 18).mean())


def support_observation(frame):
    """Count a complete HQ-anchored row; unknown must never become zero."""
    import apk_deploy_target
    cards, reason, evidence = apk_deploy_target._row(frame)
    complete = (reason == "complete_support_row" and isinstance(cards, list)
                and len([c for c in cards if c.get("row_kind") == "hq"]) == 1)
    count = len([c for c in cards if c.get("row_kind") == "unit"]) if complete else None
    if type(count) is int and not 0 <= count <= 4:
        count, reason = None, "support_count_out_of_range"
    return {"count": count, "reason": reason, "cards": cards, "hq": evidence.get("hq")}


def hand_layout(raw_hand):
    # Colors and resources changing within a turn must not restore a failed
    # attempt. A new true engine turn can retry a now-affordable middle card.
    return tuple(sorted((round(int(b["cx"]) / 16), round(int(b["cy"]) / 16),
                         str(b.get("kind", "unknown")))
                        for b in raw_hand if isinstance(b, dict)
                        and type(b.get("cx")) in (int, float)
                        and type(b.get("cy")) in (int, float)))


def retry_key(plan):
    return (plan["turn_id"], tuple(tuple(item) for item in plan["hand_layout"]), tuple(plan["origin"]))


class FailedLayoutLedger:
    """Blind failures block a turn/origin; approved units retain layout scope."""
    def __init__(self):
        self.failures = set()
        self.blind_failures = set()

    def allowed(self, plan):
        if (plan.get("mode") == "blind_middle"
                and (plan["turn_id"], tuple(plan["origin"])) in self.blind_failures):
            return False
        return retry_key(plan) not in self.failures

    def failed(self, plan):
        if plan.get("mode") == "blind_middle":
            self.blind_failures.add((plan["turn_id"], tuple(plan["origin"])))
        else:
            self.failures.add(retry_key(plan))


def make_plan(frame, info, units, raw_hand, approved_grab, ledger, row=None):
    row = support_observation(frame) if row is None else row
    count = row["count"]
    if type(count) is not int:
        return None, "support_count_unknown:" + row["reason"]
    if count >= 4:
        return None, "support_row_full"
    if not valid_frame(frame):
        return None, "invalid_frame"
    base = {"kind": PLAN_KIND, "frame_id": info["frame_id"], "turn_id": info["turn_id"],
            "captured_elapsed_ms": info["captured_elapsed_ms"],
            "foreground_generation": info["foreground_generation"],
            "source_hash": pixel_hash(frame), "support_before": count,
            "target": list(TARGET), "hand_layout": hand_layout(raw_hand),
            "selected_identity_verified": False, "cost": None, "credits_before": None,
            "consumed": False}
    for badge in units:
        origin = approved_grab(badge)
        if origin is None:
            continue
        approval = badge.get("apk_availability", {})
        plan = dict(base, mode="approved_unit", origin=list(origin), badge=dict(badge),
                    cost=approval.get("cost"), credits_before=approval.get("credits"),
                    plate=approval.get("plate"), grab=badge.get("apk_grab"))
        if ledger.allowed(plan):
            return plan, "approved_unit_to_simple_support_target"
    # Do not use a middle fallback to replay a known candidate just refused by
    # the attempt ledger. Only missing strict unit approval enables this path.
    if units:
        return None, "deployment_layout_attempts_exhausted"
    plan = dict(base, mode="blind_middle", origin=list(MIDDLE_ORIGIN),
                badge={"cx": MIDDLE_ORIGIN[0], "cy": MIDDLE_ORIGIN[1],
                       "kind": "unknown", "state": "unknown"})
    if not ledger.allowed(plan):
        return None, "middle_layout_already_failed"
    return plan, "user_authorized_unknown_middle_hand_attempt"


def validate_plan(plan, frame, info, gesture, units, approved_grab, row=None):
    """Reprove current count and source, independently of old surface gates."""
    if not isinstance(plan, dict) or plan.get("kind") != PLAN_KIND or plan.get("consumed") is not False:
        return "simple_plan_missing_or_consumed"
    if not valid_frame(frame) or plan.get("source_hash") != pixel_hash(frame):
        return "simple_plan_pixels_changed"
    for key in ("frame_id", "captured_elapsed_ms", "foreground_generation", "turn_id"):
        if type(info.get(key)) is not int or plan.get(key) != info[key]:
            return "simple_plan_capture_changed"
    if (tuple(gesture.get("from", ())) != tuple(plan.get("origin", ())) or
            tuple(gesture.get("to", ())) != TARGET or tuple(plan.get("target", ())) != TARGET):
        return "simple_plan_coordinates_changed"
    row = support_observation(frame) if row is None else row
    if type(row["count"]) is not int or row["count"] >= 4:
        return "simple_support_count_unknown_or_full"
    if row["count"] != plan.get("support_before"):
        return "simple_support_count_changed"
    if plan.get("mode") == "approved_unit":
        matches = [b for b in units if approved_grab(b) == tuple(plan["origin"])]
        if len(matches) != 1:
            return "simple_origin_not_unique_current_unit"
    elif plan.get("mode") == "blind_middle":
        if tuple(plan["origin"]) != MIDDLE_ORIGIN or units:
            return "simple_middle_fallback_not_current"
    else:
        return "simple_plan_mode_unknown"
    return None


def observe(frame):
    import mobile_board as board
    row = support_observation(frame)
    return dict(row, transition=board.board_transition_reason(frame),
                choice_modal=board.choice_modal(frame)[0])


def _signature(row):
    hq = row["hq"]
    return sorted((round((c["cx"] - hq["cx"]) / 144), c["type"])
                  for c in row["cards"] if c.get("row_kind") == "unit")


def refusal_regions(frame, row):
    """Actual operation/stat plates and full HQ shield, without reading values."""
    regions = []
    if not row.get("cards") or not row.get("hq"):
        return None
    for index, card in enumerate(row["cards"]):
        if card.get("row_kind") == "unit":
            boxes = card.get("stat_boxes")
            if not isinstance(boxes, (list, tuple)) or len(boxes) < 2:
                return None
            x, y = int(card["x"]), int(card["y"])
            regions.append({"field": f"unit_{index}_operation", "roi": [x, y, x+37, y+35]})
            for field, (sx, sy, sw, sh) in enumerate(boxes):
                regions.append({"field": f"unit_{index}_stat_{field}",
                                "roi": [int(sx), int(sy), int(sx+sw), int(sy+sh)]})
    try:
        import mobile_board as board
        shield, box = board.hq_hp.find_shield(frame, row["hq"])
    except ImportError:
        return None
    if shield is None or box is None:
        return None
    x, y, w, h = (int(v) for v in box)
    regions.append({"field": "hq_full_shield", "roi": [x, y, x+w, y+h]})
    return regions


def compare_patch(before, after, roi, *, type_subpixel=False):
    """Tolerate observed <=3px glow/drift; glyph changes must still disagree."""
    radius = REFUSAL_PATCH_SEARCH_RADIUS
    x0, y0, x1, y1 = (int(v) for v in roi)
    if not (radius <= x0 < x1 <= 1280-radius and radius <= y0 < y1 <= 720-radius):
        return None
    template = before[y0:y1, x0:x1]
    if min(template.shape[:2]) < 8 or float(template.std()) < 2.:
        return None
    search = after[y0-radius:y1+radius, x0-radius:x1+radius]
    _, score, _, best = cv2.minMaxLoc(cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED))
    score = float(score)
    if not np.isfinite(score):
        return None
    if not type_subpixel or score >= REFUSAL_PATCH_CORRELATION_MIN:
        return score
    # Only a separately proved type icon may compensate fractional sampling.
    # Residuals stay near the integer optimum and inside the original +/-3px.
    dx, dy = best[0] - radius, best[1] - radius
    mx, my = np.meshgrid(np.arange(x0, x1, dtype=np.float32),
                         np.arange(y0, y1, dtype=np.float32))
    for oy in REFUSAL_TYPE_RESIDUAL_OFFSETS:
        for ox in REFUSAL_TYPE_RESIDUAL_OFFSETS:
            sx, sy = dx + ox, dy + oy
            if abs(sx) > radius or abs(sy) > radius:
                continue
            patch = cv2.remap(after, mx + sx, my + sy, cv2.INTER_LINEAR)
            candidate = float(cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)[0, 0])
            if np.isfinite(candidate):
                score = max(score, candidate)
    return score


def _proven_type_regions(frame, row):
    """Bind compensation to actual central type plates, never an index alone."""
    import mobile_board as board
    import mobile_combat_vision as combat
    proven = {}
    for index, card in enumerate(row.get("cards", ())):
        boxes = card.get("stat_boxes")
        if (card.get("row_kind") != "unit" or card.get("type") not in combat.TYPES or
                not isinstance(boxes, (list, tuple)) or len(boxes) != 3):
            continue
        box = boxes[1]
        if (not isinstance(box, (list, tuple)) or len(box) != 4 or
                any(type(v) is not int for v in box)):
            continue
        x, y, w, h = box
        if not (0 <= x < x+w <= 1280 and 0 <= y < y+h <= 720):
            continue
        if board._type_stat_plate(frame, box):
            proven[f"unit_{index}_stat_1"] = (x, y, x+w, y+h)
    return proven


def unchanged_support_fields(before, previous, current, row):
    regions = row.get("refusal_regions")
    if regions is None:
        regions = refusal_regions(before, row)
    result = {"unchanged": False, "fields": [], "reason": "support_semantic_regions_unknown"}
    if not regions:
        return result
    proven_types = None
    for region in regions:
        scores = [compare_patch(before, frame, region["roi"]) for frame in (previous, current)]
        evidence = dict(region)
        if any(score is not None and score < REFUSAL_PATCH_CORRELATION_MIN for score in scores):
            if proven_types is None:
                proven_types = _proven_type_regions(before, row)
            if proven_types.get(region["field"]) == tuple(region["roi"]):
                evidence.update(integer_scores=scores, type_subpixel_search=True)
                scores = [compare_patch(before, frame, region["roi"], type_subpixel=True)
                          if score is not None and score < REFUSAL_PATCH_CORRELATION_MIN else score
                          for frame, score in zip((previous, current), scores)]
        result["fields"].append(dict(evidence, scores=scores))
        if any(score is None or score < REFUSAL_PATCH_CORRELATION_MIN for score in scores):
            result["reason"] = "support_semantic_field_changed_or_unknown"
            return result
    result.update(unchanged=True, reason="operation_stats_and_full_hq_shield_preserved")
    return result


def inspect_pair(before, previous, current, observer=None):
    """Confirm a persistent real gain, or separately prove a stable refusal.

    The caller may accept no_effect only after its bounded late observation.
    Neither touch completion nor an unknown consumed order establishes gain.
    """
    result = {"confirmed": False, "no_effect": False, "reason": "deployment_unconfirmed",
              "selected_identity_verified": False,
              "meaning": "observed_support_gain_not_card_name_or_effect_identity"}
    if not all(valid_frame(f) for f in (before, previous, current)):
        result["reason"] = "invalid_frame"
        return result
    read = observer or observe
    rows = [read(f) for f in (before, previous, current)]
    result["observations"] = rows
    if any(r.get("transition") or r.get("choice_modal") for r in rows):
        result["reason"] = "transition_or_choice_modal"
        return result
    if any(type(r.get("count")) is not int or r.get("reason") != "complete_support_row"
           or not r.get("cards") or not r.get("hq") for r in rows):
        result["reason"] = "support_row_incomplete"
        return result
    signatures = [_signature(r) for r in rows]
    old, earlier, latest = signatures
    result.update(before_support=len(old), previous_support=len(earlier), after_support=len(latest),
                  unit_signatures=signatures)
    support_motion = motion(previous, current, SUPPORT_ROI)
    hand_motion = motion(previous, current, HAND_ROI)
    changes = [motion(before, frame, HAND_ROI) for frame in (previous, current)]
    support_changes = [motion(before, frame, SUPPORT_ROI) for frame in (previous, current)]
    result.update(support_motion=support_motion, hand_motion=hand_motion,
                  hand_changes=changes, support_changes=support_changes)
    geometry_stable = (len(rows[1]["cards"]) == len(rows[2]["cards"]) and all(
        abs(a["cx"] - b["cx"]) <= 3 and abs(a["y"] - b["y"]) <= 3
        for a, b in zip(rows[1]["cards"], rows[2]["cards"])))
    if (signatures[1] != signatures[2] or not geometry_stable or
            support_motion > SUPPORT_MOTION_MAX or hand_motion > HAND_MOTION_MAX):
        result["reason"] = "post_input_pixels_or_geometry_still_moving"
        return result
    types_before = Counter(t for _, t in old)
    types_after = Counter(t for _, t in latest)
    if (len(earlier) == len(old) + 1 and all(types_after[t] >= n for t, n in types_before.items())
            and all(change > HAND_CHANGE_MIN for change in changes)
            and all(change > SUPPORT_MOTION_MAX for change in support_changes)):
        result.update(confirmed=True, reason="persistent_support_unit_gain_and_hand_change")
        return result
    source_geometry_stable = all(len(rows[0]["cards"]) == len(r["cards"]) and all(
        a.get("row_kind") == b.get("row_kind") and abs(a["cx"] - b["cx"]) <= 3
        and abs(a["y"] - b["y"]) <= 3 for a, b in zip(rows[0]["cards"], r["cards"]))
        for r in rows[1:])
    if (old == earlier == latest and source_geometry_stable and
            all(c <= REFUSAL_HAND_CHANGE_MAX for c in changes)):
        if any(type(card.get("n_stats")) is not int or card["n_stats"] < 2
               for row in rows for card in row["cards"] if card.get("row_kind") == "unit"):
            result["reason"] = "support_numeric_fields_unavailable_for_refusal"
            return result
        semantics = unchanged_support_fields(before, previous, current, rows[0])
        result["refusal_semantics"] = semantics
        if semantics["unchanged"]:
            result.update(no_effect=True, reason="stable_no_deployment_effect")
        else:
            result["reason"] = semantics["reason"]
    elif any(c > HAND_CHANGE_MIN for c in changes):
        result["reason"] = "hand_changed_without_persistent_unit_gain"
    else:
        result["reason"] = "persistent_unit_gain_and_hand_change_missing"
    return result
