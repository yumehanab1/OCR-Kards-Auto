"""Read-only confirmation of a completed deployment across a turn boundary.

The missing own-turn button is never evidence. Two positive opponent labels,
complete HQ-anchored support rows and one persistent outer unit are required.
Only friendly support pixels are compared: enemy animation cannot erase an
otherwise stable deployment, and enemy changes cannot establish a unit gain.
"""
from __future__ import annotations

import cv2
import numpy as np

SUPPORT_ROI = (200, 425, 1060, 590)
SUPPORT_MOTION_MAX = .008


def observe(frame):
    import mobile_board as board
    import apk_deploy_target
    import apk_enemy_turn
    transition = board.board_transition_reason(frame)
    choice = board.choice_modal(frame)[0]
    cards, reason, row = apk_deploy_target._row(frame)
    return {"transition": transition, "choice_modal": choice,
            "opponent": apk_enemy_turn.inspect_opponent_turn(frame),
            "row_reason": reason, "cards": cards, "hq": row.get("hq")}


def _valid(frame):
    return (isinstance(frame, np.ndarray) and frame.shape == (720, 1280, 3)
            and frame.dtype == np.uint8)


def _unit_signature(observation):
    hq = observation["hq"]
    return sorted((round((card["cx"] - hq["cx"]) / 144), card["type"])
                  for card in observation["cards"] if card.get("row_kind") == "unit")


def inspect_pair(before, previous, current, badge, target, observer=None):
    """No hand/resource difference is accepted as post-input unit evidence."""
    result = {"confirmed": False, "reason": "unconfirmed_turn_boundary_deployment",
              "selected_identity_verified": False,
              "meaning": "persistent_new_unit_not_card_name_or_effect_identity"}
    if not all(_valid(frame) for frame in (before, previous, current)):
        result["reason"] = "invalid_frame"
        return result
    if (not isinstance(badge, dict) or badge.get("kind") != "unit" or
            badge.get("state") != "orange" or
            badge.get("apk_availability", {}).get("allowed") is not True or
            badge.get("apk_availability", {}).get("basis") != "orange_unit_geometry_v1"):
        result["reason"] = "source_unit_approval_missing"
        return result
    if not isinstance(target, (tuple, list)) or len(target) != 2 or target[1] != 505:
        result["reason"] = "support_landing_missing"
        return result
    read = observer or observe
    observations = [read(frame) for frame in (before, previous, current)]
    result["observations"] = observations
    if any(item.get("transition") or item.get("choice_modal") for item in observations):
        result["reason"] = "transition_or_choice_modal"
        return result
    if any(item.get("row_reason") != "complete_support_row" or
           not item.get("cards") or not item.get("hq") for item in observations):
        result["reason"] = "support_row_incomplete"
        return result
    if any(item.get("opponent", {}).get("present") is not True for item in observations[1:]):
        result["reason"] = "positive_opponent_label_pair_missing"
        return result
    signatures = [_unit_signature(item) for item in observations]
    result["unit_signatures"] = signatures
    old, earlier, latest = signatures
    result.update(before_support=len(old), previous_support=len(earlier), after_support=len(latest))
    if len(earlier) != len(old) + 1 or latest != earlier:
        result["reason"] = "persistent_exactly_one_unit_gain_missing"
        return result
    if any(entry not in earlier for entry in old):
        result["reason"] = "existing_support_units_not_preserved"
        return result
    new = [entry for entry in earlier if entry not in old]
    if len(new) != 1:
        result["reason"] = "new_unit_not_unique"
        return result
    # A reviewed empty outer landing cannot establish an internal inserted unit.
    old_slots = [entry[0] for entry in old] + [0]
    slot = new[0][0]
    left = target[0] < observations[0]["hq"]["cx"]
    if not (slot == min(old_slots)-1 if left else slot == max(old_slots)+1):
        result["reason"] = "new_unit_not_on_dispatched_outer_side"
        return result
    cards_a, cards_b = observations[1]["cards"], observations[2]["cards"]
    if (len(cards_a) != len(cards_b) or any(
            abs(a["cx"] - b["cx"]) > 3 or abs(a["y"] - b["y"]) > 3
            for a, b in zip(cards_a, cards_b))):
        result["reason"] = "support_geometry_still_moving"
        return result
    x0, y0, x1, y1 = SUPPORT_ROI
    a = cv2.GaussianBlur(previous[y0:y1, x0:x1], (3, 3), 0)
    b = cv2.GaussianBlur(current[y0:y1, x0:x1], (3, 3), 0)
    motion = float((cv2.absdiff(a, b).max(axis=2) > 18).mean())
    result["support_motion"] = motion
    if motion > SUPPORT_MOTION_MAX:
        result["reason"] = "support_pixels_still_moving"
        return result
    result.update(confirmed=True, reason="persistent_outer_unit_on_opponent_turn_pair", new_unit=new[0])
    return result
