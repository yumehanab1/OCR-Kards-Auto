"""
badge_miss_diag.py - 诊断"某个徽章为什么没被 `_badges_cc` 检出"。

用法:
  .venv\\Scripts\\python.exe src\\badge_miss_diag.py --frame shots\\attack_probe\\0911_131142_after.png --x0 820 --x1 1010 --y0 420 --y1 560

做法:把指定区域里**每一个深色连通域**都列出来,并逐条标出它卡在哪一个
过滤条件上(宽/高/实心度/数字像素数/上下文亮度),再打印全场检出结果对照。

★ 这一步是"排参数"而不是"调参数":先看它卡在哪一条,再决定改哪一条。
   (2026-09-11 我按"尺寸过滤"扫了三档宽度上限,合并总数一点没变 —— 白扫一轮。)

★★ 2026-09-11 晚:**主判据已经换了**(数字判据从"绝对亮度像素"换成
   "被暗包住的亮块",见 `unit_state.enclosed_bright` / §7 第 67 条)。
   本工具量的**还是旧判据各条的过滤条件**,所以:
     · 它仍然能回答"这个深色块卡在宽/高/实心度/上下文哪一条上";
     · 但"数字像素 N"那一列**已经不是当前判据**了,别照它下结论。
   要看现在的判据,用:
     · `badge_band_probe.py`(连通域 vs 行带补检,带标注图和小图)
     · `badge_feat_probe.py`(给候选量特征,拿已知为真的徽章当正样本定阈值)
"""

from __future__ import annotations

import argparse
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", required=True)
    ap.add_argument("--x0", type=int, default=820)
    ap.add_argument("--x1", type=int, default=1010)
    ap.add_argument("--y0", type=int, default=420)
    ap.add_argument("--y1", type=int, default=540)
    ap.add_argument("--min-area", type=int, default=40)
    args = ap.parse_args()

    img = cv2.imread(args.frame)
    if img is None:
        print("读不到帧")
        return 1
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    V, S = hsv[:, :, 2], hsv[:, :, 1]
    # ★ 和 find_cost_badges 完全一致的掩码与裁剪
    dark = (V < 120).astype(np.uint8) * 255
    dark[:board.FIELD_Y0, :] = 0
    dark[us.BOARD_BADGE_MAX_Y:, :] = 0
    dark[:, :board.FIELD_X0] = 0
    dark[:, board.FIELD_X1:] = 0
    n, _labels, stats, _ = cv2.connectedComponentsWithStats(dark, 8)

    print(f"{os.path.basename(args.frame)}  区域 "
          f"x{args.x0}-{args.x1} y{args.y0}-{args.y1}")
    print(f"常数: W {us.BADGE_W_MIN}~{us.BADGE_W_MAX} H {us.BADGE_H_MIN}~{us.BADGE_H_MAX} "
          f"fill>={us.BADGE_FILL_MIN} 数字像素=(V>{us.BADGE_DIGIT_V})|"
          f"(S>{us.BADGE_DIGIT_S}) >= {us.BADGE_DIGIT_MIN_PX} 上下文>110\n")

    passed = 0
    for i in range(1, n):
        x, y, w, h, area = (int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]),
                            int(stats[i, 3]), int(stats[i, 4]))
        if x + w < args.x0 or x > args.x1 or y + h < args.y0 or y > args.y1:
            continue
        if area < args.min_area:
            continue
        why = []
        if not (us.BADGE_W_MIN <= w <= us.BADGE_W_MAX):
            why.append(f"宽{w}")
        if not (us.BADGE_H_MIN <= h <= us.BADGE_H_MAX):
            why.append(f"高{h}")
        fill = area / float(w * h)
        if fill < us.BADGE_FILL_MIN:
            why.append(f"fill{fill:.2f}")
        Vc, Sc = V[y:y + h, x:x + w], S[y:y + h, x:x + w]
        px = int(((Vc > us.BADGE_DIGIT_V) | (Sc > us.BADGE_DIGIT_S)).sum())
        if px < us.BADGE_DIGIT_MIN_PX:
            why.append(f"数字像素{px}")
        right = V[y:y + h, min(img.shape[1] - 1, x + w + 3):
                  min(img.shape[1], x + w + 10)]
        above = V[max(0, y - 7):max(1, y - 2), x:x + w]
        if not ((right.size and right.mean() > 110)
                or (above.size and above.mean() > 110)):
            why.append("上下文不亮")
        tag = "**通过**" if not why else " / ".join(why)
        if not why:
            passed += 1
        print(f"  x{x:4d} y{y:4d} {w:3d}x{h:3d} area{area:5d} 数字像素{px:4d}  -> {tag}")
    print(f"\n这一片里通过的徽章: {passed} 个")

    print("find_cost_badges 全场结果:")
    for b in us.find_cost_badges(img):
        print(f"  x{b['x']:4d} y{b['y']:4d} {b['w']}x{b['h']} "
              f"S={b['digit_s']:5.1f} n={b['digit_n']:4d} -> {b['state']}")

    crop = img[max(0, args.y0):args.y1, max(0, args.x0):args.x1]
    if crop.size:
        out = os.path.join(ROOT, "shots", "anchor_check", "diag_zoom.png")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cv2.imwrite(out, cv2.resize(crop, None, fx=2.4, fy=2.4,
                                    interpolation=cv2.INTER_NEAREST))
        print(f"放大图 -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
