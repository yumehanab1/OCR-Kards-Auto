"""scan_frame_check.py - 只读:拿"扫描前那一帧"(shots/scan_frames)核对两个边缘。

为什么必须用这批帧:`shots/attack_frames` 里很多帧有牌被悬停/抬起,扇形几何和
"扫描时(光标停 SAFE_POINT、扇形未展开)"**不是一回事** —— 拿它验证几何会得出
错误的结论(2026-09-13 我自己就先错过一次)。

做法:把日志里 `布局「N 张」(…量到 L…/R…)` 那几行的 (L,R) 按时间配到
`shots/scan_frames/*.png` 上,在**手牌那一条**画两条竖线(蓝=量到的左边缘,
红=量到的右边缘)+ 布局表里各条应有的边界,然后拼成一张图。
人眼一次就能看出:**量到的 R 是不是落在最右那张牌的右边界上**。

用法:
  .venv\\Scripts\\python.exe src\\scan_frame_check.py
  .venv\\Scripts\\python.exe src\\scan_frame_check.py --out shots/scan_frames/_check.png
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(PROJECT_ROOT, "logs", "main_loop.log")
SCAN_DIR = os.path.join(PROJECT_ROOT, "shots", "scan_frames")
LAYOUT_JSON = os.path.join(PROJECT_ROOT, "config", "hand_layout.json")

LINE_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) .*布局「(\d+) 张」"
                     r".*量到 L(\d+)/R(\d+).*残差 L([\dN]+)/R([\dN]+)")
BAND_Y = (596, 720)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(SCAN_DIR, "_check.png"))
    ap.add_argument("--scale", type=float, default=1.0)
    args = ap.parse_args()

    with open(LAYOUT_JSON, "r", encoding="utf-8") as f:
        items = sorted((v for v in json.load(f)["layouts"].values()
                        if v.get("right_edge")), key=lambda v: v["count"])

    picks = []
    for ln in open(LOG, encoding="utf-8"):
        m = LINE_RE.match(ln.strip())
        if m:
            picks.append((m.group(1), int(m.group(2)), int(m.group(3)),
                          int(m.group(4)), m.group(5), m.group(6)))
    if not picks:
        print("日志里没有「布局…量到 L…/R…」的行(先跑一局带新日志的实机)")
        return 1
    # 只取最后一段 main_loop(和别的工具一个规矩)
    starts = [i for i, ln in enumerate(open(LOG, encoding="utf-8"))
              if "main_loop start" in ln]
    print(f"日志里带 L/R 的布局行 {len(picks)} 条,最后一段从第 {starts[-1] + 1} 行起")

    frames = sorted(glob.glob(os.path.join(SCAN_DIR, "*.png")))
    frames = [p for p in frames
              if os.path.getsize(p) > 200_000 and "_check" not in p]
    print(f"可用的扫描帧 {len(frames)} 张")
    if not frames:
        print("没有可用的扫描帧(窗口没被盖住时才有真图)")
        return 1

    print(f"\n{'帧':<24}{'选':>4}{'量到 L':>8}{'量到 R':>8}{'宽':>6}"
          f"{'选中残差 L/R':>14}   各条布局的宽度")
    tiles = []
    for p in frames:
        # 文件名形如 0913_182039_scan.png -> "MMDD_HHMMSS_..."(下划线在 4 和 11)
        ts = os.path.basename(p)[:11]            # 0913_182039
        hhmmss = ts[5:11]                        # "182039"
        cand = [q for q in picks if q[0][11:13] + q[0][14:16] + q[0][17:19]
                >= hhmmss]
        if not cand:
            continue
        t, cnt, L, R, rl, rr = cand[0]
        frame = cv2.imread(p)
        if frame is None:
            continue
        band = frame[BAND_Y[0]:BAND_Y[1], :].copy()
        for v in items:
            x = v["left_edge"]
            if abs(v["count"] - cnt) <= 1:
                cv2.line(band, (x, 0), (x, band.shape[0]), (60, 60, 60), 1)
            xr = v["right_edge"]
            if abs(v["count"] - cnt) <= 1:
                cv2.line(band, (xr, 0), (xr, band.shape[0]), (60, 60, 60), 1)
        cv2.line(band, (L, 0), (L, band.shape[0]), (255, 128, 0), 2)
        cv2.line(band, (R, 0), (R, band.shape[0]), (0, 0, 255), 2)
        cv2.putText(band, f"{ts} chose {cnt} cards | measured L{L} R{R} "
                          f"(w{R - L}) | table: 6cards 390/886 5cards 421/860",
                    (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (255, 255, 255), 1, cv2.LINE_AA)
        if args.scale != 1.0:
            band = cv2.resize(band, None, fx=args.scale, fy=args.scale)
        tiles.append(band)
        w = R - L
        print(f"{ts:<24}{cnt:>4}{L:>8}{R:>8}{w:>6}{rl + '/' + rr:>14}   "
              f"6张宽496 7张宽547")

    if tiles:
        w = max(t.shape[1] for t in tiles)
        tiles = [cv2.copyMakeBorder(t, 0, 2, 0, max(0, w - t.shape[1]),
                                    cv2.BORDER_CONSTANT, value=(255, 255, 255))
                 for t in tiles]
        out = np.vstack(tiles)
        cv2.imwrite(args.out, out)
        print(f"\n核对图 -> {args.out}({out.shape[1]}x{out.shape[0]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
