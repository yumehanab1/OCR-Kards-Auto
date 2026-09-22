"""
fix_bands.py - 标定四条战线的 y 带(只读)。

为什么要它
----------
`board.py` 里的四条行带 (`OUR_SUPPORT_BAND` 等)必须
  a) 对准真实的行位置
  b) **互不重叠**
因为卡数统计是"行带里有多少张卡",带子一重叠,同一张卡就被两条线各算一次,
卡数直接虚高一倍(实测踩过:支撑带与敌方前线带重叠了 60px)。

怎么标
------
1. 在整帧上找"卡面"(比局部最暗桌面亮、且不带桌面绿色调)
2. 取连通域的长方形,记下它们的 y 范围
3. 把所有帧的 **卡中心 y** 聚成若干簇 -> 每一簇就是一条战线
4. 打印簇中心和簇内 y 范围,给出建议的行带(取簇的中间 35px,保证不重叠)

用法:
  .venv\\Scripts\\python.exe dev\\fix_bands.py                      # 用 shots/ 下的样本帧
  .venv\\Scripts\\python.exe dev\\fix_bands.py --dir shots\\turn_pairs
  .venv\\Scripts\\python.exe dev\\fix_bands.py --frame shots\\x.png
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BOARD_Y0, BOARD_Y1 = 80, 620
BOARD_X0, BOARD_X1 = 120, 1160
LOCAL_BLOCK = 41
CARD_MIN_CONTRAST = 55
MIN_CARD_W, MAX_CARD_W = 60, 175
MIN_CARD_H, MAX_CARD_H = 80, 185
MIN_FILL = 0.5

DEFAULT_FRAMES = [
    "shots/deploy_probe/f041.png",
    "shots/live/ingame_now.png",
    "shots/diff_base.png",
    "shots/turn_pairs/20260911_010816_turn001_start.png",
    "shots/turn_pairs/20260911_010816_turn002_end.png",
]


def card_boxes(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    local = cv2.erode(gray, np.ones((LOCAL_BLOCK, LOCAL_BLOCK), np.uint8))
    bright = ((gray.astype(np.int16) - local.astype(np.int16))
              > CARD_MIN_CONTRAST).astype(np.uint8) * 255
    bright[:BOARD_Y0, :] = 0
    bright[BOARD_Y1:, :] = 0
    bright[:, :BOARD_X0] = 0
    bright[:, BOARD_X1:] = 0
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((13, 13), np.uint8))
    n, _lab, st, _ = cv2.connectedComponentsWithStats(bright, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = (int(st[i, 0]), int(st[i, 1]), int(st[i, 2]),
                         int(st[i, 3]), int(st[i, 4]))
        if not (MIN_CARD_W <= w <= MAX_CARD_W):
            continue
        if not (MIN_CARD_H <= h <= MAX_CARD_H):
            continue
        if a / float(w * h) < MIN_FILL:
            continue
        out.append({"x": x, "y": y, "w": w, "h": h,
                    "cx": x + w // 2, "cy": y + h // 2})
    return out


def cluster(values, gap=45):
    """把 y 值聚成簇(相邻差距 > gap 就断开)。"""
    vals = sorted(values)
    clusters, cur = [], [vals[0]] if vals else []
    for v in vals[1:]:
        if v - cur[-1] > gap:
            clusters.append(cur)
            cur = [v]
        else:
            cur.append(v)
    if cur:
        clusters.append(cur)
    return clusters


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=None, help="扫这个目录下的 png")
    ap.add_argument("--frame", default=None)
    args = ap.parse_args()

    if args.frame:
        frames = [args.frame]
    elif args.dir:
        frames = sorted(glob.glob(os.path.join(args.dir, "*.png")))
        frames = [f for f in frames if not f.endswith("_ann.png")]
    else:
        frames = [os.path.join(ROOT, p) for p in DEFAULT_FRAMES]

    all_y, per_frame = [], []
    for p in frames:
        img = cv2.imread(p)
        if img is None:
            continue
        boxes = card_boxes(img)
        ys = [b["cy"] for b in boxes]
        all_y.extend(ys)
        per_frame.append((os.path.basename(p), ys))
        print(f"{os.path.basename(p):<46} 检出 {len(boxes)} 张  "
              f"中心 y: {sorted(ys)}")

    if not all_y:
        print("\n没检出任何卡 —— 判据需要重新调(见 fix_bands.py 顶部参数)。")
        return 1

    print()
    print("=" * 90)
    print("卡中心 y 的聚类(= 各条战线):")
    clusters = cluster(all_y)
    for i, cl in enumerate(clusters):
        c = np.array(cl)
        print(f"  簇{i}: 中心 y≈{int(c.mean()):>4}  "
              f"范围 {c.min():>4}~{c.max():>4}  样本 {len(cl):>3} 个")
    print()
    print("建议行带(每条取中心 ±18px,保证互不重叠):")
    bands = []
    for i, cl in enumerate(clusters):
        c = int(np.array(cl).mean())
        bands.append((c - 18, c + 18, c))
        print(f"  簇{i}: y {c - 18}~{c + 18}   (中心 {c})")
    print()
    print("对照 board.py 现有的行带:")
    import board
    for name in ("ENEMY_HQ_BAND", "ENEMY_SUPPORT_BAND", "OUR_SUPPORT_BAND",
                 "OUR_FRONT_BAND", "ENEMY_FRONT_BAND"):
        print(f"  {name:<20} {getattr(board, name)}")
    print()
    print("⚠️ 上面只是「按检出卡的 y 聚类」的建议值。**必须逐帧配合放大图人工核对**,")
    print("   因为:①地形装饰也会被检出成卡 ②同一条线上几张卡的 y 略有不同。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
