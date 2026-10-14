"""PC hand cost candidates from one neutral 1280x720 frame.

Orange ink must form a tall numeral on a dark plate. A candidate is not a
permission to play: the hover scanner still identifies the card and the engine
applies its rules. Coordinates are calibrated for the PC fan, not Android.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import os
import cv2
import numpy as np

ENABLED = os.environ.get('KARDS_ORANGE_SCAN', '1') != '0'
ZONE = (340, 605, 960, 706)


def candidates(frame, zone=ZONE, height_range=(14, 30), colour='orange'):
    if frame is None or frame.shape[:2] != (720, 1280):
        return []
    x0, y0, x1, y1 = zone
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    orange = ((h >= 6) & (h <= 32) & (s >= 120) & (v >= 115)).astype(np.uint8)
    mask = orange if colour=='orange' else ((s<=100)&(v>=135)).astype(np.uint8)
    roi = np.zeros_like(mask)
    roi[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
    _, _, stats, _ = cv2.connectedComponentsWithStats(roi)
    orange_roi = np.zeros_like(orange)
    orange_roi[y0:y1,x0:x1]=orange[y0:y1,x0:x1]
    _, _, k_stats, _ = cv2.connectedComponentsWithStats(orange_roi)
    found = []
    for x, y, w, height, area in stats[1:]:
        x, y, w, height, area = map(int, (x, y, w, height, area))
        # K, operation-cost annotations and fan title letters are smaller.
        if not (height_range[0] <= height <= height_range[1] and 4 <= w <= 45
                and w / height <= 1.5 and 28 <= area <= 1100):
            continue
        pad = v[max(y0, y-3):min(y1, y+height+3),
                max(x0, x-3):min(x1, x+w+3)]
        if not pad.size or float(np.mean(pad < 115)) < .40:
            continue
        # A real cost has the small K at its upper-right. Orange artwork and
        # title fragments must not turn into hover probes.
        k_found = any(3 <= kh <= 13 and 2 <= kw <= 12 and ka >= 6
                      and x+w-2 <= kx <= x+w+15 and y-4 <= ky <= y+height*.6
                      for kx, ky, kw, kh, ka in k_stats[1:])
        if not k_found:
            continue
        compound = any(2 <= pw <= 25 and ph>=height*.7
                       and 0<=x-(px+pw)<=7 and abs(py-y)<=5
                       for px, py, pw, ph, pa in stats[1:])
        found.append(dict(x=x, y=y, w=w, h=height, area=area,
                          compound=compound, probe_x=int(x+w/2+22)))
    return sorted(found, key=lambda c: c['x'])


@lru_cache(maxsize=1)
def _templates():
    root = Path(__file__).resolve().parents[1] / 'config/hand_cost_digits'
    bank = {}
    for p in root.glob('[0-9]*.png'):
        bank.setdefault(int(p.stem.split('_')[0]), []).append(
            cv2.imread(str(p), cv2.IMREAD_GRAYSCALE))
    return bank


def read_candidate_cost(frame, candidate, ocr=None):
    if candidate.get('compound'):
        return None  # A two-digit fee must never be truncated to its last digit.
    from kredits_templates import normalize_glyph, score_against
    x, y, w, h = (candidate[k] for k in ('x', 'y', 'w', 'h'))
    hsv = cv2.cvtColor(frame[y:y+h, x:x+w], cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 0] >= 6) & (hsv[:, :, 0] <= 32)
            & (hsv[:, :, 1] >= 120) & (hsv[:, :, 2] >= 115)).astype(np.uint8)*255
    padded = cv2.copyMakeBorder(mask, 20, 20, 20, 20, cv2.BORDER_CONSTANT)
    scores = {}
    for angle in range(-24, 25, 3):
        hh, ww = padded.shape
        mat = cv2.getRotationMatrix2D((ww/2, hh/2), angle, 1)
        rotated = cv2.warpAffine(padded, mat, (ww, hh), flags=cv2.INTER_NEAREST)
        glyph = normalize_glyph(rotated)
        if glyph is None:
            continue
        for digit, templates in _templates().items():
            for template in templates:
                normalized = normalize_glyph(template)
                if normalized is not None:
                    score = score_against(glyph, normalized)
                    scores[digit] = max(scores.get(digit, -1), score)
    ranked = sorted(scores.items(), key=lambda p: -p[1])
    candidate['digit_scores'] = {str(d): round(s, 3) for d, s in ranked}
    if not ranked or ranked[0][1] < .72:
        return None
    if len(ranked) > 1 and ranked[0][1]-ranked[1][1] < .10:
        return None
    return ranked[0][0]


def best_combo(cards, budget, unit_slots=4):
    """Maximize spent credits; equal spend prefers more cards, then cheap first.

    Caller provides only legal candidates with currently measured costs.
    Enumerating at most ten hand cards is cheap and preserves duplicate copies.
    """
    import orders
    if not isinstance(budget, int) or budget < 0:
        return []
    valid = [c for c in cards if isinstance(c.get('cost'), int)
             and 0 <= c['cost'] <= budget]
    if len(valid)>10:
        return []
    best, best_key = [], (-1, -1)
    for bits in range(1, 1 << len(valid)):
        subset = [c for i, c in enumerate(valid) if bits & (1 << i)]
        spend = sum(c['cost'] for c in subset)
        units = sum(c.get('type') != 'order' for c in subset)
        if sum(orders.is_weather(c.get('name')) for c in subset) > 1:
            continue
        key = (spend, len(subset))
        if spend <= budget and units <= unit_slots and key > best_key:
            best, best_key = subset, key
    return sorted(best, key=lambda c: (c['cost'], c['x']))
