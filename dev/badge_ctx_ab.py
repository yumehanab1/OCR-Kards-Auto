"""
badge_ctx_ab.py - 离线 A/B:**行带补检的"亮卡面"判据**,只看右边 vs 看上/右/下任一方向。

为什么要做这个 A/B(而不是直接改)
----------------------------------
`find_cost_badges_band` 里那条"徽章右边必须是亮卡面"的判据,假设是
"徽章挂在卡的**浅色**顶边上"。实机抓到的反例(`shots/attack_frames/0912_032521_attack.png`,
我方支援线):那张战斗机卡的顶栏是**深橄榄绿**,徽章右边紧挨着深色标题栏 ->
被"上下文不亮"判掉 -> **我方单位整类检不出徽章**。

★ 但按 §7 第 59/67 条那条纪律:**换判据绝不能只看总数**。
  放宽"亮卡面"这一条,既可能**多收**(卡面美术/文字/悬停面板成片变亮),也可能
  同时**丢掉**(不会),所以必须把"新收进来的"和"新丢掉的"分别切出来**看图**。
  滑窗版当年就是"合成用例 13/13 全绿、真实帧 44~68 个假徽章"翻的车。

输出
----
  · 逐帧数量对比(旧判据 vs 新判据);
  · `shots/badge_ctx_ab/new_only_*.png` —— **只有新判据收到**的徽章(必须逐个看);
  · `shots/badge_ctx_ab/old_only_*.png` —— **只有旧判据收到**的(理论上应为 0);
  · 汇总里给出总数与"净增/净减"。

用法
----
  .venv\\Scripts\\python.exe dev\\badge_ctx_ab.py
  .venv\\Scripts\\python.exe dev\\badge_ctx_ab.py --dir shots\\attack_frames
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import board  # noqa: E402
import unit_state  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "shots", "badge_ctx_ab")

DEFAULT_DIRS = ["shots/attack_frames", "shots/board_samples", "shots/turn_pairs",
                "shots/deploy_probe"]


def frames_from(dirs):
    out = []
    for d in dirs:
        p = os.path.join(ROOT, d)
        for f in sorted(glob.glob(os.path.join(p, "*.png"))):
            n = os.path.basename(f)
            if "_ann" in n or "_annot" in n or "_mask" in n:
                continue
            out.append(f)
    return out


def tile(badges_imgs, labels, cols=8, size=64):
    if not badges_imgs:
        return None
    rows = []
    for i in range(0, len(badges_imgs), cols):
        chunk = badges_imgs[i:i + cols]
        lab = labels[i:i + cols]
        tiles = []
        for im, lab_txt in zip(chunk, lab):
            thumb = cv2.resize(im, (size, size), interpolation=cv2.INTER_NEAREST)
            bar = np.zeros((14, size, 3), np.uint8)
            cv2.putText(bar, str(lab_txt)[:18], (2, 11), cv2.FONT_HERSHEY_SIMPLEX,
                        0.32, (0, 255, 255), 1)
            tiles.append(np.vstack([bar, thumb]))
        while len(tiles) < cols:
            tiles.append(np.zeros_like(tiles[0]))
        rows.append(np.hstack(tiles))
    return np.vstack(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="行带补检的亮卡面判据 A/B")
    ap.add_argument("--dirs", default="", help="逗号分隔;默认几个 shots 子目录")
    ap.add_argument("--max-frames", type=int, default=0, help="0=全部")
    args = ap.parse_args()
    dirs = [d.strip() for d in args.dirs.split(",") if d.strip()] or DEFAULT_DIRS
    files = frames_from(dirs)
    if args.max_frames:
        files = files[:args.max_frames]
    if not files:
        print("没有找到帧")
        return 2
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"帧数 {len(files)}  目录 {dirs}")

    n_old = n_new = 0
    new_imgs, new_labs = [], []
    old_imgs, old_labs = [], []
    per_frame = []
    for f in files:
        im = cv2.imread(f)
        if im is None:
            continue
        rows = board.rows_from_boxes(board.card_boxes(im))
        old = unit_state.find_cost_badges_band(im, rows, context_any=False)
        new = unit_state.find_cost_badges_band(im, rows, context_any=True)
        n_old += len(old)
        n_new += len(new)

        def key(b):
            return (round(b["y"] / 8), round(b["x"] / 8))

        ko = {key(b) for b in old}
        kn = {key(b) for b in new}
        name = os.path.basename(f)
        for b in new:
            if key(b) not in ko:
                y, x = int(b["y"]), int(b["x"])
                new_imgs.append(im[max(0, y - 14):y + 32, max(0, x - 14):x + 32].copy())
                new_labs.append(f"{name[:10]} S{b['digit_s']:.0f}")
        for b in old:
            if key(b) not in kn:
                y, x = int(b["y"]), int(b["x"])
                old_imgs.append(im[max(0, y - 14):y + 32, max(0, x - 14):x + 32].copy())
                old_labs.append(f"{name[:10]} S{b['digit_s']:.0f}")
        per_frame.append((name, len(old), len(new)))

    print(f"\n{'frame':<34}{'旧(只看右)':>10}{'新(上右下)':>12}")
    for name, a, b in per_frame:
        mark = "   <<<" if b != a else ""
        print(f"{name:<34}{a:>10}{b:>12}{mark}")
    print(f"\n合计: 旧 {n_old}  新 {n_new}   净增 {n_new - n_old}")
    print(f"新判据**独有** {len(new_imgs)} 个(必须逐个看图,确认全是真徽章)")
    print(f"旧判据**独有** {len(old_imgs)} 个(理论上应为 0;不为 0 就是新判据丢了真的)")

    t = tile(new_imgs, new_labs)
    if t is not None:
        p = os.path.join(OUT_DIR, "new_only.png")
        cv2.imwrite(p, t)
        print(f"  -> {p}")
    t = tile(old_imgs, old_labs)
    if t is not None:
        p = os.path.join(OUT_DIR, "old_only.png")
        cv2.imwrite(p, t)
        print(f"  -> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
