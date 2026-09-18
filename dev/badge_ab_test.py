"""
badge_ab_test.py - 离线对比两版**费用徽章检测器**(不需要游戏)。

  `unit_state.find_cost_badges`      = 主判据(深色连通域 + 尺寸过滤)
  `unit_state.find_cost_badges_win`  = 失败的滑窗实验(2026-09-11 下午,已弃用)

为什么要有这个对比:滑窗版的动机是"连通域在徽章与旁边暗部粘连时会漏检",
而它自己在合成用例上 13/13 全过。但**真实帧上它是灾难**(见下面实测),
所以它被降级成"实验品"。这个脚本就是当时的证据,留着防止有人再走一遍。

★ 评测帧的卫生:`shots/attack_probe/*_probe.png` 是**上一轮自己写的标注图**
  (画了洋红框和文字,实测 803~2702 个洋红像素),洋红是"又亮又饱和"的像素,
  会污染"数字像素"判据。干净的是 `*_after.png` / `*_movefront.png`,
  以及 `shots/board_samples/*_00N.png`(不带 `_mask`/`_annot` 后缀的才是原图)、
  `shots/deploy_probe/f0*.png`。**结论只信干净帧。**

用法:
  .venv\\Scripts\\python.exe src\\badge_ab_test.py --set board
  .venv\\Scripts\\python.exe src\\badge_ab_test.py --set deploy --shots
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
    "attack": ("shots/attack_probe", "*.png"),
    "attack_clean": ("shots/attack_probe", "*_after.png"),
    "board": ("shots/board_samples", "0911_122530_00*.png"),
    "deploy": ("shots/deploy_probe", "f0*.png"),
}


def files_for(name, limit=0):
    d, pat = SETS[name]
    fs = sorted(glob.glob(os.path.join(ROOT, d, pat)))
    fs = [f for f in fs if "_mask" not in f and "_annot" not in f
          and "_field" not in f and "_anchor" not in f]
    return fs[:limit] if limit else fs


def mag_px(img):
    """洋红像素数 —— 判断这一帧是不是被自己的标注污染过。"""
    return int(((img[:, :, 0] > 200) & (img[:, :, 1] < 60)
                & (img[:, :, 2] > 200)).sum())


def draw(img, badges, path, color, label):
    out = img.copy()
    for b in badges:
        cv2.rectangle(out, (b["x"], b["y"]), (b["x"] + b["w"], b["y"] + b["h"]),
                      color, 2)
        cv2.putText(out, f"{label}{b['state'] or '?'}",
                    (b["x"], max(12, b["y"] - 3)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
    cv2.imwrite(path, out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="board", choices=sorted(SETS))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--shots", action="store_true")
    args = ap.parse_args()

    files = files_for(args.set, args.limit)
    if not files:
        print("没有帧")
        return 1
    outdir = os.path.join(ROOT, "shots", "badge_ab")
    if args.shots:
        os.makedirs(outdir, exist_ok=True)

    print(f"{args.set}: {len(files)} 帧")
    print(f"{'帧':34s} {'脏?':>4s} {'主判据':>6s} {'滑窗实验':>8s}  两边不一致的地方")
    tot_c = tot_w = diffs = 0
    for f in files:
        img = cv2.imread(f)
        if img is None:
            continue
        cc = us.find_cost_badges(img)
        win = us.find_cost_badges_win(img)
        tot_c += len(cc)
        tot_w += len(win)
        dirty = "脏" if mag_px(img) > 0 else ""
        msg = ""
        if len(cc) != len(win):
            diffs += 1
            msg = (f"主判据x={[b['x'] for b in cc]} "
                   f"滑窗x={[b['x'] for b in win][:12]}…")
        print(f"{os.path.basename(f):34s} {dirty:>4s} {len(cc):3d} {len(win):4d}  {msg}")
        if args.shots:
            draw(img, cc, os.path.join(outdir, os.path.basename(f)
                                       .replace(".png", "_cc.png")),
                 (255, 0, 0), "cc:")
            draw(img, win, os.path.join(outdir, os.path.basename(f)
                                        .replace(".png", "_win.png")),
                 (0, 255, 0), "win:")
    print(f"\n合计 cc={tot_c} / win={tot_w};两边数量不一致的帧 {diffs}/{len(files)}")
    if args.shots:
        print(f"对比图 -> {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
