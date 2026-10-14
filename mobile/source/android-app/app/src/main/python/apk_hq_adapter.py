"""APK-only recovery for dark saturated HQ shields; no new digit templates.

The original saturation-only OR mask can join olive shield pixels to the rim,
leaving no usable glyphs. Keep existing successful reads verbatim. On exactly
that extraction failure, require bright white or sufficiently bright red/green
pixels, then use the original digit bank with stricter confidence and geometry.
This does not identify a card as HQ: mobile_board retains its support-row,
large-shield geometry and unique-candidate checks before accepting this read.
"""
from __future__ import annotations

import cv2
import numpy as np

_ORIGINAL_READ_SHIELD = None


def _dark_olive_fragment(hsv, glyphs, labels, stats, bank_):
    """Distinguish one failed shield-bottom fragment from an actual glyph.

    The broad saturation mask can leave a small disconnected piece of the
    olive shield bottom. Every component pixel must be dim and outside all
    supported digit colors; a normal low-confidence digit is never retried.
    """
    import hq_hp
    if len(glyphs) != 1 or not all(k in glyphs[0] for k in ("img", "x", "y", "w", "h")):
        return None
    glyph = glyphs[0]
    x, y, w, h = (glyph[key] for key in ("x", "y", "w", "h"))
    if w < h or y < hsv.shape[0] * .65 or h > hsv.shape[0] * .25:
        return None
    components = [i for i in range(1, len(stats))
                  if tuple(int(v) for v in stats[i, :4]) == (x, y, w, h)]
    if len(components) != 1:
        return None
    pixels = hsv[labels == components[0]]
    if (not len(pixels) or np.any(pixels[:, 2] >= hq_hp.V_FLOOR)
            or np.any(pixels[:, 1] <= hq_hp.COLOR_WHITE_MAX_S)
            or np.any(pixels[:, 0] <= hq_hp.COLOR_RED_HUE[1])
            or np.any(pixels[:, 0] >= hq_hp.COLOR_GREEN_HUE[0])):
        return None
    digit, score, runner_score, runner_digit = hq_hp._match_digit(glyph["img"], bank_)
    if not np.isfinite(score) or score >= hq_hp.MATCH_MIN:
        return None
    return {"reason": "non_digit_dark_olive_bottom_fragment", "box": [x, y, w, h],
            "component_pixels": len(pixels), "hsv_min": pixels.min(axis=0).tolist(),
            "hsv_max": pixels.max(axis=0).tolist(), "best_digit": digit, "score": score,
            "next_digit": runner_digit, "next_score": runner_score}


