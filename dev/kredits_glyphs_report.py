"""
kredits_glyphs_report.py - 整理录到的 Kredits 字形,生成去重报表 + 一张拼图。

录制(kredits_record.py)会把每个"新字形"按出现顺序存成 n_XX.png。因为字形
会被墨迹装饰切碎、也可能混入噪声,直接按序号当费用值是错的。本脚本:

  1. 读入所有 n_XX.png,归一化后两两比较,把相似字形归为一类(去重)
  2. 每类选一张最清晰的代表,拼成一张contact sheet(拼图)存到
     shots/kredits/glyphs_sheet.png,方便一眼看完全部字形
  3. 打印 类别 -> 成员序号 的对照表,便于确定"哪张是几费"

用法:
  .venv\\Scripts\\python.exe src\\kredits_glyphs_report.py
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "shots", "kredits", "samples")
SHEET = os.path.join(ROOT, "shots", "kredits", "glyphs_sheet.png")

NORM_W, NORM_H = 32, 48
CLUSTER_THRESHOLD = 22.0     # 平均绝对差小于此值视为同一字形
MIN_HEIGHT = 28              # 数字字形高 36;低于这个高度的多半是被切的或噪声


def norm_of(mask):
    return cv2.resize(mask, (NORM_W, NORM_H), interpolation=cv2.INTER_AREA)


def main() -> int:
    files = sorted(glob.glob(os.path.join(SAMPLES, "n_*.png")))
    files = [f for f in files if not f.endswith("_mask.png")]
    if not files:
        print(f"没有找到样例,先跑 kredits_record.py。目录: {SAMPLES}")
        return 1

    items = []
    for f in files:
        img = cv2.imread(f)
        mf = f.replace(".png", "_mask.png")
        mask = cv2.imread(mf, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        stem = os.path.basename(f).replace(".png", "")
        if mask is None:
            # 没有掩码就用彩色图做灰度近似
            mask = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        items.append({
            "name": stem,
            "file": f,
            "img": img,
            "mask": mask,
            "norm": norm_of(mask),
            "h": img.shape[0],
            "w": img.shape[1],
        })

    print(f"读到 {len(items)} 张字形\n")

    # 按高度初筛:太矮的单独列出来(很可能是被切碎的)
    tall = [it for it in items if it["h"] >= MIN_HEIGHT]
    short = [it for it in items if it["h"] < MIN_HEIGHT]

    # 聚类
    clusters = []
    for it in tall:
        placed = False
        for c in clusters:
            if float(cv2.absdiff(it["norm"], c["rep"]["norm"]).mean()) < CLUSTER_THRESHOLD:
                c["members"].append(it)
                placed = True
                break
        if not placed:
            clusters.append({"rep": it, "members": [it]})

    print("=" * 84)
    print(f"疑似完整字形 (高 >= {MIN_HEIGHT}px): {len(tall)} 张 -> {len(clusters)} 类")
    print("=" * 84)
    print(f"{'类':<5}{'代表':<10}{'尺寸':<10}{'成员(序号)':<34}{'宽高比':<8}{'填充率'}")
    print("-" * 84)
    for i, c in enumerate(clusters):
        rep = c["rep"]
        mem = ", ".join(m["name"].replace("n_", "#") for m in c["members"])
        cov = float((rep["mask"] > 0).mean())
        size = f"{rep['w']}x{rep['h']}"
        print(f"{i:<5}{rep['name']:<10}{size:<10}{mem:<34}"
              f"{rep['w'] / rep['h']:<8.2f}{cov:.2f}")

    if short:
        print()
        print("=" * 84)
        print(f"疑似被切碎/噪声 (高 < {MIN_HEIGHT}px): {len(short)} 张")
        print("=" * 84)
        for it in short:
            cov = float((it["mask"] > 0).mean())
            print(f"    {it['name']:<10}{it['w']}x{it['h']:<8}宽高比 {it['w'] / it['h']:.2f}  "
                  f"填充率 {cov:.2f}")

    # 拼图:每类一张代表,横向排列
    reps = [c["rep"] for c in clusters] + short
    if reps:
        cell_w, cell_h = 90, 130
        cols = min(14, max(1, len(reps)))
        rows = (len(reps) + cols - 1) // cols
        sheet = np.zeros((rows * cell_h, cols * cell_w, 3), dtype=np.uint8)
        for i, it in enumerate(reps):
            r, c = divmod(i, cols)
            y0, x0 = r * cell_h, c * cell_w
            img = it["img"]
            scale = min((cell_w - 20) / img.shape[1], (cell_h - 50) / img.shape[0], 3.0)
            disp = cv2.resize(img, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_NEAREST)
            dh, dw = disp.shape[:2]
            oy = y0 + 8 + (cell_h - 50 - dh) // 2
            ox = x0 + (cell_w - dw) // 2
            sheet[oy:oy + dh, ox:ox + dw] = disp
            cv2.putText(sheet, it["name"].replace("n_", "#"), (x0 + 6, y0 + cell_h - 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
            cv2.putText(sheet, f"{it['w']}x{it['h']}", (x0 + 6, y0 + cell_h - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 160, 160), 1, cv2.LINE_AA)
        os.makedirs(os.path.dirname(SHEET), exist_ok=True)
        cv2.imwrite(SHEET, sheet)
        print()
        print(f"拼图已存: {SHEET}  ({len(reps)} 个字形, {cols} 列)")
        print("绿色是样例名(#序号),灰色是尺寸。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
