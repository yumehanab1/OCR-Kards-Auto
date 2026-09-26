r"""Read-only OCR probe for saved three-option KARDS screenshots.

Run: python\python.exe dev\three_title_probe.py
Reads ignored shots/choice_samples/three_*.png; does not access the game.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from hover_card_reader import _ocr  # noqa: E402
from order_choice import THREE_LEFTS  # noqa: E402

cards = json.loads((ROOT / "card_db/kards_data.json").read_text(encoding="utf-8"))
known = {card.get("json", {}).get("title", {}).get("zh-Hans", "")
         for card in cards["cards"]}
print("known weather titles", [(name, name in known) for name in
      ("蓝天", "薄雾", "狂风", "雷暴", "热带风暴", "旋风")])

for name in ("three_first.png", "three_second.png"):
    path = ROOT / "shots/choice_samples" / name
    frame = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    if frame.shape[:2] == (766, 1284):
        frame = frame[45:765, 2:1282]
    print(name, frame.shape)
    for side, x in zip(("left", "middle", "right"), THREE_LEFTS):
        for bounds in ((430, 457), (425, 467), (430, 470)):
            crop = frame[bounds[0]:bounds[1], x + 8:x + 184]
            crop = cv2.resize(crop, None, fx=2, fy=2)
            crop = cv2.copyMakeBorder(crop, 12, 12, 12, 12,
                                      cv2.BORDER_CONSTANT,
                                      value=(200, 200, 200))
            print(side, bounds, [(line["text"], round(line["conf"], 3),
                                  round(line["y"])) for line in _ocr(crop)])
