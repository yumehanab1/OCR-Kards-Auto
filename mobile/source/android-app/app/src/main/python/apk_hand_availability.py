"""APK-only veto for core-recognized units, never a standalone card selector.

Require an independent, bounded cost plate and orange primary numeral ink.
The game's colour supplies availability; numeral OCR is optional diagnostics.
The user-authorized grab rule is the current orange numeral centre +25px on
each screen axis. Availability does not establish card identity or bypass
modal/frame, foreground, cancellation, dispatch or post-input checks.
"""
from __future__ import annotations

import base64
from functools import lru_cache
import math

import cv2
import numpy as np


def _feature(crop):
    value = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 2].astype(np.float32)
    value = cv2.resize(value, (28, 28), interpolation=cv2.INTER_AREA)[3:-3, 3:-3]
    low, high = np.percentile(value, (25, 95))
    return np.clip((value - low) / max(high - low, 1), 0, 1).astype(np.float32)


@lru_cache(maxsize=1)
def _templates():
    from apk_hand_cost_templates import SAMPLES
    result = []
    for sample in SAMPLES:
        crop = cv2.imdecode(np.frombuffer(base64.b64decode(sample["png"]), np.uint8), cv2.IMREAD_COLOR)
        if crop is None:
            raise ValueError("embedded_hand_cost_template_unavailable")
        result.append((sample["cost"], _feature(crop)))
    return result


def _rot(crop, angle):
    h, w = crop.shape[:2]
    return cv2.warpAffine(crop, cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1), (w, h),
                          flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _read_cost(crop):
    scores, digits, angles = {}, {}, {}
    for angle in range(-20, 21, 4):
        feature = _feature(_rot(crop, angle) if angle else crop)
        for cost, template in _templates():
            whole = float(cv2.matchTemplate(feature, template, cv2.TM_CCOEFF_NORMED)[0, 0])
            numeral = float(cv2.matchTemplate(feature[:, :15], template[:, :15], cv2.TM_CCOEFF_NORMED)[0, 0])
            if whole > scores.get(cost, -1):
                scores[cost], angles[cost] = whole, angle
            digits[cost] = max(digits.get(cost, -1), numeral)
    ranked = sorted(scores, key=lambda cost: -scores[cost])
    numerals = sorted(digits, key=lambda cost: -digits[cost])
    cost, numeral = ranked[0], numerals[0]
    evidence = {"candidate": cost, "score": scores[cost], "margin": scores[cost]-scores[ranked[1]],
                "numeral_candidate": numeral, "numeral_score": digits[numeral],
                "numeral_margin": digits[numeral]-digits[numerals[1]], "angle": angles[cost]}
    known = (cost == numeral and min(evidence["score"], evidence["numeral_score"]) >= .80
             and min(evidence["margin"], evidence["numeral_margin"]) >= .055)
    return cost if known else None, evidence


def _geometry_plates(frame):
    value = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2]
    candidates = []
    for threshold in (75, 85, 95):
        _, labels, stats, _ = cv2.connectedComponentsWithStats((value < threshold).astype(np.uint8), 8)
        for index, (sx, sy, sw, sh, area) in enumerate(stats[1:], 1):
            x, y, w, h = map(int, (sx, sy, sw, sh))
            if (not 200 <= x or not 560 <= y or x+w >= 1100 or y+h >= 720 or
                    not 20 <= w <= 34 or not 20 <= h <= 34 or not .8 <= w/h <= 1.25 or
                    not .35 <= int(area)/(w*h) <= .88):
                continue
            yy, xx = np.where(labels[y:y+h, x:x+w] == index)
            rect = cv2.minAreaRect(np.column_stack((xx, yy)).astype(np.float32))
            # Complete rectangular outlines locate the fee row independently
            # of ink colour or OCR. An incomplete outline is still an obstacle:
            # erosion/occlusion must not silently erase a real neighbour.
            component = (labels[y:y+h, x:x+w] == index).astype(np.uint8)
            contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            rectangle_area = float(rect[1][0] * rect[1][1])
            silhouette = max((cv2.contourArea(c) for c in contours), default=0.)
            rectangularity = silhouette / rectangle_area if rectangle_area else 0.
            angle = (float(rect[2]) + 45) % 90 - 45
            candidates.append({"box": [x, y, w, h], "cx": x+w/2, "cy": y+h/2,
                               "angle": angle, "rectangularity": rectangularity})
    return _fan_obstacles(candidates)


