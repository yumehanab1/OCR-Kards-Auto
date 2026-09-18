"""
badge_band_probe.py - 离线 A/B:"连通域版徽章检测" vs "行带补检"(不需要游戏)。

为什么要这个工具(而不是"看它能不能跑出结果"):
    §7 第 59 条那条教训 —— **合成用例全绿 ≠ 能用**。滑窗版当年就是
    "13/13 合成用例全过、真实帧上 44~68 个/帧"。
    所以任何新图像判据的最后一步,必须是**真实帧上的逐帧计数 + 和已有判据做 A/B**,
    而且要看图。这个脚本就是那道关:
      1. 逐帧打印 连通域版 / 行带补检 / 合并 的数量;
      2. 把**只有补检找到的那些**单独拼成小图(`--tiles`),人眼逐个核对
         —— 补检加进来的必须**每一个都是真徽章**,否则它就是"制造假攻击"的工具;
      3. `--shots` 存标注图(蓝=连通域 绿=补检新增)。

用法:
  .venv\\Scripts\\python.exe src\\badge_band_probe.py --set board
  .venv\\Scripts\\python.exe src\\badge_band_probe.py --set all --tiles
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
import unit_state as us  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SETS = {
    "board": ("shots/board_samples", "0911_122530_00*.png"),
    "deploy": ("shots/deploy_probe", "f0*.png"),
    "attack_clean": ("shots/attack_probe", "*_after.png"),
    "attack_move": ("shots/attack_probe", "*_movefront.png"),
}
BAD = ("_mask", "_annot", "_field", "_anchor")


def files_for(name, limit=0):
    if name == "all":
        out = []
        for k in SETS:
            out += files_for(k)
        return out
    d, pat = SETS[name]
    fs = sorted(glob.glob(os.path.join(ROOT, d, pat)))
    fs = [f for f in fs if not any(s in f for s in BAD)]
    return fs[:limit] if limit else fs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="all", choices=sorted(SETS) + ["all"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--shots", action="store_true")
    ap.add_argument("--tiles", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    files = files_for(args.set, args.limit)
    if not files:
        print("没有帧")
        return 1
    outdir = os.path.join(ROOT, "shots", "badge_band")
    if args.shots or args.tiles:
        os.makedirs(outdir, exist_ok=True)

    print(f"{args.set}: {len(files)} 帧")
    print(f"{'帧':30s} {'cc':>4s} {'band':>5s} {'新增':>5s} {'合并':>5s}  备注")
    tot = {"cc": 0, "band": 0, "new": 0, "union": 0}
    tiles = []
    for f in files:
        img = cv2.imread(f)
        if img is None:
            continue
        rows = board.rows_from_boxes(board.card_boxes(img))
        cc = us._badges_cc(img)
        band = us.find_cost_badges_band(img, rows)
        uni = us.find_cost_badges(img, rows=rows)
        # "只有补检找到的" = 合并里 from=band 的那些
        new = [b for b in uni if b.get("from") == "band"]
        for k, v in (("cc", len(cc)), ("band", len(band)),
                     ("new", len(new)), ("union", len(uni))):
            tot[k] += v
        note = ""
        if len(uni) != len(cc):
            note = (f"cc x={[b['x'] for b in cc]} "
                    f"新增 x={[(b['x'], b['y'], b['state']) for b in new]}")
        print(f"{os.path.basename(f):30s} {len(cc):4d} {len(band):5d} "
              f"{len(new):5d} {len(uni):5d}  {note}")
        if args.verbose:
            for b in band:
                print(f"      band x{b['x']} y{b['y']} S={b['digit_s']} "
                      f"n={b['digit_n']} -> {b['state']}")
        if args.shots:
            out = img.copy()
            for b in cc:
                cv2.rectangle(out, (b["x"], b["y"]),
                              (b["x"] + b["w"], b["y"] + b["h"]), (255, 0, 0), 2)
                cv2.putText(out, f"cc{b['state'] or '?'}", (b["x"] - 8, b["y"] + 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)
            for b in new:
                col = ((0, 0, 255) if b["state"] == "orange"
                       else (0, 255, 0) if b["state"] == "grey" else (0, 255, 255))
                cv2.rectangle(out, (b["x"], b["y"]),
                              (b["x"] + b["w"], b["y"] + b["h"]), col, 2)
                cv2.putText(out, f"B{b['state'] or '?'}", (b["x"] - 8, b["y"] + 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1)
            cv2.imwrite(os.path.join(outdir, os.path.basename(f)), out)
        if args.tiles:
            for b in new:
                x, y, w, h = b["x"], b["y"], b["w"], b["h"]
                x0, y0 = max(0, x - 12), max(0, y - 12)
                crop = img[y0:y + h + 12, x0:x + w + 12].copy()
                if crop.size == 0:
                    continue
                crop = cv2.resize(crop, (160, 160),
                                  interpolation=cv2.INTER_NEAREST)
                cv2.putText(crop, f"S{b['digit_s']:.0f}", (3, 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)
                cv2.putText(crop, f"{b['state'] or '?'}", (3, 155),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1)
                tiles.append(crop)

    print(f"\n合计 cc={tot['cc']} band={tot['band']} 补检新增={tot['new']} "
          f"合并={tot['union']}")
    if args.tiles and tiles:
        cols = 10
        rows_img = []
        for i in range(0, len(tiles), cols):
            chunk = tiles[i:i + cols]
            while len(chunk) < cols:
                chunk.append(np.zeros((160, 160, 3), np.uint8))
            rows_img.append(np.hstack(chunk))
        p = os.path.join(outdir, "band_only_tiles.png")
        cv2.imwrite(p, np.vstack(rows_img))
        print(f"补检新增的小图({len(tiles)} 个) -> {p}")
    if args.shots:
        print(f"标注图 -> {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
