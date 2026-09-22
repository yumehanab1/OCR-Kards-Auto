"""edge_probe.py - 只读:手牌扇形两个边缘的**稳定度**探针(2026-09-13 第十个会话)。

为什么要它:布局条目以前只按**左边缘**匹配(`LAYOUT_EDGE_TOL=22`),而
`config/hand_layout.json` 里其实**两个边缘都记了**。这条工具用来回答三件事:

  1. `detect_edges` 在**同一帧**上对"测量带 y"和"背景参考区 x"有多敏感?
     (敏感 = 这条判据本身不牢,拿它做张数判断要小心)
  2. 扇形是不是**居中**的?(布局表里 9 条的 center 是不是同一个值)
     —— 如果居中,那么 `宽 = R - L` 就是"左边缘"的等价测量,但它少了一份
     "偏中心"的误差,而且能把 **8 张 vs 9 张**分开(左边缘只差 1px,右边缘差 10px)。
  3. 拿两个边缘一起挑布局条目,和只按左边缘挑,差在哪几帧上。

用法:
  .venv\\Scripts\\python.exe dev\\edge_probe.py --frame shots/hand_live/base.png
  .venv\\Scripts\\python.exe dev\\edge_probe.py --glob "shots/attack_frames/*.png"
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

import hand_calibrate as hc  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYOUT_JSON = os.path.join(PROJECT_ROOT, "config", "hand_layout.json")

BANDS = [(660, 715), (670, 720), (675, 710), (680, 715), (690, 715), (700, 720)]
BGS = [(40, 120), (150, 250), (250, 330), (900, 1000), (1100, 1200)]


def table():
    with open(LAYOUT_JSON, "r", encoding="utf-8") as f:
        return json.load(f).get("layouts", {})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", default=os.path.join(PROJECT_ROOT, "shots",
                                                    "hand_live", "base.png"))
    ap.add_argument("--glob", default="")
    args = ap.parse_args()

    items = sorted((v for v in table().values() if v.get("right_edge")),
                   key=lambda v: v["count"])
    print("布局表(两个边缘都是实测的;看 center 是不是同一个值):")
    for v in items:
        w = v["right_edge"] - v["left_edge"]
        print(f"   {v['count']:>2} 张  L={v['left_edge']:>4} R={v['right_edge']:>4} "
              f"宽={w:>4}  center={(v['left_edge'] + v['right_edge']) / 2:>6.1f}")
    cs = [(v["left_edge"] + v["right_edge"]) / 2 for v in items]
    print(f"   center 范围 {min(cs):.1f} ~ {max(cs):.1f}(极差 {max(cs) - min(cs):.1f}px)"
          f" -> {'居中成立' if max(cs) - min(cs) <= 20 else '不居中!'}")
    ws = [v["right_edge"] - v["left_edge"] for v in items]
    print(f"   宽度的相邻间隔:{[ws[i+1] - ws[i] for i in range(len(ws) - 1)]}"
          f"(**最小间隔**决定了宽度能把张数分到多细)")

    paths = sorted(glob.glob(args.glob)) if args.glob else [args.frame]
    for p in paths:
        frame = cv2.imread(p)
        if frame is None:
            print(f"{p}: 读不到")
            continue
        print(f"\n=== {os.path.basename(p)} ===")
        y0, y1, bx = hc.EDGE_Y0, hc.EDGE_Y1, hc.BG_SAMPLE
        try:
            print(f"  默认(带 y{y0}-{y1} / 背景 x{bx[0]}-{bx[1]}): "
                  f"L={hc.detect_left_edge(frame)} R={hc.detect_right_edge(frame)}")
            print(f"    被跳过的窄区段(装饰):{getattr(hc.detect_left_edge, 'skipped', None)}")
            print("  换测量带:")
            for b in BANDS:
                hc.EDGE_Y0, hc.EDGE_Y1 = b
                print(f"    y{b[0]}-{b[1]}: L={hc.detect_left_edge(frame)} "
                      f"R={hc.detect_right_edge(frame)}")
            hc.EDGE_Y0, hc.EDGE_Y1 = y0, y1
            print("  换背景参考区:")
            for g in BGS:
                hc.BG_SAMPLE = g
                print(f"    x{g[0]}-{g[1]}: L={hc.detect_left_edge(frame)} "
                      f"R={hc.detect_right_edge(frame)}")
            hc.BG_SAMPLE = bx
            le, re_ = hc.detect_edges(frame)
            if le is not None and re_ is not None:
                print(f"  两个边缘一起挑:")
                scored = sorted(
                    ((abs(v['left_edge'] - le) + abs(v['right_edge'] - re_),
                      abs(v['left_edge'] - le), abs(v['right_edge'] - re_), v)
                     for v in items))
                for s, dl, dr, v in scored[:3]:
                    print(f"    {v['count']:>2} 张  残差 L{dl:>3} R{dr:>3}  和{s:>3}")
        finally:
            hc.EDGE_Y0, hc.EDGE_Y1, hc.BG_SAMPLE = y0, y1, bx
    return 0


if __name__ == "__main__":
    sys.exit(main())