def _fan_obstacles(candidates):
    """Discard irregular artwork only outside a locally confirmed fee row."""
    anchors = []
    for plate in sorted(candidates, key=lambda p: p["box"][2]*p["box"][3], reverse=True):
        if plate["rectangularity"] < .88:
            continue
        if not any(abs(plate["cx"]-p["cx"]) < 12 and abs(plate["cy"]-p["cy"]) < 12 for p in anchors):
            anchors.append(plate)
    anchors.sort(key=lambda p: p["cx"])
    kept = []
    for plate in candidates:
        discard = False
        if plate["rectangularity"] < .88:
            for left, right in zip(anchors, anchors[1:]):
                distance = right["cx"]-left["cx"]
                if not (left["cx"] <= plate["cx"] <= right["cx"] and 48 <= distance <= 185):
                    continue
                slope = (right["cy"]-left["cy"])/distance
                tangent = math.degrees(math.atan(slope))
                if any(abs(p["angle"]) > 22 or abs(tangent-p["angle"]) > 15 for p in (left, right)):
                    continue
                x, y, w, h = plate["box"]
                row_y = [left["cy"]+(edge-left["cx"])*slope for edge in (x, x+w)]
                # The entire component must be beyond the row, with a 24px
                # margin (larger than a calibrated plate's half-height).
                # No extrapolation beyond two anchors; ambiguous row/title
                # fragments and chipped real neighbours remain blocking.
                discard = y > max(row_y)+24 or y+h < min(row_y)-24
                break
        if not discard:
            kept.append(plate)
    return kept


def _plates(frame, badge, *, geometry=None):
    boxes = set()
    for item in _geometry_plates(frame) if geometry is None else geometry:
        x, y, w, h = item["box"]
        if abs(x+w/2-badge["cx"]) > 6 or abs(y+h/2-badge["cy"]) > 6:
            continue
        anchor = badge.get("anchor")
        if anchor and not (x <= anchor[0] and y <= anchor[1]
                           and anchor[0]+anchor[2] <= x+w and anchor[1]+anchor[3] <= y+h):
            continue
        boxes.add((x, y, w, h))
    return sorted(boxes)


def _safe_grab(frame, badge, availability, *, geometry=None):
    """Fixed screen-axis offset, not a claim of verified touch ownership.

    ``cx/cy`` is the core's window centre around the current orange numeral
    anchor. It differs slightly from the surrounding dark fee plate centre.
    Do not rotate, clamp or choose among alternative points: the user's
    explicit +25/+25 rule supersedes the old all-neighbour fan veto.
    """
    result = {"point": None, "reason": "source_unit_approval_missing", "evidence": {
        "point_policy": "orange_digit_center_plus_25px_v1",
        "selected_identity_verified": False, "offset": [25, 25]}}
    if (not isinstance(frame, np.ndarray) or frame.shape != (720, 1280, 3) or frame.dtype != np.uint8):
        result["reason"] = "invalid_frame"
        return result
    if (availability.get("allowed") is not True or availability.get("basis") != "orange_unit_geometry_v1"
            or badge.get("kind") != "unit" or badge.get("state") != "orange"):
        return result
    center = [badge.get("cx"), badge.get("cy")]
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in center):
        result["reason"] = "orange_digit_center_invalid"
        return result
    point = [round(center[0] + 25), round(center[1] + 25)]
    result["evidence"].update(digit_center=center, plate=availability.get("plate"))
    if not (205 <= point[0] <= 1094 and 570 <= point[1] <= 713):
        result["reason"] = "fixed_grab_outside_hand_bounds"
        return result
    result.update(point=point, reason="user_fixed_orange_digit_offset")
    return result


def safe_grab(frame, badge):
    """User-authorized point proposal; actual card selection needs live validation."""
    availability = inspect_unit(frame, badge)
    if not availability["allowed"]:
        return {"point": None, "reason": availability["reason"], "evidence": {"availability": availability}}
    return _safe_grab(frame, badge, availability)