def _green_bottom_fringe(shield, hsv, raw_mask, closed_mask, glyph, bg):
    """Recover one near-threshold source row, never synthesize or pad pixels.

    A small change in the shield background percentile can remove the two dim
    antialiased pixels at a green digit's bottom. The even CLOSE shifts its
    bounding box down/right; require that exact raw component, a connected
    two-pixel fringe less than 3/255 below the existing threshold, and exactly
    one new row after closing. All other components and crop edges stay fixed.
    """
    import hq_hp
    x, y, w, h = (glyph[key] for key in ("x", "y", "w", "h"))
    height, width = raw_mask.shape
    if (h + 1 > hq_hp.GLYPH_H_MAX or y + h + 1 >= height - 1
            or x <= 1 or x + w >= width - 1):
        return None
    _, raw_labels, raw_stats, _ = cv2.connectedComponentsWithStats(raw_mask, 8)
    exact = [i for i in range(1, len(raw_stats))
             if tuple(int(v) for v in raw_stats[i, :4]) == (x - 1, y - 1, w, h)]
    if len(exact) != 1:
        return None
    rx, fringe_y = x - 1, y + h - 1
    threshold = max(45.0, bg + hq_hp.V_REL_DELTA)
    hue, sat, value = (hsv[:, :, i].astype(float) for i in range(3))
    green = ((hue >= hq_hp.COLOR_GREEN_HUE[0]) & (hue <= hq_hp.COLOR_GREEN_HUE[1])
             & (sat > hq_hp.SAT_DIGIT))
    near = green & (value > max(45.0, threshold - 3.0)) & (value <= threshold)
    fringe = near[fringe_y, rx:rx+w].copy()
    # One isolated antialias/noise pixel is not enough. Neither a detached row
    # nor a second faint row can supply this narrowly supported extension.
    preceding = raw_labels[fringe_y-1, rx:rx+w] == exact[0]
    connected = np.convolve(preceding.astype(np.uint8), np.ones(3, np.uint8), "same") > 0
    if (raw_mask[fringe_y, rx:rx+w].any() or not np.any(fringe[:-1] & fringe[1:])
            or np.any(fringe & ~connected) or fringe[0] or fringe[-1]
            or np.any((green & (value > max(45.0, threshold - 3.0)))[fringe_y+1:fringe_y+3, rx:rx+w])):
        return None
    augmented = raw_mask.copy()
    augmented[fringe_y, rx:rx+w] |= fringe.astype(np.uint8)
    revised = cv2.morphologyEx(augmented, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    changed = revised != closed_mask
    changed[y:y+h+1, x:x+w] = False
    if changed.any():
        return None
    _, _, stats, _ = cv2.connectedComponentsWithStats(revised, 8)
    if not any(tuple(int(v) for v in row[:4]) == (x, y, w, h + 1) for row in stats[1:]):
        return None
    return {
        "img": shield[y:y+h+1, x:x+w].copy(),
        "evidence": {"method": "connected_green_bottom_source_fringe", "source_row": fringe_y,
                     "source_x": [int(rx + k) for k in np.flatnonzero(fringe)],
                     "source_values": value[fringe_y, rx:rx+w][fringe].tolist(),
                     "threshold": threshold, "original_box": [x, y, w, h],
                     "recovered_box": [x, y, w, h + 1]},
    }


def _red_top_singleton(shield, hsv, raw_mask, closed_mask, glyph, bg):
    """Recover a crop enlarged by one barely visible red source pixel.

    Only one red pixel one intensity step above the existing color threshold
    may extend the raw component above a broad, bright connected body. Removing
    that mask pixel must alter exactly one closed-mask pixel and only the top
    row of this component. Match real source pixels in the revised crop; this
    neither lowers digit confidence nor replaces pixels with a template.
    """
    import hq_hp
    x, y, w, h = (glyph[key] for key in ("x", "y", "w", "h"))
    height, width = raw_mask.shape
    if (h - 1 < hq_hp.GLYPH_H_MIN or x <= 1 or y <= 2
            or x + w >= width - 1 or y + h >= height - 1):
        return None
    _, labels, stats, _ = cv2.connectedComponentsWithStats(raw_mask, 8)
    exact = [i for i in range(1, len(stats))
             if tuple(int(v) for v in stats[i, :4]) == (x - 1, y - 1, w, h)]
    if len(exact) != 1:
        return None
    component = exact[0]
    rx, ry = x - 1, y - 1
    top = np.flatnonzero(labels[ry, rx:rx+w] == component)
    if (len(top) != 1 or top[0] in (0, w - 1)
            or int(raw_mask[ry, rx:rx+w].sum()) != 1
            or raw_mask[ry-1, rx:rx+w].any()):
        return None
    px = int(rx + top[0])
    hue, sat, value = (float(v) for v in hsv[ry, px])
    threshold = max(45.0, bg + hq_hp.V_REL_DELTA)
    red = hue <= hq_hp.COLOR_RED_HUE[1] or hue >= hq_hp.COLOR_RED_HUE[0]
    if (not red or sat <= hq_hp.SAT_DIGIT or not threshold < value <= threshold + 1.0
            or value >= hq_hp.V_FLOOR):
        return None
    body = labels[ry+1, rx:rx+w] == component
    body_x = np.flatnonzero(body)
    body_pixels = hsv[ry+1, rx:rx+w][body]
    if (not body[top[0]] or len(body_x) < max(4, (w + 1) // 2)
            or np.any(np.diff(body_x) != 1)
            or np.count_nonzero(body_pixels[:, 2] >= hq_hp.V_FLOOR) < 3
            or np.any(body_pixels[:, 1] <= hq_hp.SAT_DIGIT)
            or np.any((body_pixels[:, 0] > hq_hp.COLOR_RED_HUE[1])
                      & (body_pixels[:, 0] < hq_hp.COLOR_RED_HUE[0]))):
        return None
    revised_raw = raw_mask.copy()
    revised_raw[ry, px] = 0
    revised = cv2.morphologyEx(revised_raw, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    changed = revised != closed_mask
    if (int(changed.sum()) != 1 or int(changed[y, x:x+w].sum()) != 1
            or np.any(revised[changed] != 0)):
        return None
    count, _, revised_stats, _ = cv2.connectedComponentsWithStats(revised, 8)
    old_count, _, _, _ = cv2.connectedComponentsWithStats(closed_mask, 8)
    if count != old_count:
        return None
    boxes = [s for s in revised_stats[1:] if tuple(int(v) for v in s[:4]) == (x, y + 1, w, h - 1)]
    if (len(boxes) != 1 or boxes[0][4] < hq_hp.GLYPH_AREA_MIN
            or boxes[0][4] / float(w * (h - 1)) < hq_hp.GLYPH_FILL_MIN):
        return None
    return {"img": shield[y+1:y+h, x:x+w].copy(),
            "evidence": {"method": "single_near_threshold_red_top_source_pixel", "source_xy": [px, ry],
                         "source_hsv": [hue, sat, value], "threshold": threshold,
                         "original_box": [x, y, w, h], "recovered_box": [x, y + 1, w, h - 1],
                         "closed_mask_changed_pixels": 1, "other_mask_pixels_unchanged": True}}


def inspect_shield(shield, sbox=None, bank_=None):
    """Diagnose the narrow fallback; result is not input authorization."""
    import hq_hp
    result = {"read": None, "reason": "invalid_shield", "evidence": {}}
    if (not isinstance(shield, np.ndarray) or shield.ndim != 3
            or shield.shape[2] != 3 or shield.dtype != np.uint8):
        return result
    # read_box deliberately includes a 5px outer pad. When its stated shield
    # geometry proves that exact pad, keep map art outside the numeral crop.
    # find_shield supplies matching dimensions and therefore never enters here.
    if (isinstance(sbox, (tuple, list)) and len(sbox) == 4
            and shield.shape[:2] == (sbox[3] + 10, sbox[2] + 10)):
        shield = shield[5:-5, 5:-5]
        result["evidence"]["known_read_box_pad_removed"] = 5
    height, width = shield.shape[:2]
    # Includes the core's find_shield crop and read_box's 5px verification pad;
    # small unit type icons are not eligible for this extraction fallback.
    if not (42 <= width <= 78 and 38 <= height <= 80):
        result["reason"] = "unsupported_shield_geometry"
        return result
    original_glyphs = hq_hp.extract_glyphs(shield)
    hsv = cv2.cvtColor(shield, cv2.COLOR_BGR2HSV)
    hue, sat, value = (hsv[:, :, i].astype(float) for i in range(3))
    bg = float(np.percentile(value, 55))
    # The newly observed failure requires dark saturated pixels, not a low
    # digit score. Never retry ordinary ambiguous/low-confidence reads here.
    spill = (sat > hq_hp.SAT_DIGIT) & (value < hq_hp.V_FLOOR)
    result["evidence"].update(background_value=bg, dark_saturated_fraction=float(spill.mean()))
    broad_mask = ((value > max(float(hq_hp.V_FLOOR), bg + hq_hp.V_REL_DELTA))
                  | (sat > hq_hp.SAT_DIGIT)).astype(np.uint8)
    broad_mask = cv2.morphologyEx(broad_mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    _, broad_labels, broad_stats, _ = cv2.connectedComponentsWithStats(broad_mask, 8)
    if original_glyphs:
        fragment = _dark_olive_fragment(hsv, original_glyphs, broad_labels, broad_stats,
                                       hq_hp.bank() if bank_ is None else bank_)
        if fragment is None:
            result["reason"] = "original_extraction_available"
            return result
        result["evidence"]["discarded_original_fragment"] = fragment
    merged = any(w >= width*.9 and h >= height*.9
                 and (w > hq_hp.GLYPH_W_MAX or h > hq_hp.GLYPH_H_MAX)
                 for _x, _y, w, h, area in broad_stats[1:])
    result["evidence"]["original_mask_merged_with_rim"] = bool(merged)
    if int(spill.sum()) < hq_hp.GLYPH_AREA_MIN or not merged:
        result["reason"] = "no_dark_saturation_spill"
        return result
    digit_hue = ((hue <= hq_hp.COLOR_RED_HUE[1]) | (hue >= hq_hp.COLOR_RED_HUE[0])
                 | ((hue >= hq_hp.COLOR_GREEN_HUE[0]) & (hue <= hq_hp.COLOR_GREEN_HUE[1])))
    raw_mask = ((value > max(float(hq_hp.V_FLOOR), bg + hq_hp.V_REL_DELTA))
                | ((sat > hq_hp.SAT_DIGIT) & digit_hue
                   & (value > max(45.0, bg + hq_hp.V_REL_DELTA)))).astype(np.uint8)
    mask = cv2.morphologyEx(raw_mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    count, components, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    glyphs = []
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if not (hq_hp.GLYPH_W_MIN <= w <= hq_hp.GLYPH_W_MAX
                and hq_hp.GLYPH_H_MIN <= h <= hq_hp.GLYPH_H_MAX
                and area >= hq_hp.GLYPH_AREA_MIN and area / float(w*h) >= hq_hp.GLYPH_FILL_MIN):
            continue
        pixels = hsv[y:y+h, x:x+w][components[y:y+h, x:x+w] == index]
        glyphs.append({"img": shield[y:y+h, x:x+w].copy(), "x": x, "y": y, "w": w, "h": h,
                       "s": float(pixels[:, 1].mean()), "v": float(pixels[:, 2].mean()),
                       "hue": float(pixels[:, 0].mean())})
    glyphs.sort(key=lambda g: g["x"])
    result["evidence"]["glyph_boxes"] = [[g[k] for k in ("x", "y", "w", "h")] for g in glyphs]
    if len(glyphs) not in (1, 2):
        result["reason"] = "unknown_glyph_count"
        return result
    left, right = glyphs[0]["x"], glyphs[-1]["x"] + glyphs[-1]["w"]
    # An even 2x2 CLOSE with OpenCV's default anchor shifts these glyphs one
    # pixel down/right. The support-row crop can leave two blank source rows
    # below an intact red digit, but only one after closing. Accept precisely
    # that case, verified against the pre-morphology pixels. Touching the crop
    # edge, a nonblank source margin, and every other edge keep the old refusal.
    bottom_margin_recovered = []
    for index, glyph in enumerate(glyphs):
        end_y = glyph["y"] + glyph["h"]
        x0 = max(0, glyph["x"] - 1)
        x1 = min(width, glyph["x"] + glyph["w"] + 1)
        if (end_y == height - 1 and not raw_mask[-2:, x0:x1].any()
                and not mask[-1:, x0:x1].any()):
            bottom_margin_recovered.append(index)
    result["evidence"]["source_bottom_margin_recovered_glyphs"] = bottom_margin_recovered
    if (not .40 <= (left + right) / (2.0 * width) <= .60
            or any(g["x"] <= 1 or g["y"] <= 1 or g["x"] + g["w"] >= width - 1
                   or (g["y"] + g["h"] >= height - 1 and i not in bottom_margin_recovered)
                   for i, g in enumerate(glyphs))):
        result["reason"] = "off_center_or_clipped_glyphs"
        return result
    if len(glyphs) == 2:
        a, b = glyphs
        gap = b["x"] - (a["x"] + a["w"])
        if (abs(a["y"] - b["y"]) > 2 or abs(a["y"]+a["h"] - b["y"]-b["h"]) > 2
                or not 1 <= gap <= min(a["h"], b["h"]) * .5):
            result["reason"] = "misaligned_or_nonadjacent_glyphs"
            return result
    bank = hq_hp.bank() if bank_ is None else bank_
    digits, scores, details = [], [], []
    matched_boxes = [[g[key] for key in ("x", "y", "w", "h")] for g in glyphs]
    for glyph_index, glyph in enumerate(glyphs):
        digit, score, next_score, next_digit = hq_hp._match_digit(glyph["img"], bank)
        detail = {"digit": digit, "score": score, "next_digit": next_digit,
                  "next_score": next_score, "margin": score-next_score}
        details.append(detail)
        # Keep successful reads verbatim. Only the color-separated two-green-
        # digit path can recover a physically present bottom fringe. Preserve
        # the original winner and margin, then require the usual full score.
        if (len(glyphs) == 2 and all(hq_hp._color_state([g]) == "green" for g in glyphs)
                and digit is not None and np.isfinite(score) and np.isfinite(next_score)
                and score < max(.85, hq_hp.CONFIDENT_SCORE)
                and score-next_score >= hq_hp.AMBIGUOUS_MARGIN):
            recovered = _green_bottom_fringe(shield, hsv, raw_mask, mask, glyph, bg)
            if recovered is not None:
                candidate_boxes = [box[:] for box in matched_boxes]
                candidate_boxes[glyph_index] = recovered["evidence"]["recovered_box"]
                bottoms = [box[1] + box[3] for box in candidate_boxes]
                if max(bottoms) - min(bottoms) > 2:
                    recovered = None
            if recovered is not None:
                d2, s2, runner_score, runner_digit = hq_hp._match_digit(recovered["img"], bank)
                detail["fringe_attempt"] = dict(recovered["evidence"], digit=d2, score=s2,
                                                next_digit=runner_digit, next_score=runner_score)
                if (d2 == digit and np.isfinite(s2) and np.isfinite(runner_score)
                        and s2 >= max(.85, hq_hp.CONFIDENT_SCORE)
                        and s2-runner_score >= hq_hp.AMBIGUOUS_MARGIN):
                    detail["original_score"] = score
                    score, next_score, next_digit = s2, runner_score, runner_digit
                    matched_boxes[glyph_index] = recovered["evidence"]["recovered_box"]
                    detail.update(score=score, next_score=next_score, next_digit=next_digit,
                                  margin=score-next_score)
        # Red 3 can gain a top row when one antialiased source pixel changes
        # from V=threshold to threshold+1. Successful reads never enter this
        # branch; retain the original winner/margin and the full final limits.
        if (len(glyphs) == 2 and digit == 3 and np.isfinite(score) and np.isfinite(next_score)
                and score < max(.85, hq_hp.CONFIDENT_SCORE)
                and score-next_score >= hq_hp.AMBIGUOUS_MARGIN
                and all(hq_hp._color_state([g]) == "red" for g in glyphs)):
            recovered = _red_top_singleton(shield, hsv, raw_mask, mask, glyph, bg)
            if recovered is not None:
                candidate_boxes = [box[:] for box in matched_boxes]
                candidate_boxes[glyph_index] = recovered["evidence"]["recovered_box"]
                tops = [box[1] for box in candidate_boxes]
                bottoms = [box[1] + box[3] for box in candidate_boxes]
                if max(tops) - min(tops) > 2 or max(bottoms) - min(bottoms) > 2:
                    recovered = None
            if recovered is not None:
                d2, s2, runner_score, runner_digit = hq_hp._match_digit(recovered["img"], bank)
                detail["top_singleton_attempt"] = dict(recovered["evidence"], digit=d2, score=s2,
                                                        next_digit=runner_digit, next_score=runner_score)
                if (d2 == digit and np.isfinite(s2) and np.isfinite(runner_score)
                        and s2 >= max(.85, hq_hp.CONFIDENT_SCORE)
                        and s2-runner_score >= hq_hp.AMBIGUOUS_MARGIN):
                    detail["original_score"] = score
                    score, next_score, next_digit = s2, runner_score, runner_digit
                    matched_boxes[glyph_index] = recovered["evidence"]["recovered_box"]
                    detail.update(score=score, next_score=next_score, next_digit=next_digit,
                                  margin=score-next_score)
        if (digit is None or not np.isfinite(score) or score < max(.85, hq_hp.CONFIDENT_SCORE)
                or score-next_score < hq_hp.AMBIGUOUS_MARGIN):
            result.update(reason="uncertain_digit")
            result["evidence"]["digits"] = details
            return result
        digits.append(digit)
        scores.append(score)
    result["evidence"]["digits"] = details
    hp = int("".join(str(digit) for digit in digits))
    color = hq_hp._color_state(glyphs)
    if not 1 <= hp <= 99 or digits[0] == 0 or color not in ("white", "red", "green"):
        result["reason"] = "unknown_value_or_color"
        return result
    result.update(reason="strict_color_separated_templates", read={
        "hp": hp, "state": color, "score": round(min(scores), 3), "n_glyphs": len(glyphs),
        "shield_box": sbox, "why": "apk_color_separated_templates", "ambiguous": False})
    return result


def read_shield(shield, sbox=None, debug=False, bank_=None):
    """Keep original reads; only recover its saturated-background extraction failure."""
    original = _ORIGINAL_READ_SHIELD
    if original is None:
        import hq_hp
        original = hq_hp.read_shield
    got = original(shield, sbox, debug=debug, bank_=bank_)
    if got is not None:
        return got
    return inspect_shield(shield, sbox, bank_)["read"]


def install():
    """Install once inside the APK interpreter; never write the core source/bank."""
    global _ORIGINAL_READ_SHIELD
    import hq_hp
    if _ORIGINAL_READ_SHIELD is None:
        _ORIGINAL_READ_SHIELD = hq_hp.read_shield
        hq_hp.read_shield = read_shield
    return {"installed": True, "adapter": "apk_hq_adapter", "digit_templates": "unchanged"}
