"""APK-only resource HUD adaptation; all card/board pixels stay unchanged.

The game may reflow its HUD after returning from an Activity. The compact
layout has 34px current-credit digits, but unchanged 1280x720 board geometry.
Both resource plate borders must support one explicit layout. This module
never authorizes an input and never derives credit values from turn history.
"""
from __future__ import annotations

import cv2
import numpy as np

_ORIGINAL_READ = None
_COMPACT_READ_BOX = (16, 563, 81, 624)
_LAYOUTS = {
    "standard": ((30, 133, 110, 209), (30, 505, 110, 581)),
    "standard_inset": ((44, 133, 124, 209), (44, 505, 124, 581)),
    "compact": ((21, 94, 79, 149), (21, 567, 79, 622)),
}


def _valid(frame):
    return (isinstance(frame, np.ndarray) and frame.shape == (720, 1280, 3)
            and frame.dtype == np.uint8)


def _plate_edges(bright, box):
    x0, y0, x1, y1 = box
    return [
        max(float(bright[y, x0+3:x1-3].mean()) for y in range(y0-2, y0+3)),
        max(float(bright[y, x0+3:x1-3].mean()) for y in range(y1-3, y1+2)),
        max(float(bright[y0+3:y1-3, x].mean()) for x in range(x0-2, x0+3)),
        max(float(bright[y0+3:y1-3, x].mean()) for x in range(x1-3, x1+2)),
    ]


def inspect_hud(frame):
    """Identify an explicit layout from all four borders of BOTH resource plates."""
    result = {"layout": "unknown", "reason": "invalid_frame", "evidence": {}}
    if not _valid(frame):
        return result
    hsv = cv2.cvtColor(frame[:, :128], cv2.COLOR_BGR2HSV)
    bright = (hsv[:, :, 1] <= 100) & (hsv[:, :, 2] >= 90)
    for name, boxes in _LAYOUTS.items():
        result["evidence"][name] = [_plate_edges(bright, box) for box in boxes]
    confirmed = [name for name, values in result["evidence"].items()
                 if min(v for plate in values for v in plate) >= 0.70]
    if len(confirmed) == 1:
        result.update(layout=confirmed[0], reason="both_resource_plate_borders")
    else:
        result["reason"] = "missing_or_conflicting_resource_plate_borders"
    return result


def _compact_geometry(mask, segments, bbox):
    if not segments or len(segments) > 2 or bbox is None:
        return "invalid_compact_numeral_segments"
    x, y, _w, _h = bbox
    bx1, by1, bx2, by2 = _COMPACT_READ_BOX
    # 34px single-digit height is measured in session-04; double digits are
    # the standard HUD's 33px scaled by the same 0.72 layout transform.
    # Double-digit compact coverage is synthetic until a real sample is seen.
    low, high = (31, 37) if len(segments) == 1 else (22, 26)
    spans = []
    for left, right in segments:
        ys = np.where(mask[:, left:right] > 0)[0]
        if not len(ys):
            return "empty_compact_digit"
        spans.append((int(ys.min()), int(ys.max()) + 1))
    top, bottom = min(v[0] for v in spans), max(v[1] for v in spans)
    if (x + segments[0][0] <= bx1 or y + top <= by1
            or x + segments[-1][1] >= bx2 or y + bottom >= by2):
        return "clipped_compact_digit"
    if not low <= bottom-top <= high or any(not low <= b-t <= high for t, b in spans):
        return "incomplete_or_mixed_scale_compact_digits"
    if len(spans) == 2:
        if any(abs(spans[0][i] - spans[1][i]) > 2 for i in (0, 1)):
            return "misaligned_compact_digits"
        gap = segments[1][0] - segments[0][1]
        if not 1 <= gap <= (bottom-top) * 0.4:
            return "nonadjacent_compact_digits"
    return None


def inspect_kredits(frame):
    """Read current own credits, with explicit unknown and numeric evidence."""
    import kredits
    import kredits_templates as kt
    result = {"value": None, "reason": "unknown_layout", "hud": inspect_hud(frame),
              "box": None, "digits": []}
    layout = result["hud"]["layout"]
    if layout in ("standard", "standard_inset"):
        original = _ORIGINAL_READ or kredits.read_kredits
        result["value"] = original(frame, box=kredits.MOBILE_CURRENT_BOX, profile="mobile")
        result.update(reason=kredits.LAST_REJECT or "confirmed_standard_mobile_digits",
                      box=list(kredits.MOBILE_CURRENT_READ_BOX))
        return result
    if layout != "compact":
        return result
    result["box"] = list(_COMPACT_READ_BOX)
    _numeral, mask, bbox = kredits.isolate_numeral(frame, _COMPACT_READ_BOX)
    if mask is None:
        result["reason"] = "missing_compact_current_numeral"
        return result
    segments = kt.split_glyphs(mask)
    rejection = _compact_geometry(mask, segments, bbox)
    if rejection:
        result["reason"] = rejection
        return result
    bank = kt.build_templates()
    if set(bank) != set(range(10)):
        result["reason"] = "incomplete_digit_bank"
        return result
    for left, right in segments:
        glyph = kt.normalize_glyph(mask[:, left:right])
        if glyph is None:
            result["reason"] = "invalid_compact_digit"
            return result
        scores = sorted([(digit, max(kt.score_against(glyph, template) for template in samples))
                         for digit, samples in bank.items()], key=lambda pair: -pair[1])
        digit, score = scores[0]
        margin = score - scores[1][1]
        result["digits"].append({"value": int(digit), "score": float(score), "margin": float(margin)})
        if not np.isfinite(score) or score < 0.80 or margin < 0.08:
            result["reason"] = "ambiguous_compact_digit"
            return result
    digits = [d["value"] for d in result["digits"]]
    value = int("".join(str(d) for d in digits))
    if value > 24 or (len(digits) == 2 and digits[0] == 0):
        result["reason"] = "compact_value_outside_current_credit_range"
        return result
    result.update(value=value, reason="confirmed_compact_current_digits")
    return result


def read_kredits(frame, box=None, record_samples=False, _sample_counter=None,
                 merge_mode=None, height_guard=None, profile="pc"):
    """Compatibility wrapper. Only explicit mobile current-credit reads change."""
    import kredits
    original = _ORIGINAL_READ
    if original is None:
        original = kredits.read_kredits
    is_current = box is None or tuple(box) in (kredits.MOBILE_CURRENT_BOX, kredits.MOBILE_CURRENT_READ_BOX)
    if profile != "mobile" or not is_current:
        kwargs = dict(box=box, record_samples=record_samples, merge_mode=merge_mode,
                      height_guard=height_guard, profile=profile)
        if _sample_counter is not None:
            kwargs["_sample_counter"] = _sample_counter
        return original(frame, **kwargs)
    observed = inspect_kredits(frame)
    kredits.LAST_REJECT = None if observed["value"] is not None else observed["reason"]
    return observed["value"]


def install():
    """Install once in the APK Python interpreter, never modify production files."""
    global _ORIGINAL_READ
    import kredits
    if _ORIGINAL_READ is None:
        _ORIGINAL_READ = kredits.read_kredits
        kredits.read_kredits = read_kredits
    return {"installed": True, "adapter": "apk_hud_adapter", "board_transform": "none"}
