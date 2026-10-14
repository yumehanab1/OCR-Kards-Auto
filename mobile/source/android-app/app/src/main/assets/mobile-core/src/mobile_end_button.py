"""Read the end-turn button's observed color after confirming its shape in the ROI.

Normalized template correlation confirms the label's shape, not its actual color.
Only pixels at the matched template's bright strokes classify white/orange. Mixed,
dark, unsupported colors or weak/occluded matches stay unknown. No credits or
unit-action history are consulted, and this module never performs device input.
"""
from __future__ import annotations

import cv2
import numpy as np

TEMPLATE_NAMES = ("end_turn_btn", "end_turn_btn_white")
MIN_STROKE_PIXELS = 80
MIN_COLOR_FRACTION = 0.80
MAX_OTHER_COLOR_FRACTION = 0.10


def _stroke_color(patch, template):
    """Return a color only when most expected text strokes share that color."""
    template = cv2.resize(template, (patch.shape[1], patch.shape[0]),
                          interpolation=cv2.INTER_AREA)
    mask = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY) > 100
    count = int(mask.sum())
    metrics = {"stroke_pixels": count, "white_fraction": 0.0, "orange_fraction": 0.0}
    if count < MIN_STROKE_PIXELS:
        return None, metrics
    pixels = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[mask]
    hue, saturation, value = pixels.T
    # OpenCV hue is 0..179. The intentionally separated bands leave ambiguous
    # saturation/brightness unknown rather than guessing from the template name.
    white = (saturation <= 65) & (value >= 110)
    orange = ((hue >= 5) & (hue <= 35) & (saturation >= 90) & (value >= 100))
    wf, of = float(white.mean()), float(orange.mean())
    metrics.update(white_fraction=wf, orange_fraction=of,
                   median_hsv=[float(v) for v in np.median(pixels, axis=0)])
    if wf >= MIN_COLOR_FRACTION and of <= MAX_OTHER_COLOR_FRACTION:
        return "white", metrics
    if of >= MIN_COLOR_FRACTION and wf <= MAX_OTHER_COLOR_FRACTION:
        return "orange", metrics
    return None, metrics


def inspect_end_button(frame, templates=None, min_score=0.82):
    """Return presence, measured color and evidence; uncertain color is None.

    Input uses the existing normalized BGR screenshot coordinate system. Template
    existence and color confidence are separate facts: ``present=True`` with
    ``state=None`` must not be treated as a confirmed white or orange button.
    """
    result = {"state": None, "present": False, "score": 0.0, "box": None,
              "matched_template": None, "reason": "invalid_frame", "color_metrics": {}}
    if (frame is None or not hasattr(frame, "shape") or frame.ndim != 3
            or frame.shape[2] != 3 or frame.dtype != np.uint8):
        return result
    try:
        import ui_state
        if templates is None:
            meta, _note = ui_state.load_platform_meta("android")
            templates = ui_state.load_templates(meta)
        best_name, best_score, best_box = None, 0.0, None
        for name in TEMPLATE_NAMES:
            template = templates.get(name)
            if template is None:
                continue
            score, box = ui_state.match_roi(frame, name, template)
            if np.isfinite(score) and score > best_score:
                best_name, best_score, best_box = name, float(score), box
        result.update(score=best_score, matched_template=best_name, reason="weak_shape")
        if best_box is None or best_score < min_score:
            return result
        if isinstance(best_box, dict):
            x, y, width, height = (int(best_box[k]) for k in ("x", "y", "w", "h"))
        else:
            x, y, width, height = (int(v) for v in best_box)
        if min(width, height) <= 0 or x < 0 or y < 0 or x + width > frame.shape[1] or y + height > frame.shape[0]:
            result["reason"] = "invalid_match_box"
            return result
        result.update(present=True, box=[x, y, width, height])
        state, metrics = _stroke_color(frame[y:y+height, x:x+width], templates[best_name])
        result.update(state=state, color_metrics=metrics,
                      reason="confirmed_color" if state is not None else "uncertain_color")
        return result
    except Exception as error:
        result.update(state=None, reason="analysis_error", error=type(error).__name__)
        return result


def end_turn_state(frame, templates=None, min_score=0.82):
    """Compatibility result: observed white/orange, otherwise None."""
    return inspect_end_button(frame, templates, min_score)["state"]
