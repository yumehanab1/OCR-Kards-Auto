r"""
hover_card_reader.py - offline hover-card recognition (M3).

★ 这个 docstring 必须是 raw string(开头那个 r 前缀不能去掉):下面写着正则
  `^N\s*K$`,而 `\s` 在普通字符串里是**无效转义序列** —— Python 会为此发
  SyntaxWarning,并且明说以后会失效。警告本身无害,但它是**每次从压缩包解压后
  第一次运行时**都会冒出来的(解压出来的副本没有 __pycache__),使用者看到
  "Warning" 会以为自己装坏了。2026-09-18 从打好的 zip 里验出来的。

Strategy (no fixed crop, works wherever the hover panel appears):
  The hovered card's cost badge looks like "<N>K" (or "<N> Kredits") and is
  OCRed as a short token near the enlarged card. The card name is the largest
  text line near that token (same row or just below, larger font than UI text).

  Because the screen also shows other cards (enemy board, own field, hand fan),
  we must pick the *hover card cluster*:
    1. OCR whole frame.
    2. Find candidate cost tokens matching ^N+K$/^N\s*K$/i with N in 0..20.
    3. For each candidate, find the nearest high-confidence text line below it
       that looks like a card name (matches data.json OR is a short bold line).
    4. Choose the best (cost, name) cluster.
"""

from __future__ import annotations

import json
import os
import re

import cv2

from card_match import DATA_JSON      # 卡库路径统一在 card_match 里解析
                                      # (2026-09-19 起目录名是 card_db\,旧名字兜底)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_NAME_SET = None
_NAME_LIST = None
_EN_TO_ZH = None      # {norm_upper(en_name): zh_name}
_EN_LIST = None       # [(norm_upper(en_name), zh_name)] longest first
_OCR_ENGINE = None


def _load_names():
    global _NAME_SET, _NAME_LIST, _EN_TO_ZH, _EN_LIST
    if _NAME_SET is not None:
        return
    names = set()
    en_to_zh: dict[str, str] = {}
    try:
        with open(DATA_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        for c in data.get("cards", []):
            title = (c.get("json", {}).get("title") or {})
            zh = title.get("zh-Hans", "")
            en = title.get("en-EN", "")
            if zh:
                names.add(zh)
            if zh and en:
                key = _norm(en).upper()
                if key and key not in en_to_zh:
                    en_to_zh[key] = zh
    except Exception:
        pass
    _NAME_SET = names
    _NAME_LIST = sorted(names, key=len, reverse=True)
    _EN_TO_ZH = en_to_zh
    _EN_LIST = sorted(en_to_zh.items(), key=lambda kv: len(kv[0]), reverse=True)
    print(f"hover_card_reader: loaded {len(names)} zh names, {len(en_to_zh)} en names")


def _ocr(img_bgr):
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR, __file__ as rapidocr_file

        engine_dir = os.path.dirname(rapidocr_file)
        config_path = os.path.join(engine_dir, "config_ppocrv6.yaml")
        # RapidOCR silently falls back to v4 if config_path is missing.
        if not os.path.isfile(config_path):
            raise FileNotFoundError(config_path)
        # Official PP-OCRv6 small models need their own CTC dictionary.
        _OCR_ENGINE = RapidOCR(
            config_path=config_path,
            rec_keys_path=os.path.join(engine_dir, "models", "ppocrv6_dict.txt"),
        )
    res, _ = _OCR_ENGINE(img_bgr)
    out = []
    if res:
        for item in res:
            box, text, conf = item[0], item[1], float(item[2])
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            out.append({
                "text": str(text),
                "conf": conf,
                "x": min(xs), "y": min(ys),
                "w": max(xs) - min(xs),
                "h": max(ys) - min(ys),
                "cx": sum(xs) / 4,
                "cy": sum(ys) / 4,
            })
    return out


def _norm(t):
    return re.sub(r"\s+", "", t)


def _match_name(t):
    """Return canonical zh-Hans name if OCR text matches a known card, else None.

    Tries Chinese first, then English (en-EN field, case-insensitive).
    Short titles may match exactly; a fragment shorter than four normalised
    characters is not sufficient evidence for a longer card title.
    """
    tn = _norm(t)
    if not tn:
        return None
    # Check exact short titles, but do not turn a board glyph (e.g. K) into a card.
    if tn in _NAME_SET:
        return tn
    for cand in _NAME_LIST:
        c = _norm(cand)
        if c == tn:
            return cand
        if len(c) >= 4 and len(tn) >= 4 and (c in tn or tn in c):
            return cand
    # --- English path ---
    tnu = tn.upper()
    if tnu in _EN_TO_ZH:
        return _EN_TO_ZH[tnu]
    for en_key, zh in _EN_LIST:
        if en_key == tnu:
            return zh
        if len(en_key) >= 4 and len(tnu) >= 4 and (en_key in tnu or tnu in en_key):
            return zh
    return None


def read_hover_card(img_bgr, debug=False):
    _load_names()
    h, w = img_bgr.shape[:2]
    lines = _ocr(img_bgr)
    if debug:
        print(f"  OCR lines: {len(lines)}")
        for ln in sorted(lines, key=lambda l: (l["y"], l["x"])):
            print(f"    [{ln['x']:.0f},{ln['y']:.0f}] {ln['text']!r} conf={ln['conf']:.2f}")

    # Candidate cost tokens: "2K", "1 K", "20" near top-half (hover panel), etc.
    candidates = []
    for ln in lines:
        t = ln["text"].strip()
        m = re.fullmatch(r"(\d{1,2})\s*K", t, re.I)
        if m:
            candidates.append((int(m.group(1)), ln))
            continue
        # bare number with small width, in upper half
        if re.fullmatch(r"\d{1,2}", t) and ln["y"] < h * 0.6:
            candidates.append((int(t), ln))

    if not candidates:
        if debug:
            print("  no cost token found")
        return None

    best = None
    best_score = -1
    for cost, tok in candidates:
        # name should be near the cost token: same y band (within 90px) or below
        for ln in lines:
            if ln is tok:
                continue
            dy = abs(ln["cy"] - tok["cy"])
            if ln["y"] > h * 0.6:  # ignore hand fan region
                continue
            if dy > 100:           # must be close to the cost badge
                continue
            name = _match_name(ln["text"])
            if name is None:
                continue
            # prefer exact/confident and close
            score = ln["conf"] * 10 - dy / 10
            if ln["text"].strip() == _norm(ln["text"]) and name:
                score += 2
            if score > best_score:
                best_score = score
                best = {"name": name, "cost": cost, "name_conf": ln["conf"],
                        "name_line": ln, "cost_line": tok}

    if debug:
        if best:
            print(f"  => {best['name']} cost={best['cost']} (score {best_score:.1f})")
        else:
            print("  => no name/cost cluster found")
    return best


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from win import capture_client_bgr, find_by_process, set_dpi_aware
    set_dpi_aware()
    wins = find_by_process("kards")
    if wins:
        frame = capture_client_bgr(wins[0]["hwnd"])
        if frame is not None:
            cv2.imwrite(os.path.join(PROJECT_ROOT, "shots", "hover_live.png"), frame)
            print(read_hover_card(frame, debug=True))
