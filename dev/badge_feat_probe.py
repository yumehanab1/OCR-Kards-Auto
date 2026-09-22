"""
badge_feat_probe.py - 给徽章候选量一组特征,用**已知为真的徽章**(连通域版检出的)
当正样本去定阈值(离线,不需要游戏)。

为什么需要它:
    行带补检(`find_cost_badges_band`)的假阳性会变成"bot 以为某个单位能行动",
    然后从**空桌面**上按下鼠标拖向敌方总部 —— 那正是这个项目最想消除的"乱拖"。
    所以补检不能只看"能跑出结果",要有量化门槛。

做法:
    · 正样本 = `_badges_cc` 的结果(连通域 + 尺寸过滤,假阳性极低,看图核对过)
    · 待判样本 = `find_cost_badges_band` 里**不属于任何正样本**的那些
    对每个样本量同一组特征,打印两类的分布,阈值就取在两类之间。

用法:
  .venv\\Scripts\\python.exe dev\\badge_feat_probe.py --set board+deploy+attack
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


def feats(img, V, S, x, y, w, h):
    """一个候选窗口的一组特征。"""
    Vc = V[y:y + h, x:x + w].astype(np.float32)
    enc, _b = us.enclosed_bright(Vc)
    nl, lab, st, _ = cv2.connectedComponentsWithStats(enc.astype(np.uint8), 8)
    keep = np.zeros_like(enc)
    for i in range(1, nl):
        if st[i, 4] < us.DIGIT_BLOB_MIN_PX:
            continue
        if st[i, 2] > us.DIGIT_BLOB_W_MAX:
            continue
        if not (us.DIGIT_BLOB_H_MIN <= st[i, 3] <= us.DIGIT_BLOB_H_MAX):
            continue
        keep |= (lab == i)
    bg = float(np.percentile(Vc, us.DIGIT_BG_PCT))
    thr = min(us.DIGIT_DARK_V, bg + us.DIGIT_REL_DELTA)
    dark = Vc < thr
    ring = np.concatenate([dark[0, :], dark[-1, :], dark[:, 0], dark[:, -1]])
    ys, xs = np.nonzero(keep)
    if len(ys):
        cy = (ys.min() + ys.max()) / 2.0 / max(1, h - 1)
        cx = (xs.min() + xs.max()) / 2.0 / max(1, w - 1)
        off = max(abs(cy - 0.5), abs(cx - 0.5))
        bh = int(ys.max() - ys.min() + 1)
        bw = int(xs.max() - xs.min() + 1)
    else:
        off, bh, bw = 9.0, 0, 0
    right = V[y + 2:y + h - 2, x + w + 2:x + w + 14].astype(np.float32)
    return {
        "dark": float(dark.mean()), "ring": float(ring.mean()),
        "n": int(keep.sum()), "off": float(off), "bh": bh, "bw": bw,
        "right": float((right > us.BAND_BRIGHT_V).mean()) if right.size else 0.0,
        "S": float(S[y:y + h, x:x + w][keep].mean()) if keep.any() else -1.0,
    }


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
    args = ap.parse_args()

    pos, cand = [], []
    for f in files_for(args.set):
        img = cv2.imread(f)
        if img is None:
            continue
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        V, S = hsv[:, :, 2], hsv[:, :, 1]
        rows = board.rows_from_boxes(board.card_boxes(img))
        cc = us._badges_cc(img)
        band = us.find_cost_badges_band(img, rows)
        for b in cc:
            pos.append((f, b, feats(img, V, S, b["x"], b["y"], b["w"], b["h"])))
        for b in band:
            if any(abs(b["cx"] - o["cx"]) <= 20 and abs(b["cy"] - o["cy"]) <= 20
                   for o in cc):
                continue
            cand.append((f, b, feats(img, V, S, b["x"], b["y"], b["w"], b["h"])))

    print(f"正样本(连通域版){len(pos)} 个 / 待判(补检独有){len(cand)} 个\n")
    keys = ["dark", "ring", "n", "off", "bh", "bw", "right"]
    print(f"{'特征':8s} {'正样本 min/中位/max':>26s}   {'补检 min/中位/max':>26s}")
    for k in keys:
        a = sorted(p[2][k] for p in pos)
        b = sorted(c[2][k] for c in cand)
        if not a or not b:
            continue
        print(f"{k:8s} {a[0]:8.2f}/{a[len(a) // 2]:8.2f}/{a[-1]:8.2f}"
              f"   {b[0]:8.2f}/{b[len(b) // 2]:8.2f}/{b[-1]:8.2f}")

    print("\n按 ring(外圈暗占比)分档看补检候选:")
    for lo in (0.0, 0.5, 0.6, 0.7, 0.8, 0.9):
        hi = lo + 0.1
        c = [x for x in cand if lo <= x[2]["ring"] < hi]
        p = [x for x in pos if lo <= x[2]["ring"] < hi]
        print(f"  ring {lo:.1f}-{hi:.1f}: 正样本 {len(p):4d} / 补检 {len(c):4d}")
    print("\n按 dark(窗口暗占比)分档:")
    for lo in (0.5, 0.6, 0.7, 0.8, 0.9):
        hi = lo + 0.1
        c = [x for x in cand if lo <= x[2]["dark"] < hi]
        p = [x for x in pos if lo <= x[2]["dark"] < hi]
        print(f"  dark {lo:.1f}-{hi:.1f}: 正样本 {len(p):4d} / 补检 {len(c):4d}")
    print("\n按 off(数字偏离窗口中心,0=正中)分档:")
    for lo in (0.0, 0.1, 0.15, 0.2, 0.3):
        hi = lo + 0.05
        c = [x for x in cand if lo <= x[2]["off"] < hi]
        p = [x for x in pos if lo <= x[2]["off"] < hi]
        print(f"  off {lo:.2f}-{hi:.2f}: 正样本 {len(p):4d} / 补检 {len(c):4d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
