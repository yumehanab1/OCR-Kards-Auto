"""
badge_s_calib.py - 标定"费用数字 橙/灰"的饱和度阈值(离线,看图用)。

背景(2026-09-11 晚):
    换了"被暗包住的亮块"这套数字判据之后,阈值必须**在新判据上重新量一遍** ——
    判据一变,数字像素的集合就变了,旧阈值(在旧集合上标定的)不再成立。

做法:把真实帧上检出的**每一个徽章**按 `digit_s` 分档,每一档拼一张小图,
      人眼确认"这一档到底是橙还是灰",再在两个峰之间的**空隙**里取阈值。

★ 这一步不能省:图像判据的最后一步永远是**看图**,不是看直方图
  (§7 第 59 条:滑窗版就是"合成用例 13/13 全绿、真实帧上是灾难")。

用法:
  .venv\\Scripts\\python.exe src\\badge_s_calib.py --set all --out shots\\badge_s_calib
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

BANDS = [(0, 60), (60, 90), (90, 105), (105, 130), (130, 175), (175, 240)]
BAD = ("_mask", "_annot", "_field", "_anchor")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "shots", "badge_s_calib"))
    ap.add_argument("--set", default="board+deploy+attack")
    ap.add_argument("--cols", type=int, default=12)
    args = ap.parse_args()

    files = []
    if "board" in args.set:
        files += sorted(glob.glob(os.path.join(ROOT, "shots", "board_samples",
                                               "0911_122530_00*.png")))
    if "deploy" in args.set:
        files += sorted(glob.glob(os.path.join(ROOT, "shots", "deploy_probe",
                                               "f0*.png")))
    if "attack" in args.set:
        files += sorted(glob.glob(os.path.join(ROOT, "shots", "attack_probe",
                                               "*.png")))
    files = [f for f in files if not any(s in f for s in BAD)]

    os.makedirs(args.out, exist_ok=True)
    buckets = {b: [] for b in BANDS}
    n_all = 0
    for f in files:
        img = cv2.imread(f)
        if img is None:
            continue
        for b in us.find_cost_badges(img):
            s = b["digit_s"]
            n_all += 1
            for lo, hi in BANDS:
                if lo <= s < hi:
                    x, y, w, h = b["x"], b["y"], b["w"], b["h"]
                    crop = img[max(0, y - 10):y + h + 10,
                               max(0, x - 10):x + w + 10].copy()
                    if crop.size == 0:
                        break
                    crop = cv2.resize(crop, (150, 150),
                                      interpolation=cv2.INTER_NEAREST)
                    cv2.putText(crop, f"S{s:.0f}", (3, 14),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
                    buckets[(lo, hi)].append(crop)
                    break

    print(f"{len(files)} 帧 / {n_all} 个徽章")
    for (lo, hi), tiles in buckets.items():
        print(f"  S {lo:3d}-{hi:3d}: {len(tiles):4d} 个")
        if not tiles:
            continue
        rows = []
        for i in range(0, len(tiles), args.cols):
            chunk = tiles[i:i + args.cols]
            while len(chunk) < args.cols:
                chunk.append(np.zeros((150, 150, 3), np.uint8))
            rows.append(np.hstack(chunk))
        p = os.path.join(args.out, f"s_{lo:03d}_{hi:03d}.png")
        cv2.imwrite(p, np.vstack(rows))
        print(f"      -> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
