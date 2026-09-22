"""
hand_edge_ab.py - 只读离线 A/B:**布局条目到底该按什么匹配?**

背景(2026-09-13 第十个会话)
---------------------------
实机日志反复出现"用错张数的那条布局",例子:
    布局「7 张」(左边缘 368,量到 365,7 探针;容差内还有 [9, 8])
而那一帧的手牌是 **6 张**(「6 张」那条的左边缘是 390,差 25px > 容差 22,没进候选)。
探针整体偏约 30px(≈半个卡距)-> 落在两张牌的**分界线**上 -> 有的牌**从来没被探到**。

★ 关键观察:`config/hand_layout.json` 里每条都记了**两个**边缘
  (`left_edge` 和 `right_edge`),而代码只用 `left_edge` 一个:
    1 张 570/735   2 张 536/772   3 张 498/794   4 张 459/826   5 张 421/860
    6 张 390/886   7 张 368/915   8 张 357/925   9 张 358/915
  宽度依次是 165/236/296/367/439/496/547/568/557 —— **1..8 张单调可分**,
  而 8 与 9 张的左边缘只差 1px(§7 第 28 条),**右边缘却差 10px**。
  ⇒ 两个边缘是**同一个张数的两次独立测量**:一条正确的条目必须**同时**解释两边。

本工具就把这件事量出来(不需要人工标注):
  · 老规则(只用左边缘、容差内取最近)选中的那条,右边缘对得上吗?
  · 反过来,按"两边残差之和"选出来的那条是哪条?
  · 两者不一致的帧,人工看一眼(工具会把每条帧的手牌带拼出来)就知道谁对。

⚠️⚠️ **踩过的坑(2026-09-13,别重走)**:`shots/attack_frames` 里那些帧**不是**
  "光标停 SAFE_POINT、扇形未展开"的状态 —— 里面很多帧有牌被悬停/抬起
  (拼图 `shots/hand_edge_ab/bands.png` 里一眼就能看到某张牌比别的大)。
  拿它们去验证"边缘→张数"的几何,会得出**系统性错误**的结论
  (我第一版就这么下了"38/41 帧右边缘对不上"的结论,那是**帧的状态不对**,
  不是判据坏了)。要验证几何,只能用 `turn_engine.DUMP_SCAN_FRAMES` 在
  **扫描前那一刻**存的帧(`shots/scan_frames/`,标签里带 `L…R…`)。

用法:
  .venv\\Scripts\\python.exe dev\\hand_edge_ab.py                       # 默认扫 shots/attack_frames
  .venv\\Scripts\\python.exe dev\\hand_edge_ab.py --glob "shots/hand_live/base.png"
  .venv\\Scripts\\python.exe dev\\hand_edge_ab.py --montage 12          # 顺带拼一张 hand 带图
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
import numpy as np  # noqa: E402

from hand_calibrate import detect_edges  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYOUT_JSON = os.path.join(PROJECT_ROOT, "config", "hand_layout.json")
OUT_DIR = os.path.join(PROJECT_ROOT, "shots", "hand_edge_ab")

# 老规则用的容差(和 hand_scanner_v2.LAYOUT_EDGE_TOL 一致)
EDGE_TOL = 22
# 右边缘的容差:右边缘是"最右那张卡的右边界",实测它比左边缘**稳**
# (左边缘会被扇形最左那张牌的**倾斜**影响)。先按同样的 22 试,数据说话。
RIGHT_TOL = 22


def load_layouts():
    with open(LAYOUT_JSON, "r", encoding="utf-8") as f:
        return json.load(f).get("layouts", {})


def hand_band(frame, y0=596, y1=720):
    return frame[y0:y1, :]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default=os.path.join(PROJECT_ROOT, "shots",
                                                   "attack_frames", "*.png"))
    ap.add_argument("--montage", type=int, default=0,
                    help="拼几张手牌带图(每张一行),便于人眼数张数")
    args = ap.parse_args()

    layouts = load_layouts()
    items = sorted((v for v in layouts.values() if v.get("right_edge")),
                   key=lambda v: v["count"])
    paths = sorted(glob.glob(args.glob))
    if not paths:
        print(f"没有帧:{args.glob}")
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)

    print("布局表(两个边缘都是实测的):")
    for v in items:
        w = v["right_edge"] - v["left_edge"]
        print(f"   {v['count']:>2} 张  left={v['left_edge']:>4} "
              f"right={v['right_edge']:>4}  宽={w:>4}  "
              f"probes={len(v.get('probes') or [])}")

    old_bad = 0
    diff = 0
    rows = []
    for p in paths:
        frame = cv2.imread(p)
        if frame is None:
            continue
        le, re_ = detect_edges(frame)
        if le is None or re_ is None:
            print(f"{os.path.basename(p):<28} 测不到边缘({le},{re_})")
            continue
        # 老规则:左边缘容差内取最近
        cands = [v for v in items if abs(v["left_edge"] - le) <= EDGE_TOL]
        old = min(cands, key=lambda v: abs(v["left_edge"] - le)) if cands else None
        # 新规则:两边残差之和最小(要求两边都进各自的容差)
        both = [v for v in items
                if abs(v["left_edge"] - le) <= EDGE_TOL
                and abs(v["right_edge"] - re_) <= RIGHT_TOL]
        new = min(both, key=lambda v: abs(v["left_edge"] - le)
                  + abs(v["right_edge"] - re_)) if both else None
        rows.append((os.path.basename(p), le, re_, old, new))
        mark = ""
        if old is not None:
            dr = abs(old["right_edge"] - re_)
            if dr > RIGHT_TOL:
                old_bad += 1
                mark = f"  ★老规则选的那条右边缘差 {dr}px"
        if old is not None and new is not None and old["count"] != new["count"]:
            diff += 1
            mark += f"  ★两者不一致:老 {old['count']} 张 vs 新 {new['count']} 张"
        print(f"{os.path.basename(p):<28} 量到 L={le:<4} R={re_:<4} "
              f"宽={re_ - le:<4} | 老->"
              f"{('无候选' if old is None else str(old['count']) + '张'):<6} "
              f"新->{('无' if new is None else str(new['count']) + '张'):<6}{mark}")

    n = len(rows)
    print()
    print(f"共 {n} 帧:老规则选中的条目里,**右边缘对不上(>±{RIGHT_TOL}px)** 的 {old_bad} 帧")
    print(f"        老规则与新规则**给出不同张数**的 {diff} 帧")

    if args.montage:
        sel = rows[:args.montage]
        tiles = []
        for name, le, re_, old, new in sel:
            # 名字里带时间戳,回头按名字找原帧
            src = [p for p in paths if os.path.basename(p) == name]
            if not src:
                continue
            frame = cv2.imread(src[0])
            band = hand_band(frame).copy()
            cv2.line(band, (le, 0), (le, band.shape[0]), (255, 128, 0), 2)
            cv2.line(band, (re_, 0), (re_, band.shape[0]), (0, 0, 255), 2)
            label = (f"{name} L{le}R{re_}|old="
                     f"{'?' if old is None else old['count']}|new="
                     f"{'?' if new is None else new['count']}")
            cv2.putText(band, label, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (255, 255, 255), 1, cv2.LINE_AA)
            tiles.append(band)
        if tiles:
            out = np.vstack(tiles)
            dst = os.path.join(OUT_DIR, "bands.png")
            cv2.imwrite(dst, out)
            print(f"  手牌带拼图 -> {dst}({out.shape[1]}x{out.shape[0]},"
                  f"每行一张帧,人眼数一下张数)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
