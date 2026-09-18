"""
drop_check.py - **离线**核对"部署落点候选"落在哪里(不需要游戏)。

背景(2026-09-11 下午,用户实机确认):
  拖到**已有卡的位置**上松手 = 牌**回手**,而游戏**不会**自动吸附到邻近空位。
  所以落点必须是空槽位;`deploy.deploy_candidates()` 就是按"我方那一行里
  已占位的 x + 实测间距(143px)"现算空档的。

这个脚本把真实帧的"我方那一行"和候选落点摆在一起:
    行 cy / 已占位的 x / 候选落点 x / 每个候选离最近的卡有多远
人眼一看就知道"会不会又砸在卡上"。这是**开实机之前**唯一能做的验证。

用法:
  .venv\\Scripts\\python.exe src\\drop_check.py
  .venv\\Scripts\\python.exe src\\drop_check.py --set deploy --limit 8
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

import board  # noqa: E402
import deploy  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SETS = {
    "board": "shots/board_samples/0911_122530_00*.png",
    "deploy": "shots/deploy_probe/f0*.png",
    "attack": "shots/attack_probe/*.png",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="board", choices=sorted(SETS))
    ap.add_argument("--limit", type=int, default=6)
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(ROOT, SETS[args.set])))
    # ★ 先过滤再限量:上一版先取前 N 个再过滤,结果前 6 个里一半是 _mask/_annot,
    #   真正看过的帧只有 2 张(看着像"只有 2 帧",其实是脚本自己的顺序问题)。
    files = [f for f in files if "_mask" not in f and "_annot" not in f
             and "_field" not in f]
    files = files[:args.limit]
    print(f"{args.set}: {len(files)} 帧   槽位间距 SLOT_PITCH={deploy.SLOT_PITCH} "
          f"重试上限={deploy.MAX_SLOT_TRIES}")
    for f in files:
        img = cv2.imread(f)
        if img is None:
            continue
        field = board.read_field(img)
        cands = deploy.deploy_candidates(field)
        row = deploy.our_row(field)
        if row is None:
            print(f"{os.path.basename(f):28s} 读不到我方那一行 -> y 用兜底 "
                  f"{cands[0][1]}")
            continue
        occ = sorted(int(u["cx"]) for u in row["units"])
        print(f"{os.path.basename(f):28s} 行cy={int(row['cy'])} "
              f"已占位x={occ}")
        for x, y in cands[:3]:
            gap = min((abs(x - o) for o in occ), default=None)
            flag = ""
            if gap is not None and gap < deploy.SLOT_PITCH * 0.75:
                flag = f"  ⚠️离最近的卡只有 {gap}px(可能又砸在卡上)"
            print(f"      候选 ({x},{y})" + (f"  离最近卡 {gap}px{flag}"
                                            if gap is not None else "  (那一行没有卡)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