def inspect_unit(frame, badge, *, credits=None, numeric_diagnostics=False, _geometry=None):
    """Veto candidate; caller must still prove fresh/stable frame and touch origin."""
    result = {"allowed": False, "basis": None, "cost": None, "credits": None, "plate": None,
              "reason": "invalid_frame", "evidence": {}}
    if not isinstance(frame, np.ndarray) or frame.shape != (720, 1280, 3) or frame.dtype != np.uint8:
        return result
    if badge.get("kind") != "unit" or badge.get("state") != "orange":
        result["reason"] = "core_unit_and_orange_required"
        return result
    if credits is None and numeric_diagnostics:
        from apk_hud_adapter import inspect_kredits
        observed = inspect_kredits(frame)
        result["evidence"]["resources"] = observed
        credits = observed["value"]
    if type(credits) is int and 0 <= credits <= 24:
        result["credits"] = credits
    geometry = _geometry_plates(frame) if _geometry is None else _geometry
    boxes = _plates(frame, badge, geometry=geometry)
    if not boxes:
        result["reason"] = "independent_cost_plate_missing"
        return result
    # Choose the same outer geometry used by the grab calculation, without
    # choosing a plate or rotation according to a guessed numeric identity.
    plate = max((p for p in geometry if tuple(p["box"]) in boxes),
                key=lambda p: p["box"][2]*p["box"][3])
    box, angle = plate["box"], plate["angle"]
    result["plate"] = list(box)
    result["evidence"]["plate_angle"] = angle
    if not math.isfinite(angle) or abs(angle) > 22:
        result["reason"] = "plate_rotation_outside_calibration"
        return result
    x, y, w, h = box
    crop = _rot(frame[y:y+h, x:x+w], angle)
    hsv = cv2.cvtColor(cv2.resize(crop, (28, 28), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2HSV)[3:-3, 3:18]
    low, high = np.percentile(hsv[:, :, 2], (25, 95))
    ink = hsv[:, :, 2] >= low + .65 * (high-low)
    orange = (hsv[:, :, 0] >= 8) & (hsv[:, :, 0] <= 32) & (hsv[:, :, 1] >= 140) & (hsv[:, :, 2] >= 80)
    fraction = float(orange[ink].mean()) if int(ink.sum()) >= 20 else 0.
    result["evidence"]["primary_ink"] = {"count": int(ink.sum()), "orange_fraction": fraction}
    if fraction < .85:
        result["reason"] = "primary_cost_ink_not_orange"
        return result
    if numeric_diagnostics:
        observations = []
        for bx, by, bw, bh in boxes:
            cost, evidence = _read_cost(frame[by:by+bh, bx:bx+bw])
            observations.append({"plate": [bx, by, bw, bh], "value": cost, **evidence})
        known = {item["value"] for item in observations if item["value"] is not None}
        cost = next(iter(known)) if len(known) == 1 else None
        result["cost"] = cost
        result["evidence"]["cost"] = {"observations": observations,
                                      "conflicting": len(known) > 1}
        result["evidence"]["numeric_affordability"] = (
            cost <= result["credits"] if cost is not None and result["credits"] is not None else None)
    result.update(allowed=True, basis="orange_unit_geometry_v1", reason="confirmed_orange_unit")
    return result


def filter_units(frame, candidates, *, numeric_diagnostics=False):
    """Keep approved identities and prefer grab points farther from the bottom."""
    credits = None
    if numeric_diagnostics:
        from apk_hud_adapter import inspect_kredits
        credits = inspect_kredits(frame)["value"]
    # Reuse only within this synchronous frame; no cross-frame cache or stale
    # ownership evidence. The same plate observations serve all candidates.
    geometry = _geometry_plates(frame)
    results, accepted = [], []
    for badge in candidates:
        result = inspect_unit(frame, badge, credits=credits, numeric_diagnostics=numeric_diagnostics,
                              _geometry=geometry)
        results.append({"candidate": [badge.get("cx"), badge.get("cy")], **result})
        if result["allowed"]:
            grab = _safe_grab(frame, badge, result, geometry=geometry)
            results[-1]["grab"] = grab
            if grab["point"] is None:
                results[-1].update(allowed=False, reason=grab["reason"])
                continue
            accepted.append(dict(badge, apk_availability=result, apk_grab_point=grab["point"], apk_grab=grab))
    # A crowded fan's leftmost card can expose only a narrow strip at the screen
    # edge. Prefer an already-approved, more visible point before spending the
    # deployment attempt on that edge. This changes neither touch geometry nor
    # eligibility; equal-height candidates retain the core's original order.
    accepted.sort(key=lambda badge: badge["apk_grab_point"][1])
    return {"units": accepted, "checks": results, "credits": credits}
