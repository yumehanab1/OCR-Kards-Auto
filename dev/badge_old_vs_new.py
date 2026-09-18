"""
badge_old_vs_new.py - 离线核对:**旧的"数字像素"绝对判据** vs **新的"被暗包住的亮块"**,
在真实帧上"多收进来的那些"到底是真徽章还是假阳性。

为什么必须核对(而不是"测试全绿就算完"):
    换判据的副作用一定是"收进来的集合变了"。变多不等于错,但也可能是一堆假阳性
    —— 而徽章判据的假阳性会直接变成"bot 以为某个单位能行动 -> 白拖一次"
    (正是 §7 第 65 条那个坑)。所以要把**新增的**一个个切出来看图。

用法:
  .venv\\Scripts\\python.exe src\\badge_old_vs_new.py --set board+deploy+attack
  .venv\\Scripts\\python.exe src\\badge_old_vs_new.py --set board --tiles
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
BAD = ("_mask", "_annot", "_field", "_anchor")

# ---- 旧判据(2026-09-11 下午那一版)的参数,原样抄回来 ----
OLD_DIGIT_V = 135
OLD_DIGIT_S = 90
OLD_DIGIT_MIN_PX = 12


def old_cc_badges(frame):
    """旧版 `find_cost_badges`:连通域 + 绝对数字像素判据 + 上下文亮。"""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    V, S = hsv[:, :, 2], hsv[:, :, 1]
    dark = (V < us.BADGE_DARK_V).astype(np.uint8) * 255
    dark[:board.FIELD_Y0, :] = 0
    dark[us.BOARD_BADGE_MAX_Y:, :] = 0
    dark[:, :board.FIELD_X0] = 0
    dark[:, board.FIELD_X1:] = 0
    n, _lab, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = (int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]),
                            int(stats[i, 3]), int(stats[i, 4]))
        if not (us.BADGE_W_MIN <= w <= us.BADGE_W_MAX
                and us.BADGE_H_MIN <= h <= us.BADGE_H_MAX):
            continue
        if area / float(w * h) < us.BADGE_FILL_MIN:
            continue
        Vc, Sc = V[y:y + h, x:x + w], S[y:y + h, x:x + w]
        bright = (Vc > OLD_DIGIT_V) | (Sc > OLD_DIGIT_S)
        if int(bright.sum()) < OLD_DIGIT_MIN_PX:
            continue
        right = V[y:y + h, min(frame.shape[1] - 1, x + w + 3):
                  min(frame.shape[1], x + w + 10)]
        above = V[max(0, y - 7):max(1, y - 2), x:x + w]
        if not ((right.size and right.mean() > 110)
                or (above.size and above.mean() > 110)):
            continue
        s_mean = float(Sc[bright].mean())
        st = ("orange" if s_mean >= us.SAT_ORANGE_MIN
              else "grey" if s_mean <= us.SAT_GREY_MAX else None)
        out.append({"x": x, "y": y, "w": w, "h": h, "state": st,
                    "digit_s": round(s_mean, 1), "from": "old"})
    return out


def files_for(spec):
    files = []
    if "board" in spec:
        files += sorted(glob.glob(os.path.join(ROOT, "shots", "board_samples",
                                               "0911_122530_00*.png")))
    if "deploy" in spec:
        files += sorted(glob.glob(os.path.join(ROOT, "shots", "deploy_probe",
                                               "f0*.png")))
    if "attack" in spec:
        files += sorted(glob.glob(os.path.join(ROOT, "shots", "attack_probe",
                                               "*.png")))
    return [f for f in files if not any(s in f for s in BAD)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="board+deploy+attack")
    ap.add_argument("--tiles", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    files = files_for(args.set)
    if args.limit:
        files = files[:args.limit]

    outdir = os.path.join(ROOT, "shots", "badge_oldnew")
    tiles = []
    lost_tiles = []
    n_old = n_new = n_add = n_lost = 0
    changed = []
    for f in files:
        img = cv2.imread(f)
        if img is None:
            continue
        old = old_cc_badges(img)
        rows = board.rows_from_boxes(board.card_boxes(img))
        new = us.find_cost_badges(img, rows=rows)
        n_old += len(old)
        n_new += len(new)
        added = [b for b in new if not any(
            abs(b["cx"] - o["x"] - o["w"] // 2) <= us.NMS_DIST
            and abs(b["cy"] - o["y"] - o["h"] // 2) <= us.NMS_DIST for o in old)]
        lost = [o for o in old if not any(
            abs(o["x"] + o["w"] // 2 - b["cx"]) <= us.NMS_DIST
            and abs(o["y"] + o["h"] // 2 - b["cy"]) <= us.NMS_DIST for b in new)]
        n_add += len(added)
        n_lost += len(lost)
        if added or lost:
            changed.append((os.path.basename(f), added, lost))
            for tag, lst in (("add", added), ("lost", lost)):
                if not args.tiles:
                    continue
                for b in lst:
                    x, y, w, h = b["x"], b["y"], b["w"], b["h"]
                    crop = img[max(0, y - 10):y + h + 10,
                               max(0, x - 10):x + w + 10].copy()
                    if crop.size == 0:
                        continue
                    crop = cv2.resize(crop, (150, 150),
                                      interpolation=cv2.INTER_NEAREST)
                    cv2.putText(crop, f"{tag} {b['state'] or '?'}",
                                (3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                                (255, 255, 255), 1)
                    cv2.putText(crop, f"{b.get('from', '?')} x{b['x']}",
                                (3, 144), cv2.FONT_HERSHEY_SIMPLEX, 0.35,
                                (0, 255, 255), 1)
                    (tiles if tag == "add" else lost_tiles).append(crop)

    print(f"{len(files)} 帧:  旧判据 {n_old} 个 / 新判据 {n_new} 个")
    print(f"  新判据**多收** {n_add} 个, **丢掉** {n_lost} 个")
    for name, added, lost in changed[:40]:
        print(f"  {name:30s} +{len(added)} -{len(lost)}  "
              f"新增x={[(b['x'], b['y'], b['from'], b['state']) for b in added]}")
        if lost:
            print(f"     丢掉: {[(b['x'], b['y'], b['state']) for b in lost]}")
    if args.tiles:
        os.makedirs(outdir, exist_ok=True)
        cols = 12
        for tag, lst in (("added", tiles), ("lost", lost_tiles)):
            if not lst:
                continue
            rows_img = []
            for i in range(0, len(lst), cols):
                chunk = lst[i:i + cols]
                while len(chunk) < cols:
                    chunk.append(np.zeros((150, 150, 3), np.uint8))
                rows_img.append(np.hstack(chunk))
            p = os.path.join(outdir, f"{tag}_tiles.png")
            cv2.imwrite(p, np.vstack(rows_img))
            print(f"{tag} 小图({len(lst)} 个)-> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
