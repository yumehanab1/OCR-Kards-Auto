"""
badge_tile_probe.py - 把真实帧里检出的**费用徽章**切成小图拼起来,人眼核对。

为什么要这个工具(2026-09-11 晚):
    徽章"是橙还是灰"决定了 bot 敢不敢攻击,而这个判据是"徽章里数字像素的
    平均饱和度 S"。如果**徽章底色本身是高饱和的深棕**(金边卡上就有),
    那底色像素会被当成"数字像素",S 均值直接被拉到 140 上下 ——
    一个**已经行动过的灰数字**会被判成"能行动"(橙色),这正是
    §10 说的"把不能行动的牌拖出去"的来源。
    光看日志里的 S 值分不出"真的橙"和"底色是棕",必须**看图**。

用法:
  .venv\\Scripts\\python.exe dev\\badge_tile_probe.py --set board
  .venv\\Scripts\\python.exe dev\\badge_tile_probe.py --set all --state orange
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

import unit_state as us  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SETS = {
    "board": ("shots/board_samples", "0911_122530_00*.png"),
    "deploy": ("shots/deploy_probe", "f0*.png"),
    "attack": ("shots/attack_probe", "*.png"),
}
BAD = ("_mask", "_annot", "_field", "_anchor")


def files_for(name, limit=0):
    if name == "all":
        out = []
        for k in SETS:
            out += files_for(k, limit)
        return out
    d, pat = SETS[name]
    fs = sorted(glob.glob(os.path.join(ROOT, d, pat)))
    fs = [f for f in fs if not any(s in f for s in BAD)]
    return fs[:limit] if limit else fs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="all", choices=sorted(SETS) + ["all"])
    ap.add_argument("--state", default="all",
                    choices=["all", "orange", "grey", "unknown"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cols", type=int, default=10)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    files = files_for(args.set, args.limit)
    if not files:
        print("没有帧")
        return 1

    tiles = []
    info = []
    for f in files:
        img = cv2.imread(f)
        if img is None:
            continue
        for b in us.find_cost_badges(img):
            st = b["state"] or "unknown"
            if args.state != "all" and st != args.state:
                continue
            x, y, w, h = b["x"], b["y"], b["w"], b["h"]
            x0, y0 = max(0, x - 12), max(0, y - 12)
            crop = img[y0:y + h + 12, x0:x + w + 12].copy()
            if crop.size == 0:
                continue
            crop = cv2.resize(crop, (160, 160), interpolation=cv2.INTER_NEAREST)
            cv2.putText(crop, f"S{b['digit_s']:.0f} n{b['digit_n']}",
                        (3, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                        (255, 255, 255), 1)
            cv2.putText(crop, f"{st[:3]} {os.path.basename(f)[:14]}",
                        (3, 155), cv2.FONT_HERSHEY_SIMPLEX, 0.38,
                        (0, 255, 255), 1)
            tiles.append(crop)
            info.append((os.path.basename(f), b))

    print(f"{len(tiles)} 个徽章({args.state})")
    for name, b in info:
        print(f"  {name:32s} x{b['x']:4d} y{b['y']:4d} {b['w']}x{b['h']} "
              f"S={b['digit_s']:6.1f} V={b['digit_v']:5.1f} n={b['digit_n']:3d} "
              f"-> {b['state']}")

    if tiles:
        cols = args.cols
        rows = []
        for i in range(0, len(tiles), cols):
            chunk = tiles[i:i + cols]
            while len(chunk) < cols:
                chunk.append(np.zeros((160, 160, 3), np.uint8))
            rows.append(np.hstack(chunk))
        out = args.out or os.path.join(ROOT, "shots", "badge_tiles.png")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cv2.imwrite(out, np.vstack(rows))
        print(f"拼图 -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
