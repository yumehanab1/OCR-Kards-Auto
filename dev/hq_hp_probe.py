"""
hq_hp_probe.py - 总部血量盾牌的**取样 / 聚类 / 标定**工具(只读,不需要游戏)。

背景(2026-09-12 第六个会话,用户提出):
    `find_enemy_hq` 原来靠"整行 OCR 找 h>=24 的纯数字"读总部血量 —— 实测**时好时坏**:
    20 张存帧里只有 3 张读得到;而且**单个数字**(7 / 8 / 2)在这个分辨率下
    RapidOCR **一个都读不出来**(把盾牌裁出来放大 3x/5x、加白边都试过,还是空)。
    用户补充:总部血量是**白 / 红 / 绿三种颜色**,覆盖 **1~99**。

做法(和 kredits 那套一样:先取样 -> 人眼标定 -> 模板匹配):
    1. 在总部卡的**下半部**找那个**深色盾牌**(最大的、居中、够方的暗连通域);
    2. 盾牌内部按"**比盾牌底色亮、或者饱和**"取数字像素
       (`(V > max(110, 底色+22)) | (S > 100)` —— 红字不亮但饱和,白字亮但不饱和,
        绿色两者都有,所以两个条件要取**或**);
    3. 连通域 -> 每个字形(1~2 个 = 1~99);
    4. 归一化 + 与模板库比,取最像的;
    5. 顺带记下字形的平均色相/饱和度 -> **白/红/绿**三种状态。

本工具只做前三步 + 聚类拼图,方便**人眼标定**:
  --action collect   : 把所有帧里的字形抠出来存到 shots/hq_hp/,并写 index.jsonl
  --action cluster   : 按形状聚类,每个簇拼一行(带 member 数)-> 人眼贴标签
  --action montage   : 按**帧**拼图(盾牌 + 抠出来的字形),用来核对"抠对没有"

用法:
  .venv\\Scripts\\python.exe dev\\hq_hp_probe.py --action cluster
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import board  # noqa: E402
import hq_hp  # noqa: E402          # ★ 定位/抠字形/匹配只留一份实现,见 hq_hp.py 文件头

# ★ 定位盾牌、抠字形**复用生产代码**(hq_hp),不在这里再抄一份 ——
#   §7 第 60 条那个"同一个语义两处实现、迟早各错一半"的坑。
find_shield = hq_hp.find_shield
extract_glyphs = hq_hp.extract_glyphs

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT_ROOT, "shots", "hq_hp")
BANK_DIR = hq_hp.BANK_DIR
FRAME_DIRS = ["shots/attack_frames", "shots/board_samples"]

NORM = hq_hp.NORM
CLUSTER_THR = 0.80  # 形状相似度阈值(贪心聚类)


def collect():
    """扫所有帧,把"总部卡"的盾牌 + 字形抠出来存盘。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    index = []
    for d in FRAME_DIRS:
        for f in sorted(glob.glob(os.path.join(PROJECT_ROOT, d, "*.png"))):
            if "_annot" in os.path.basename(f):
                continue
            img = cv2.imread(f)
            if img is None:
                continue
            try:
                field = board.read_field(img)
            except Exception:
                continue
            if not field.get("rows"):
                continue
            # 只在"最上面那一行(敌方支援)"和"最下面那一行(我方支援)"找总部
            cand_rows = [field["rows"][0]]
            if len(field["rows"]) > 1:
                cand_rows.append(field["rows"][-1])
            for ri, row in enumerate(cand_rows):
                for ci, b in enumerate(row.get("boxes", [])):
                    got = find_shield(img, b)
                    if got is None:
                        continue
                    shield, sbox = got
                    gs = extract_glyphs(shield)
                    if not gs:
                        continue
                    name = "%s_r%d_c%d" % (os.path.splitext(os.path.basename(f))[0], ri, ci)
                    cv2.imwrite(os.path.join(OUT_DIR, name + "_shield.png"), shield)
                    for gi, g in enumerate(gs):
                        gp = name + "_g%d.png" % gi
                        cv2.imwrite(os.path.join(OUT_DIR, gp), g["img"])
                        index.append({"frame": os.path.relpath(f, PROJECT_ROOT),
                                      "card": [int(v) for v in (b["x"], b["y"], b["w"], b["h"])],
                                      "row": ri, "col": ci, "glyph": gi, "png": gp,
                                      "x": g["x"], "y": g["y"], "w": g["w"], "h": g["h"],
                                      "n": g["n"], "s": round(g["s"], 1), "v": round(g["v"], 1),
                                      "hue": round(g["hue"], 1)})
    with open(os.path.join(OUT_DIR, "index.jsonl"), "w", encoding="utf-8") as fh:
        for r in index:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"抠出 {len(index)} 个字形(来自 {len(set(r['frame'] for r in index))} 帧)"
          f" -> {os.path.relpath(OUT_DIR, PROJECT_ROOT)}")
    return index


