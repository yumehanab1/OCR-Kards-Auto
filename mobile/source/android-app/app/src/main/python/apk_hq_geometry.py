"""APK HQ location from unique current-frame structure, with optional HP.

The support row and large centered shield checks are retained. A dim bright-card
component may use the same bright-fill floor outside a separately verified
tapered HQ shield; the mandatory dark shield cannot count against card fill.
An our-HQ component widened by tabletop pixels may shrink horizontally only
when two unique, continuous current-frame card borders independently locate it.
Numerals never select between structures. A location is not a turn, stable
board, action or victory signal; callers must retain those separate guards.
"""
from __future__ import annotations

from copy import deepcopy
from numbers import Integral

import numpy as np
import cv2

_ORIGINAL_ATTRIBUTE = "_apk_hq_geometry_original_hq_card"
_WRAPPER_ATTRIBUTE = "_apk_hq_geometry_wrapper"
_CARD_KEYS = ("x", "y", "w", "h", "cx", "cy")
_HP_KEYS = ("hp", "hp_state", "hp_score", "hp_corroboration")


def _runs(points):
    runs = []
    for point in points:
        if not runs or point > runs[-1][-1] + 1:
            runs.append([])
        runs[-1].append(point)
    return runs


def _card_body(frame, side, card, box, field, board, hp):
    """Shrink only a widened our-HQ component using its two visible borders.

    A support-row CLOSE can connect a thin tabletop spur to a genuine card.
    The original shield must already pass every check except width ratio. Its
    width never supplies a replacement card width: actual opposing vertical
    borders must determine both sides, independently in this same image.
    Keep the row's original top/bottom, including a FIELD-clipped bottom.
    """
    x, y, w, h = (card[key] for key in ("x", "y", "w", "h"))
    bx, by, bw, bh = box
    if (side != "our" or not .36 <= bw / w < .42
            or not .30 <= bh / h <= .50
            or not .40 <= (bx + bw / 2 - x) / w <= .60
            or not .65 <= (by + bh / 2 - y) / h <= .90):
        return None
    top = y + int(.10 * h)
    bottom = min(by - 5, y + int(.63 * h))
    if bottom - top < 50 or x < field[0] + 3 or x + w + 3 > field[2]:
        return None
    gray = cv2.cvtColor(frame[top:bottom, x-3:x+w+3], cv2.COLOR_BGR2GRAY).astype(np.int16)
    difference = gray[:, 4:] - gray[:, :-4]
    positive = (np.mean(difference > 18, axis=0) >= .90) & (np.median(difference, axis=0) >= 30)
    negative = (np.mean(difference < -18, axis=0) >= .90) & (np.median(difference, axis=0) <= -30)
    left_runs = _runs(np.flatnonzero(positive).tolist())
    right_runs = _runs(np.flatnonzero(negative).tolist())
    if len(left_runs) != 1 or len(right_runs) != 1:
        return None
    # Thick/double borders, interior artwork or more than one possible body
    # cannot be resolved by selecting whichever would fit the shield ratio.
    left, right = left_runs[0], right_runs[0]
    if len(left) > 4 or len(right) > 4:
        return None
    medians = np.median(difference, axis=0)
    l = x - 1 + left[int(np.argmax(medians[left]))]
    r = x - 1 + right[int(np.argmin(medians[right]))]
    nw = r - l
    if (not 0 <= l - x <= .25 * w or not 0 <= x + w - r <= .25 * w
            or not .75 <= nw / w < .98
            or not board.CARD_W_RANGE[0] <= nw <= board.CARD_W_RANGE[1]):
        return None
    # The independently bounded card must retain the original bright-card
    # fill floor. Background texture or dark artwork alone is not a body.
    bright = (cv2.cvtColor(frame[y:y+h, l:r], cv2.COLOR_BGR2HSV)[:, :, 2] > board.CARD_BRIGHT_V).astype(np.uint8)
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    if np.count_nonzero(bright) / (nw * h) < .50:
        return None
    refined = dict(card, x=int(l), w=int(nw), cx=int(l + nw // 2))
    shield, new_box = hp.find_shield(frame, refined)
    if (shield is None or tuple(new_box) != tuple(box)
            or not board._hq_shield_geometry(refined, new_box)):
        return None
    return refined


def _tapered_shield(shield, hp):
    """Require a flat-sided upper shield with a centered tapered lower tip."""
    dark = (cv2.cvtColor(shield, cv2.COLOR_BGR2HSV)[:, :, 2] < hp.SHIELD_DARK_V).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
    expected = (2, 2, shield.shape[1] - 4, shield.shape[0] - 4)
    exact = [i for i in range(1, count) if tuple(int(v) for v in stats[i, :4]) == expected]
    if len(exact) != 1:
        return False
    x, y, w, h = expected
    component = labels[y:y+h, x:x+w] == exact[0]
    for fraction in (.15, .35, .55):
        points = np.flatnonzero(component[int(h * fraction)])
        if not len(points) or points[0] > 2 or points[-1] < w - 3:
            return False
    tip = np.flatnonzero(component[int(h * .95)])
    return (len(tip) >= 4 and .15 * w <= tip[0] and tip[-1] <= .85 * w
            and .10 * w <= tip[-1] - tip[0] + 1 <= .50 * w
            and abs((tip[0] + tip[-1]) / 2 - (w - 1) / 2) <= .10 * w)


def _shield_excluded_cards(frame, side, field, board, hp):
    """Recover only dim row components whose non-shield area remains bright."""
    top, bottom = board.HQ_SCAN_BANDS[side]
    low, high = board.HQ_CENTER_BANDS[side]
    x0, y0, x1, y1 = field
    mask = (cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2] > board.CARD_BRIGHT_V).astype(np.uint8)
    keep = np.zeros_like(mask)
    keep[max(y0, top):min(y1, bottom), x0:x1] = 1
    mask &= keep
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    recovered = []
    for i in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[i])
        if (not board.CARD_W_RANGE[0] <= w <= board.CARD_W_RANGE[1]
                or not board.CARD_H_RANGE[0] <= h <= board.CARD_H_RANGE[1]
                or not low <= y + h // 2 <= high or not .45 <= area / (w * h) < .50):
            continue
        card = dict(x=x, y=y, w=w, h=h, cx=x+w//2, cy=y+h//2)
        shield, box = hp.find_shield(frame, card)
        if shield is None or not board._hq_shield_geometry(card, box) or not _tapered_shield(shield, hp):
            continue
        bx, by, bw, bh = box
        # Exclude only the observed shield, retaining the old 50% brightness
        # floor on every other pixel of the independently detected card body.
        if not (x <= bx < bx + bw <= x + w and y <= by < by + bh <= y + h):
            continue
        component = labels[y:y+h, x:x+w] == i
        component[by-y:by-y+bh, bx-x:bx-x+bw] = False
        outside = w * h - bw * bh
        if outside > 0 and np.count_nonzero(component) / outside >= .50:
            recovered.append(card)
    return recovered


def _integers(values, length):
    if not isinstance(values, (tuple, list)) or len(values) != length:
        return None
    if any(isinstance(value, bool) or not isinstance(value, Integral) for value in values):
        return None
    return tuple(int(value) for value in values)


def _card_key(card):
    if not isinstance(card, dict):
        return None
    key = _integers([card.get(name) for name in _CARD_KEYS], len(_CARD_KEYS))
    if key is None:
        return None
    x, y, w, h, cx, cy = key
    if (x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1280 or y + h > 720
            or cx != x + w // 2 or cy != y + h // 2):
        return None
    return key


def _original_reader(board):
    original = getattr(board, _ORIGINAL_ATTRIBUTE, None)
    if original is None:
        original = board.hq_card
    if not callable(original) or getattr(original, _WRAPPER_ATTRIBUTE, False) is True:
        return None
    return original


def hq_card(frame, side="enemy", field=None, *, include_hp=True):
    """Return one geometry-verified HQ, or None; unreadable HP stays None.

    include_hp=False skips the old numeral-dependent reader entirely. When it
    is enabled, only that reader's exact same card and shield may add HP data.
    All state is local to this frame; no old location or HP is carried forward.
    """
    import mobile_board as board
    import hq_hp

    if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8
            or frame.shape != (720, 1280, 3) or side not in ("enemy", "our")):
        return None
    field = board.FIELD if field is None else field
    field = _integers(field, 4)
    if field is None:
        return None
    x0, y0, x1, y1 = field
    if not (0 <= x0 < x1 <= 1280 and 0 <= y0 < y1 <= 720):
        return None
    structures = []
    try:
        cards = board._support_row_bright_cards(frame, side, field)
        cards = list(cards) + _shield_excluded_cards(frame, side, field, board, hq_hp)
        for card in cards:
            if _card_key(card) is None:
                return None
            shield, box = hq_hp.find_shield(frame, card)
            if shield is None:
                continue
            box = _integers(box, 4)
            if box is None:
                return None
            x, y, w, h = box
            if (x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1280 or y + h > 720
                    or not isinstance(shield, np.ndarray) or shield.dtype != np.uint8
                    or shield.shape != (h, w, 3)):
                return None
            if not board._hq_shield_geometry(card, box):
                refined = _card_body(frame, side, card, box, field, board, hq_hp)
                if refined is None:
                    continue
                card = refined
            structures.append((card, box))
    except Exception:
        # A failed structural read must not silently remove a rival candidate.
        return None
    if len(structures) != 1:
        return None
    card, box = structures[0]
    result = deepcopy(card)
    for key in _HP_KEYS:
        result.pop(key, None)
    result.update(shield=box, geometry_verified=True, hp=None)
    if not include_hp:
        return result
    original = _original_reader(board)
    if original is None:
        return result
    try:
        got = original(frame, side, field)
        if (not isinstance(got, dict) or _card_key(got) != _card_key(card)
                or _integers(got.get("shield"), 4) != box):
            return result
        hp = got.get("hp")
        if isinstance(hp, bool) or not isinstance(hp, Integral) or not 0 <= hp <= 99:
            return result
        for key in _HP_KEYS:
            if key in got:
                result[key] = deepcopy(got[key])
        result["hp"] = int(hp)
    except Exception:
        # Failed OCR cannot undo the already unique structural observation.
        pass
    return result


setattr(hq_card, _WRAPPER_ATTRIBUTE, True)


def geometry_only_hq_card(frame, side="enemy", field=None):
    """Core-compatible runtime entry: no HP reader runs on the action path."""
    return hq_card(frame, side, field, include_hp=False)


setattr(geometry_only_hq_card, _WRAPPER_ATTRIBUTE, True)


def install():
    """Install for every APK session without capturing our own old wrapper.

    Store the original on mobile_board itself: Chaquopy may reuse its module
    across sessions, even if this adapter module is reloaded independently.
    """
    import mobile_board as board

    original = _original_reader(board)
    if original is None:
        raise RuntimeError("HQ geometry original reader is unavailable")
    if not hasattr(board, _ORIGINAL_ATTRIBUTE):
        setattr(board, _ORIGINAL_ATTRIBUTE, original)
    board.hq_card = geometry_only_hq_card
    return {"installed": True, "adapter": "apk_hq_geometry",
            "hq_location": "unique_support_card_and_large_shield",
            "hp": "disabled_on_runtime_path_explicit_diagnostic_only"}
