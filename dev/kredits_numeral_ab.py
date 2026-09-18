"""
kredits_numeral_ab.py - 只读 A/B:两位数字形的"合并规则 + 高度护栏",在同一批真实帧上比。

为什么要这个工具
----------------
2026-09-13 晚发现的真 bug:费用 **11 读成 1**。地面真值帧(画面上明明白白 "11 K/11"):

    shots/attack_frames/0913_191731_attack.png     0913 那一局 19:17
    shots/attack_probe/0912_0036{10,24,28}_*.png   0912 那一局 00:36
    shots/deploy_drag/0913_17{37,28}*.png          0913 两局
    shots/mouse_field/{A_asis,B_safepoint}.png
    shots/kredits/samples/plates/n_34_plate.png    2026-09-10 录的 plate(真值 11)

老规则 `isolate_numeral` 只圈到了左边那个 "1":

    帧里的橙色块: (10,12,10,25)  第 1 个 "1"
                  (26,12,10,25)  第 2 个 "1"      <- 合不进来
                  (47,10, 9,13)  "K/M" 徽章
    老判据: `abs(p.x - anchor.x) <= max(w) * 1.2`   —— **拿字形自己的宽度当尺子**
            |26-10| = 16  >  10*1.2 = 12      -> 第 2 个 "1" 被丢掉 -> 读成 1
    于是"10"/"12" 一直是对的(第二个字形**胖**,17~18px:14 <= 20.4 / 13 <= 21.6 ✓),
    **实测钉住读错的只有 "11"**(两个字形都窄:16 > 12);"21"/"31" 落在容差边缘
    (约 21 vs 20.4)—— 所以它躲过了所有抽查。

改法两层(互相独立,这一轮都落了地)
------------------------------------
① `kredits.MERGE_MODE="struct"` —— 合并改按**数字自己的高度**定尺:
     竖向重叠 >= 0.7·高  **且**  水平空隙 <= 0.8·高
   (徽章恒为 9x13,压在 25 高的数字上只占 44% -> 被这条**结构判据**挡掉)
   ★ 老规则一条都不撤销(两条是"或"),所以"今天能读对的帧"必须一张都不变。

② `kredits.HEIGHT_GUARD` —— **高度与段数自相矛盾时不许猜**:
   实测单位数高 33~37px,两位数只有 25px。所以"只切出一段、高度却 <= 30px"
   只能是两位数的第一个字 -> 返回 None,让上层退回"上次采用值 +1"。

用法
----
  .venv\\Scripts\\python.exe src\\kredits_numeral_ab.py            # 全语料 A/B
  .venv\\Scripts\\python.exe src\\kredits_numeral_ab.py --verbose  # 逐帧列出几何证据
  .venv\\Scripts\\python.exe src\\kredits_numeral_ab.py --sheet    # 拼改前/改后对照图

★ 本工具**只读**(不碰窗口;只往 shots/kredits/ 里写一张对照图,且要 --sheet)。
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np

import kredits as K

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "shots")
SHEET = os.path.join(SHOTS, "kredits", "numeral_ab.png")

# 地面真值(**逐个看图核对**过,不是按文件名推的):文件名 -> 画面上真实的剩余费用
GROUND_TRUTH = {
    # 2026-09-13 19:17 那一局(就是交接文档里那条 "[不采信] 采样 [1,3,5,1,1,1,…]")
    "0913_191731_attack.png": 11,
    "0913_173740_x434.png": 11,
    "0913_182801_x530.png": 11,
    "0913_182909_x703.png": 11,        # 这一帧是 11 K/12(剩余 11)
    # 2026-09-12 00:36 那一局
    "0912_003610_probe.png": 11,
    "0912_003624_probe.png": 11,
    "0912_003628_movefront.png": 11,
    # 只读探针存的帧
    "A_asis.png": 11,
    "B_safepoint.png": 11,
    # 2026-09-10 录制的那批 plate(真值来自逐个看图:n_32=10 / n_34=11 / n_36=12)
    "n_32_plate.png": 10,
    "n_34_plate.png": 11,
    "n_36_plate.png": 12,
    "0911_122530_004_anchor.png": 10,
    "0911_122530_005_anchor.png": 10,
    "0912_192728_attack_ab.png": 12,
    "0912_192745_after_ab.png": 12,
    "005_175833_10.png": 10,           # 滚动中的两位数帧(费用区域裁图)
    "007_175834_10.png": 10,
}

# 三档配置:(名字, merge_mode, height_guard)
VARIANTS = (
    ("老(宽度合并,无护栏)", K.MERGE_MODE_OLD, False),
    ("只加高度护栏", K.MERGE_MODE_OLD, True),
    ("新(结构合并 + 护栏)", K.MERGE_MODE_STRUCT, True),
)


def full_frames():
    """整帧语料:生产路径用的就是这些(1280x720,读 OURS_BOX)。"""
    out = []
    for f in sorted(glob.glob(os.path.join(SHOTS, "**", "*.png"), recursive=True)):
        img = cv2.imread(f)
        if img is None or img.shape[1] < 1000 or img.shape[0] < 600:
            continue
        out.append((f, img, K.OURS_BOX))
    return out


def plate_crops():
    """费用区域裁图语料:人工/探针存下来的那几批(整张图就是费用区域)。"""
    pats = [
        os.path.join(SHOTS, "kredits_anim", "*.png"),
        os.path.join(SHOTS, "kredits_anim2", "*.png"),
        os.path.join(SHOTS, "kredits", "samples", "plates", "*.png"),
        os.path.join(SHOTS, "kredits", "numerals", "numeral_*.png"),
    ]
    out = []
    for pat in pats:
        for f in sorted(glob.glob(pat)):
            if "_strip" in f or "_mask" in f:
                continue
            img = cv2.imread(f)
            if img is None:
                continue
            h, w = img.shape[:2]
            out.append((f, img, (0, 0, w, h)))
    return out


def probe(frame, box, mode, guard):
    """跑一次隔离 + 判读,把中间量一起带回来(便于解释差异)。"""
    import kredits_templates as kt

    _numeral, mask, bbox = K.isolate_numeral(frame, box, merge_mode=mode)
    if mask is None:
        return {"bbox": None, "segs": 0, "value": None}
    segs = kt.split_glyphs(mask)
    value = K.read_kredits(frame, box, merge_mode=mode, height_guard=guard)
    return {"bbox": bbox, "segs": len(segs), "value": value}


def pieces_of(frame, box):
    """把 box 里所有"够大"的橙色连通域列出来(合并规则就是在这些块上做判断的)。"""
    x1, y1, x2, y2 = box
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return []
    b, g, r = (crop[:, :, i].astype(int) for i in range(3))
    orange = ((r > 130) & (r - b > 50) & (g > 50)).astype(np.uint8)
    n, _lab, stats, _ = cv2.connectedComponentsWithStats(orange, 8)
    out = []
    for i in range(1, n):
        if int(stats[i, cv2.CC_STAT_AREA]) < 40:
            continue
        out.append((int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP]),
                    int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT]),
                    int(stats[i, cv2.CC_STAT_AREA])))
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true", help="逐帧打印几何与判据")
    ap.add_argument("--sheet", action="store_true", help="拼一张改前/改后对照图")
    args = ap.parse_args()

    corpus = [("整帧", full_frames()), ("费用区域裁图", plate_crops())]

    print("=" * 88)
    print("两位数字形 A/B(三层对照):")
    print(f"  老             = merge={K.MERGE_MODE_OLD!r} "
          f"(横向 <= 字形宽 * {K.MERGE_WIDTH_RATIO}),无高度护栏")
    print(f"  只加高度护栏   = 同上去掉猜(段数=1 且 高 <= {K.TWO_DIGIT_H_MAX}px -> None)")
    print(f"  新             = merge={K.MERGE_MODE_STRUCT!r}"
          f"(竖向共高 >= {K.MERGE_MIN_VOVER}·高 且 空隙 <= {K.MERGE_MAX_GAP}·高)+ 护栏")
    print("=" * 88)

    total = 0
    diffs = []
    variants_diff = []
    truth_rows = []
    truth_bad = []
    for label, frames in corpus:
        print()
        print(f"--- {label}:{len(frames)} 张 ---")
        for f, img, box in frames:
            total += 1
            res = [probe(img, box, m, g) for _n, m, g in VARIANTS]
            name = os.path.basename(f)
            if res[0]["bbox"] != res[2]["bbox"]:
                diffs.append((label, f, res, box))
            values = [r["value"] for r in res]
            if len(set(values)) > 1:
                variants_diff.append((label, f, values))
            truth = GROUND_TRUTH.get(name)
            if truth is not None:
                ok = ["OK " if r["value"] == truth else "FAIL" for r in res]
                print(f"    [真值 {truth:>2}] " + " | ".join(
                    f"{n.split('(')[0].strip()}={str(r['value']):>4} {o}"
                    for (n, _m, _g), r, o in zip(VARIANTS, res, ok)) + f"   {name}")
                truth_rows.append((name, truth, values))
                if res[2]["value"] != truth:
                    truth_bad.append((name, truth, res[2]["value"]))
            elif args.verbose and (res[0]["bbox"] != res[2]["bbox"]
                                   or (res[2]["bbox"] and res[2]["bbox"][3] <= 32)):
                print(f"    {name}: 块={pieces_of(img, box)}")
                for (n, _m, _g), r in zip(VARIANTS, res):
                    print(f"        {n:<22} bbox={r['bbox']} 段={r['segs']} "
                          f"读={r['value']}")

    print()
    print("=" * 88)
    print(f"语料合计 {total} 张")
    print(f"**隔离框(bbox)不同的帧: {len(diffs)}**")
    for label, f, res, box in diffs:
        rel = os.path.relpath(f, ROOT)
        print(f"  · {rel}")
        print(f"      块     : {pieces_of(cv2.imread(f), box)}")
        for (n, _m, _g), r in zip(VARIANTS, res):
            print(f"      {n:<22} bbox={r['bbox']}  段 {r['segs']}  读 {r['value']}")
    print(f"**三档里判读值有分歧的帧: {len(variants_diff)}**(全在上面那张真值表里)")

    print()
    print("=" * 88)
    print("地面真值帧逐张(这是本次改动的验收面):")
    print(f"{'帧':<38}{'真值':<6}{'老':<8}{'只加护栏':<10}{'新':<8}结论")
    print("-" * 88)
    for name, truth, values in truth_rows:
        verdict = "✅" if values[2] == truth else "❌"
        print(f"{name:<38}{truth:<6}{str(values[0]):<8}{str(values[1]):<10}"
              f"{str(values[2]):<8}{verdict}")
    print("-" * 88)
    if truth_bad:
        print(f"❌ 新规则在 {len(truth_bad)} 张真值帧上仍读错:{truth_bad}")
    else:
        print(f"✅ 新规则在 {len(truth_rows)} 张地面真值帧上**全对**。")
    print()
    print("判据:① 真值帧全对;② **除了那批 '11' 之外,其余帧一张都不许变**。")
    print("      任何额外变化都要逐帧看过再决定收不收(--verbose 有逐帧几何)。")

    if args.sheet and diffs:
        rows = []
        for label, f, res, box in diffs[:12]:
            img = cv2.imread(f)
            x1, y1, x2, y2 = box
            crop = img[y1:y2, x1:x2].copy()
            for r, color in ((res[0], (0, 0, 255)), (res[2], (0, 255, 0))):
                if r["bbox"] is None:
                    continue
                bx, by, bw, bh = r["bbox"]
                cv2.rectangle(crop, (bx - x1 - 2, by - y1 - 2),
                              (bx - x1 + bw + 2, by - y1 + bh + 2), color, 1)
            crop = cv2.resize(crop, None, fx=2.2, fy=2.2,
                              interpolation=cv2.INTER_NEAREST)
            cv2.putText(crop, f"old={res[0]['value']} new={res[2]['value']}",
                        (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1,
                        cv2.LINE_AA)
            rows.append(crop)
        wmax = max(r.shape[1] for r in rows)
        sheet = np.zeros((sum(r.shape[0] + 6 for r in rows), wmax, 3), dtype=np.uint8)
        y = 0
        for r in rows:
            sheet[y:y + r.shape[0], :r.shape[1]] = r
            y += r.shape[0] + 6
        os.makedirs(os.path.dirname(SHEET), exist_ok=True)
        cv2.imwrite(SHEET, sheet)
        print(f"\n对照图已存: {os.path.relpath(SHEET, ROOT)}(红=老框,绿=新框)")
    return 0 if not truth_bad else 1


if __name__ == "__main__":
    sys.exit(main())
