"""
card_reader.py - offline hover-and-OCR card identification (M3 core).

Given a screenshot with a hover-detail panel showing one enlarged card,
extract the card's name and its Kredits cost using local OCR (RapidOCR).
No network involved.

The hover panel layout (measured from probes at 1280x720):
  - enlarged card cost text appears as "<N>K" near the card top
  - card name is a bold text line right under/beside the cost

We locate text by scanning OCR results for:
  - name: a line matching a known card name from data.json (best match)
  - cost: a token like "NK" or a bare number near the name
"""

from __future__ import annotations

import os
import re

import cv2

DATA_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "card_db_test", "kards_data.json",
)

# name candidates built lazily from data.json (zh-Hans titles)
_NAME_SET = None
_NAME_LIST = None


def _load_names():
    global _NAME_SET, _NAME_LIST
    if _NAME_SET is not None:
        return
    import json

    names = set()
    try:
        with open(DATA_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        for c in data.get("cards", []):
            j = c.get("json", {})
            zh = (j.get("title") or {}).get("zh-Hans", "")
            if zh:
                names.add(zh)
    except Exception:
        pass
    _NAME_SET = names
    _NAME_LIST = sorted(names, key=len, reverse=True)  # longest first for greedy match
    print(f"card_reader: loaded {len(names)} zh card names")


def _ocr(img_bgr):
    from rapidocr_onnxruntime import RapidOCR

    if not hasattr(_ocr, "_engine"):
        _ocr._engine = RapidOCR()
    res, _ = _ocr._engine(img_bgr)
    out = []
    if res:
        for item in res:
            box, text, conf = item[0], item[1], float(item[2])
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            out.append({
                "text": str(text),
                "conf": conf,
                "x": min(xs),
                "y": min(ys),
                "cx": sum(xs) / 4,
                "cy": sum(ys) / 4,
            })
    return out


def read_hover_card(img_bgr, debug: bool = False):
    """
    img_bgr: full client capture showing a hover-detail enlarged card.
    Returns dict {name, cost, matched_name, ocr_lines} or None.
    """
    _load_names()
    h, w = img_bgr.shape[:2]
    lines = _ocr(img_bgr)

    # 1) find card name: the OCR line that best matches a known card name.
    #    hover card name sits in upper area (y < 60% height).
    name = None
    name_conf = 0.0
    name_line = None
    for ln in lines:
        if ln["y"] > h * 0.65:
            continue  # ignore bottom hand fan text
        t = re.sub(r"\s+", "", ln["text"])
        # exact or substring against known names
        for cand in _NAME_LIST:
            c = re.sub(r"\s+", "", cand)
            if c == t or (len(c) >= 4 and (c in t or t in c)):
                if ln["conf"] > name_conf:
                    name = cand
                    name_conf = ln["conf"]
                    name_line = ln
                break

    # 2) cost: look for "<n>K" token anywhere, or a bare number line close to name.
    cost = None
    cost_token = None
    for ln in lines:
        m = re.search(r"(\d{1,2})\s*K(?:rédit|redits)?", ln["text"], re.I)
        if m:
            cost = int(m.group(1))
            cost_token = ln
            break
    if cost is None:
        # fallback: bare number tokens like "4" near upper area
        best = None
        for ln in lines:
            if ln["y"] > h * 0.6:
                continue
            m = re.fullmatch(r"\d{1,2}", ln["text"].strip())
            if m and (best is None or ln["conf"] > best[0]):
                best = (ln["conf"], int(m.group()))
        if best:
            cost = best[1]

    if debug:
        print(f"  name={name} (conf {name_conf:.2f}) cost={cost} "
              f"lines={len(lines)}")
        for ln in lines:
            if ln["y"] < h * 0.65:
                print(f"    [{ln['x']:.0f},{ln['y']:.0f}] {ln['text']} ({ln['conf']:.2f})")

    if not name and cost is None:
        return None
    return {
        "name": name,
        "cost": cost,
        "name_conf": name_conf,
        "matched_line": name_line,
        "cost_line": cost_token,
    }


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from win import capture_client_bgr, find_by_process, set_dpi_aware

    set_dpi_aware()
    wins = find_by_process("kards")
    if wins:
        frame = capture_client_bgr(wins[0]["hwnd"])
        if frame is not None:
            cv2.imwrite(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "shots", "card_reader_live.png"), frame)
            print(read_hover_card(frame, debug=True))