def _norm(img, size=NORM):
    return cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)


def build():
    """
    把"人眼标定过的形状簇"变成**模板库**:`config/hq_hp_digits/<数字>/*.png`。

    标签在 `shots/hq_hp/labels.json`(簇号 -> 数字,null = 噪点丢掉)。
    ★ 借来的原型(目前只有数字 5,来自 kredits 库)也在这里落盘,
      并在 `config/hq_hp_digits/BORROWED.txt` 里写明来源 —— "借的"和"实机采的"要分得开。
    """
    labels_path = os.path.join(OUT_DIR, "labels.json")
    clusters_path = os.path.join(OUT_DIR, "clusters.json")
    if not (os.path.exists(labels_path) and os.path.exists(clusters_path)):
        print("先跑 --action collect / cluster,并写好 shots/hq_hp/labels.json")
        return
    labels = json.load(open(labels_path, encoding="utf-8"))
    clusters = json.load(open(clusters_path, encoding="utf-8"))
    os.makedirs(BANK_DIR, exist_ok=True)
    n_put = {}
    for ci, members in enumerate(clusters):
        d = labels.get(str(ci))
        if d is None:
            continue
        dst = os.path.join(BANK_DIR, str(d))
        os.makedirs(dst, exist_ok=True)
        for m in members:
            src = os.path.join(OUT_DIR, m)
            im = cv2.imread(src)
            if im is None:
                continue
            cv2.imwrite(os.path.join(dst, m), im)
            n_put[d] = n_put.get(d, 0) + 1
    borrowed = labels.get("_borrowed") or {}
    notes = []
    for d, src in borrowed.items():
        if str(d).startswith("_"):
            continue
        d = int(d)                      # JSON 的键是字符串 -> 统一成 int,不然排序会炸
        rel = os.path.join(PROJECT_ROOT, src)
        im = cv2.imread(rel)
        if im is None:
            print(f"⚠️ 借来的原型读不到: {src}")
            continue
        dst = os.path.join(BANK_DIR, str(d))
        os.makedirs(dst, exist_ok=True)
        cv2.imwrite(os.path.join(dst, "borrowed_" + os.path.basename(src)), im)
        n_put[d] = n_put.get(d, 0) + 1
        notes.append(f"{d} <- {src}")
    with open(os.path.join(BANK_DIR, "BORROWED.txt"), "w", encoding="utf-8") as fh:
        fh.write("这些原型不是从实机语料采的,是从别处借的:\n")
        for n in notes:
            fh.write("  " + n + "\n")
        fh.write(borrowed.get("_why", "") + "\n")
    print("模板库写好:", {k: n_put[k] for k in sorted(n_put)})
    print("缺的数字:", [d for d in range(10) if d not in n_put])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--action", default="cluster",
                    choices=["collect", "cluster", "montage", "build", "all"])
    args = ap.parse_args()
    if args.action in ("collect", "all"):
        collect()
    if args.action in ("cluster", "all"):
        cluster()
    if args.action in ("montage", "all"):
        montage()
    if args.action in ("build", "all"):
        build()
    return 0


