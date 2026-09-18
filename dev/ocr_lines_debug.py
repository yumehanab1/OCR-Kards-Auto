"""tmp_ocr_lines.py - 看真实悬停面板里 OCR 各行长什么样。

目的:找出"卡名那一行"的可靠特征。之前拍脑袋用行高阈值(35)过滤,
结果把正确卡名(行高 23)也拒了,而卡名行高实测能在 23-69 之间波动,
所以行高不是稳定特征。先把数据打出来看。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2

from hand_scanner_v2 import _match_name, diff_bbox
from hover_card_reader import _ocr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 真实帧对:baseline(鼠标在安全点) + hover(悬停在某张牌上)
PAIRS = [
    ("diff_region", os.path.join(ROOT, "shots", "diff_base.png"),
     os.path.join(ROOT, "shots", "diff_hover.png")),
    ("x592", os.path.join(ROOT, "shots", "diffdiag", "base1.png"),
     os.path.join(ROOT, "shots", "diffdiag", "hover_x592.png")),
    ("x460", os.path.join(ROOT, "shots", "diffdiag", "base1.png"),
     os.path.join(ROOT, "shots", "diffdiag", "hover_x460.png")),
    ("x700", os.path.join(ROOT, "shots", "diffdiag", "base1.png"),
     os.path.join(ROOT, "shots", "diffdiag", "hover_x700.png")),
]

for tag, bp, hp in PAIRS:
    base = cv2.imread(bp)
    hov = cv2.imread(hp)
    if base is None or hov is None:
        print(f"[{tag}] 缺帧")
        continue
    box = diff_bbox(base, hov)
    if box is None:
        print(f"[{tag}] 无 diff")
        continue
    bx, by, bw, bh = box
    region = hov[by:by + bh, bx:bx + bw]
    lines = _ocr(region)
    print("=" * 92)
    print(f"[{tag}] region {region.shape}  共 {len(lines)} 行")
    print(f"{'y':>5}{'h':>5}{'w':>5}{'conf':>7}  {'匹配到的卡名':<18} 原文")
    print("-" * 92)
    for ln in sorted(lines, key=lambda l: l["y"]):
        nm = _match_name(ln["text"]) or ""
        print(f"{ln['y']:>5.0f}{ln['h']:>5.0f}{ln['w']:>5.0f}{ln['conf']:>7.2f}  "
              f"{nm:<18} {ln['text']!r}")
