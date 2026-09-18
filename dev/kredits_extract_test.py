"""
kredits_extract_test.py - 离线验证 Kredits 数字提取(不需要游戏)。

对 shots/kredits/ 下的整窗口截图(以及 plate_*.png 局部图)跑一遍
kredits.isolate_numeral,打印提取到的字形尺寸/宽高比,并把结果存到
shots/kredits/extracted/,方便直接看图确认提取对不对。

用法:
  .venv\\Scripts\\python.exe src\\kredits_extract_test.py
  .venv\\Scripts\\python.exe src\\kredits_extract_test.py --file shots/live_probe.png
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np

from kredits import OPPONENT_BOX, OURS_BOX, isolate_numeral

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "shots", "kredits", "extracted")


def plate_of(frame, box):
    x1, y1, x2, y2 = box
    return frame[y1:y2, x1:x2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="", help="单个整窗口截图")
    ap.add_argument("--box", choices=["ours", "opponent"], default="ours")
    ap.add_argument("--dir", default=os.path.join(ROOT, "shots"))
    args = ap.parse_args()

    box = OURS_BOX if args.box == "ours" else OPPONENT_BOX
    os.makedirs(OUT, exist_ok=True)

    if args.file:
        files = [args.file]
    else:
        files = [p for p in
                 sorted(glob.glob(os.path.join(args.dir, "*.png")))
                 + sorted(glob.glob(os.path.join(args.dir, "**", "*.png"),
                                    recursive=True))
                 if os.path.basename(p) not in ()
                 and "kredits" not in p.lower()]

    print(f"数字区 {box}({'我方' if args.box == 'ours' else '对手'})")
    print(f"{'文件':<46}{'字形尺寸':<12}{'宽高比':<9}{'bbox':<22}")
    print("-" * 92)

    ok = 0
    for i, p in enumerate(files):
        frame = cv2.imread(p)
        if frame is None or frame.shape[0] < 300 or frame.shape[1] < 400:
            continue
        if frame.shape[1] != 1280 or frame.shape[0] != 720:
            print(f"{os.path.relpath(p, ROOT):<46}尺寸 {frame.shape[1]}x{frame.shape[0]} 跳过")
            continue
        numeral, mask, bb = isolate_numeral(frame, box)
        name = os.path.relpath(p, ROOT)
        if numeral is None:
            print(f"{name:<46}{'未提取到':<12}")
            continue
        h, w = numeral.shape[:2]
        print(f"{name:<46}{f'{w}x{h}':<12}{w / h:<9.2f}{str(bb):<22}")
        stem = f"{args.box}_{i:03d}"
        cv2.imwrite(os.path.join(OUT, f"{stem}.png"), numeral)
        cv2.imwrite(os.path.join(OUT, f"{stem}_plate.png"), plate_of(frame, box))
        ok += 1

    print("-" * 92)
    print(f"共提取 {ok} 个字形,已存到 {OUT}")
    print("注意:整窗口截图若是不同对局/不同时刻,字形顺序不代表费用值;")
    print("      要看值请结合 shots/kredits/samples 里按出现顺序录的样例。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