def _load_index():
    path = os.path.join(OUT_DIR, "index.jsonl")
    if not os.path.exists(path):
        print("先跑 --action collect")
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def cluster():
    """按形状聚类(贪心),每个簇拼一行,便于人眼贴标签。"""
    recs = _load_index()
    if not recs:
        return
    imgs = {}
    for r in recs:
        p = os.path.join(OUT_DIR, r["png"])
        im = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        if im is not None:
            imgs[r["png"]] = _norm(im)
    groups = []           # [(proto, [png...])]
    for png, im in imgs.items():
        best, bs = None, -2
        for g in groups:
            s = float(cv2.matchTemplate(im.astype(np.float32),
                                        g[0].astype(np.float32),
                                        cv2.TM_CCOEFF_NORMED)[0, 0])
            if s > bs:
                best, bs = g, s
        if best is not None and bs >= CLUSTER_THR:
            best[1].append(png)
        else:
            groups.append((im, [png]))
    groups.sort(key=lambda g: -len(g[1]))
    print(f"{len(imgs)} 个字形 -> {len(groups)} 个形状簇(阈值 {CLUSTER_THR})")
    rows = []
    for gi, (proto, members) in enumerate(groups):
        tiles = [cv2.resize(proto, (64, 64), interpolation=cv2.INTER_NEAREST)]
        for m in members[:5]:
            tiles.append(cv2.resize(imgs[m], (64, 64), interpolation=cv2.INTER_NEAREST))
        while len(tiles) < 6:
            tiles.append(np.zeros((64, 64), np.uint8))
        row = np.hstack([cv2.cvtColor(t, cv2.COLOR_GRAY2BGR) for t in tiles])
        for t, m in zip(row[:64].T, []):
            pass
        cv2.putText(row, f"#{gi} n={len(members)}", (3, 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
        rows.append(row)
    for k in range(0, len(rows), 10):
        chunk = rows[k:k + 10]
        while len(chunk) % 2:
            chunk.append(np.zeros_like(chunk[0]))
        out = np.vstack([np.hstack(chunk[i:i + 2]) for i in range(0, len(chunk), 2)])
        p = os.path.join(OUT_DIR, "clusters_%02d.png" % (k // 10))
        cv2.imwrite(p, out)
        print("  写好", os.path.relpath(p, PROJECT_ROOT))
    with open(os.path.join(OUT_DIR, "clusters.json"), "w", encoding="utf-8") as fh:
        json.dump([[m for m in g[1]] for g in groups], fh, ensure_ascii=False, indent=1)


def montage():
    """按帧拼图:盾牌 + 抠出来的字形(核对"抠对没有")。"""
    recs = _load_index()
    by = {}
    for r in recs:
        by.setdefault(r["frame"], []).append(r)
    rows = []
    for frame, rs in sorted(by.items()):
        rs.sort(key=lambda r: r["glyph"])
        sh = cv2.imread(os.path.join(OUT_DIR, rs[0]["png"].replace("_g0", "_shield")))
        col = [cv2.resize(sh, (110, 110), interpolation=cv2.INTER_CUBIC)] if sh is not None \
            else [np.zeros((110, 110, 3), np.uint8)]
        for r in rs[:3]:
            im = cv2.imread(os.path.join(OUT_DIR, r["png"]))
            col.append(cv2.resize(im, (60, 110), interpolation=cv2.INTER_CUBIC)
                       if im is not None else np.zeros((110, 60, 3), np.uint8))
        while len(col) < 4:
            col.append(np.zeros((110, 60, 3), np.uint8))
        row = np.hstack(col)
        cv2.putText(row, os.path.basename(frame)[5:17], (3, 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 255), 1)
        rows.append(row)
    for k in range(0, len(rows), 9):
        chunk = rows[k:k + 9]
        while len(chunk) % 3:
            chunk.append(np.zeros_like(chunk[0]))
        out = np.vstack([np.hstack(chunk[i:i + 3]) for i in range(0, len(chunk), 3)])
        p = os.path.join(OUT_DIR, "frames_%02d.png" % (k // 9))
        cv2.imwrite(p, out)
        print("  写好", os.path.relpath(p, PROJECT_ROOT))


if __name__ == "__main__":
    sys.exit(main())
