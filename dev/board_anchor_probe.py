"""
board_anchor_probe.py - 离线对比两种"场上卡定位"锚点(不需要游戏)。

背景(§12 交给下个会话的问题清单 第 1 条)
------------------------------------------
`board.card_boxes()` 靠**亮度/饱和度掩码 + 形态学**找卡矩形,实测会
**漏卡和粘连**(实机:"我方那一行 5 张只检出 1~2 张"),而
`battlefield_snapshot()`(部署成功判据)还在用它数卡 -> 判据可能仍不可靠。

而 `unit_state.find_cost_badges()` 直接找**费用徽章**(每张单位卡左上角的
深色小方块 + 亮色数字),它是独立小方块,不会被相邻卡粘连吞掉,
实机已验证比卡框可靠。

这个脚本就是**离线把两种锚点摆在一起看**,回答三个问题:
  1. 两种锚点各数出几行、每行几张?
  2. 差值出现在哪(缺哪一张、还是多检了)?
  3. 徽章锚点会不会漏(什么情况下漏)?

用法:
  .venv\\Scripts\\python.exe dev\\board_anchor_probe.py --set attack
  .venv\\Scripts\\python.exe dev\\board_anchor_probe.py --set board --shots
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
import numpy as np  # noqa: E402

import board  # noqa: E402
import unit_state  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SETS = {
    "attack": ("shots/attack_probe", "*_probe.png"),
    "attack_all": ("shots/attack_probe", "*.png"),
    "board": ("shots/board_samples", "*.png"),
    "deploy": ("shots/deploy_probe", "f0*.png"),
}


def files_for(name):
    d, pat = SETS[name]
    fs = sorted(glob.glob(os.path.join(ROOT, d, pat)))
    return [f for f in fs if "_mask" not in f and "_annot" not in f
            and "_field" not in f and "_anchor" not in f]


def cluster_badges(badges, min_gap=60):
    """把徽章按 y 聚成行(和 rows_from_boxes 同一套逻辑,但锚点是徽章)。"""
    rows = []
    for b in sorted(badges, key=lambda b: b["cy"]):
        hit = None
        for r in rows:
            if abs(r["cy"] - b["cy"]) <= min_gap:
                hit = r
                break
        if hit is None:
            rows.append({"cy": float(b["cy"]), "items": [b]})
        else:
            hit["items"].append(b)
            hit["cy"] = sum(x["cy"] for x in hit["items"]) / len(hit["items"])
    rows.sort(key=lambda r: r["cy"])
    for r in rows:
        r["items"].sort(key=lambda b: b["cx"])
        r["n"] = len(r["items"])
    return rows


def annotate(frame, boxes, rows_b, path):
    out = frame.copy()
    for b in boxes:                       # 卡框 = 蓝
        cv2.rectangle(out, (b["x"], b["y"]), (b["x"] + b["w"], b["y"] + b["h"]),
                      (255, 0, 0), 2)
        cv2.putText(out, "box", (b["x"], b["y"] + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)
    for r in rows_b:                      # 徽章 = 绿
        for b in r["items"]:
            cv2.rectangle(out, (b["x"] - 2, b["y"] - 2),
                          (b["x"] + b["w"] + 2, b["y"] + b["h"] + 2),
                          (0, 255, 0), 2)
            cv2.putText(out, f"{b['state'] or '?'}", (b["x"], b["y"] - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        cv2.putText(out, f"badgeRow cy{r['cy']:.0f} n={r['n']}",
                    (12, int(r["cy"])), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 255, 0), 1)
    # 徽章检测的范围上限(手牌分界),画出来便于判断"是不是被这个上限截掉了"
    cv2.line(out, (0, unit_state.BOARD_BADGE_MAX_Y),
             (out.shape[1], unit_state.BOARD_BADGE_MAX_Y), (0, 165, 255), 1)
    cv2.putText(out, f"BADGE_MAX_Y={unit_state.BOARD_BADGE_MAX_Y}",
                (12, unit_state.BOARD_BADGE_MAX_Y - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
    cv2.imwrite(path, out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="attack", choices=sorted(SETS))
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--shots", action="store_true", help="存对比标注图")
    ap.add_argument("--badge-max-y", type=int, default=None,
                    help="临时改徽章检测的 y 上限(试参数用)")
    ap.add_argument("--badge-w-max", type=int, default=None,
                    help="临时改徽章的宽度上限(实测有徽章粘到深色卡边 -> 29px)")
    args = ap.parse_args()

    if args.badge_max_y is not None:
        unit_state.BOARD_BADGE_MAX_Y = args.badge_max_y
        print(f"(临时把 BOARD_BADGE_MAX_Y 改成 {args.badge_max_y})")
    if args.badge_w_max is not None:
        unit_state.BADGE_W_MAX = args.badge_w_max
        print(f"(临时把 BADGE_W_MAX 改成 {args.badge_w_max})")

    files = files_for(args.set)
    if args.max:
        files = files[:args.max]
    if not files:
        print("没有帧")
        return 1
    print(f"{args.set}: {len(files)} 帧\n")

    outdir = os.path.join(ROOT, "shots", "anchor_check")
    if args.shots:
        os.makedirs(outdir, exist_ok=True)

    tot_box = tot_badge = tot_merge = 0
    worst = []
    for fp in files:
        img = cv2.imread(fp)
        if img is None:
            continue
        name = os.path.basename(fp)
        boxes = board.card_boxes(img)
        rows_cb = board.rows_from_boxes(boxes)
        badges = unit_state.find_cost_badges(img)
        rows_bd = cluster_badges(badges)
        tot_box += len(boxes)
        tot_badge += len(badges)
        print(f"=== {name} ===")
        print(f"    卡框: {len(rows_cb)} 行 / {len(boxes)} 张   "
              + " | ".join(f"cy{r['cy']:.0f} n={r['n']} "
                           f"x={[b['cx'] for b in r['boxes']]}" for r in rows_cb))
        print(f"    徽章: {len(rows_bd)} 行 / {len(badges)} 个  "
              + " | ".join(f"cy{r['cy']:.0f} n={r['n']} "
                           f"x={[b['cx'] for b in r['items']]}" for r in rows_bd))
        mg = board.merged_card_boxes(img)
        rows_mg = board.rows_from_boxes(mg)
        tot_merge += len(mg)
        print(f"    合并: {len(rows_mg)} 行 / {len(mg)} 张   "
              + " | ".join(f"cy{r['cy']:.0f} n={r['n']} "
                           f"x={[(b['cx'], b.get('from')) for b in r['boxes']]}"
                           for r in rows_mg))
        if rows_cb and rows_bd:
            bd_last = rows_bd[-1]
            cb_last = rows_cb[-1]
            if bd_last["n"] > cb_last["n"]:
                worst.append((name, cb_last["n"], bd_last["n"]))
        if args.shots:
            annotate(img, boxes, rows_bd,
                     os.path.join(outdir, name.replace(".png", "_anchor.png")))
    print(f"\n合计: 卡框 {tot_box} 张 / 徽章 {tot_badge} 个 / 合并 {tot_merge} 张")
    if worst:
        print("徽章比卡框多检出(说明卡框漏卡)的帧:")
        for n, a, b in worst:
            print(f"    {n}: 卡框最下面一行 {a} 张 -> 徽章 {b} 个")
    if args.shots:
        print(f"对比图 -> {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
