"""
guard_ab.py - ★ 离线 A/B:守护判据在**全语料**上跑一遍,把命中逐个存图**人眼看**
              (§7 第 59/67/78 条的纪律:换判据必须把"收进来的"摊开看)

输出:
  · 每个命中卡的裁剪图 + 分数 -> `shots/guard_ab/hits/`
  · 命中拼图 -> `shots/guard_ab/hits_top.png`(按分数排序,一眼看完全部)
  · **边界带**(0.80~0.95)单独拼一张 -> `shots/guard_ab/borderline.png`
    ★ 这一张最值钱:门槛附近的东西是"真盾"还是"别的字形",只能看图。
"""
from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np

import board
import guard

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "shots", "guard_ab")
TILE = 34


def _montage(items, path, per=8):
    """items: [(score, img, label)] -> 拼图存盘。"""
    tiles = []
    for s, im, lab in items:
        big = cv2.resize(im, None, fx=5, fy=5, interpolation=cv2.INTER_NEAREST)
        bar = np.zeros((26, big.shape[1], 3), np.uint8)
        cv2.putText(bar, "%.2f" % s, (2, 11), cv2.FONT_HERSHEY_SIMPLEX,
                    0.35, (255, 255, 255), 1)
        cv2.putText(bar, lab[:16], (2, 23), cv2.FONT_HERSHEY_SIMPLEX,
                    0.32, (170, 220, 255), 1)
        tiles.append(np.vstack([big, bar]))
    if not tiles:
        return 0
    rows = []
    for i in range(0, len(tiles), per):
        chunk = tiles[i:i + per]
        h = max(t.shape[0] for t in chunk)
        chunk = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, 6,
                                    cv2.BORDER_CONSTANT, (0, 0, 0)) for t in chunk]
        rows.append(np.hstack(chunk))
    w = max(r.shape[1] for r in rows)
    rows = [cv2.copyMakeBorder(r, 0, 6, 0, w - r.shape[1],
                               cv2.BORDER_CONSTANT, (0, 0, 0)) for r in rows]
    cv2.imwrite(path, np.vstack(rows))
    return len(tiles)


def main():
    os.makedirs(os.path.join(OUT, "hits"), exist_ok=True)
    files = (sorted(glob.glob(os.path.join(ROOT, "shots", "attack_frames", "*.png")))
             + sorted(glob.glob(os.path.join(ROOT, "shots", "board_samples", "*.png")))
             + [os.path.join(ROOT, "shots", "live_probe.png")])
    hits, border, total, cards = [], [], 0, 0
    frames_with_guard = 0
    for p in files:
        im = cv2.imread(p)
        if im is None:
            continue
        name = os.path.basename(p)
        field = board.read_field(im, templates=None)
        hq = board.find_enemy_hq(im, field=field, templates=None)
        cards_here = []
        if hq:
            cards_here.append(("hq", hq))
        for u in (field.get("enemy_support") or []):
            if not u.get("is_hq"):
                cards_here.append(("unit", u))
        # ★ 不止敌方支援线:所有行的卡都扫一遍(我们自己那张带守护的卡也要看得见)
        for r in (field.get("rows") or []):
            for b in (r.get("boxes") or []):
                cards_here.append((r.get("side") or "?", b))
        seen = set()
        got = False
        for kind, b in cards_here:
            key = (kind, int(b["x"]), int(b["y"]))
            if key in seen:
                continue
            seen.add(key)
            total += 1
            s, d = guard.glyph_at(im, b)
            sc = d.get("score") or 0.0
            if sc >= guard.MATCH_MIN:
                cards += 1
                got = True
            if sc >= 0.80:
                x, y = d.get("at") or (int(b["x"]), int(b["y"]))
                crop = im[max(0, y - 9):y + 25, max(0, x - 9):x + 25]
                if crop.shape[0] < TILE or crop.shape[1] < TILE:
                    crop = cv2.copyMakeBorder(
                        crop, 0, max(0, TILE - crop.shape[0]),
                        0, max(0, TILE - crop.shape[1]),
                        cv2.BORDER_CONSTANT, (0, 0, 0))
                lab = f"{kind}:{name[5:13]}"
                if sc >= guard.MATCH_MIN:
                    hits.append((sc, crop, lab))
                else:
                    border.append((sc, crop, lab))
                if sc >= guard.MATCH_MIN:
                    cv2.imwrite(os.path.join(OUT, "hits",
                                             f"{name}_{kind}_x{int(b['x'])}.png"),
                                cv2.resize(crop, None, fx=6, fy=6,
                                           interpolation=cv2.INTER_NEAREST))
        if got:
            frames_with_guard += 1
    hits.sort(key=lambda t: t[0], reverse=True)
    border.sort(key=lambda t: t[0], reverse=True)
    n1 = _montage(hits, os.path.join(OUT, "hits_top.png"))
    n2 = _montage(border, os.path.join(OUT, "borderline.png"))
    print(f"看了 {len(files)} 帧 / {total} 张卡")
    print(f"命中盾牌(>= {guard.MATCH_MIN}): {cards} 张卡,分布在 "
          f"{frames_with_guard} 帧")
    print(f"命中拼图({n1} 张)-> {OUT}\\hits_top.png")
    print(f"★ 边界带 0.80~{guard.MATCH_MIN}({n2} 张)-> {OUT}\\borderline.png"
          f"   <- 这一张要人眼看:门槛附近是不是真盾")


if __name__ == "__main__":
    main()
