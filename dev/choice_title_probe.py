r"""Read-only A/B of two-card title OCR on saved real choice frames.

Run from the repository root: .venv\Scripts\python.exe dev\choice_title_probe.py
No game window or mouse access. Crops from ignored shots/choice_samples and
shots/choice; intended for investigating title-read failures.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from hover_card_reader import _ocr  # noqa: E402
import order_choice  # noqa: E402


def load(path: Path):
    image = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    if image is not None and image.shape[:2] == (766, 1284):
        image = image[45:765, 2:1282]
    return image


paths = (
    ROOT / "shots/choice_samples/choice_two.png",
    ROOT / "shots/choice/0926_192524_blocked.png",
)
for path in paths:
    frame = load(path)
    print(path, frame.shape, order_choice.titles_match(frame, "呼叫殖民地"))
    for side, x in zip(("left", "right"), order_choice.CARD_LEFTS):
        crops = {
            "old": frame[430:457, x + 8:x + 184],
            "title-wide": frame[425:472, x + 10:x + 180],
            "title-tight": frame[430:461, x + 36:x + 154],
            "lower-card": frame[420:501, x + 10:x + 180],
        }
        for label, crop in crops.items():
            for scale in (2, 3):
                enlarged = cv2.resize(crop, None, fx=scale, fy=scale)
                enlarged = cv2.copyMakeBorder(enlarged, 12, 12, 12, 12,
                    cv2.BORDER_CONSTANT, value=(200, 200, 200))
                lines = _ocr(enlarged)
                print(side, label, scale, [(item["text"], round(item["conf"], 3),
                                          round(item["x"]), round(item["y"]))
                                           for item in lines])
