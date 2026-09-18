"""
hand_timing.py - 只读:手牌识别(悬停面板 `_classify`)的**耗时拆解 + A/B**。

为什么需要它(2026-09-13 第九个会话):
  档案里"下一步提速"那一节把大头记成"卡名 OCR 约 1.1s/张"。实测下来
  **两件事都和档案写的不一样**,所以先量再改:

    1. `_classify` 每张卡 ~2.0s,其中 OCR ~1.4s、**类型图标模板匹配 ~0.6s**
       —— 档案里"图标匹配 0.001s/张"说的是**盘面上**那个 23x23 的小牌子;
       这里是在**整块悬停面板**上跑 7 个模板的 `cv2.matchTemplate`。
    2. OCR 的成本**只由输入的长宽比决定**,不是面积:
       detector 是 `limit_side_len=736 / limit_type=min`,把短边放大到 736,
       所以模型输入像素 = 736² × (长边/短边)。
       ⇒ **"把卡名带裁窄"反而更慢**(横带长宽比更差),正解是裁成近正方形。

  这两条都是**反直觉**的,所以本工具把两种行为并排跑:
    `--ab`      老行为(整块 diff bbox) vs 新行为(`NAME_OCR_WINDOW` 近正方窗口)
    `--parts`   拆开量 类型图标 / OCR(det+cls+rec) 各自的耗时
    `--shapes`  只量 detector:同一块图裁成不同长宽比时的纯耗时(成本模型)

只读:不点鼠标、不写文件、不碰游戏窗口。

用法:
  .venv\\Scripts\\python.exe src\\hand_timing.py --ab
  .venv\\Scripts\\python.exe src\\hand_timing.py --parts
  .venv\\Scripts\\python.exe src\\hand_timing.py --shapes
"""

from __future__ import annotations

import glob
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

import hand_scanner_v2 as hs  # noqa: E402
from hand_scanner_v2 import HandScannerV2, _load_db, diff_bbox  # noqa: E402
from ui_state import load_meta, load_templates, match_one  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(PROJECT_ROOT, "shots")


def corpus():
    """
    真实悬停帧语料:(名字, base 帧, hover 帧)。

    两批:
      · `shots/diffdiag/` —— 有配套基准帧(base1/base2)的真实悬停序列(12 对);
      · `shots/probe/`    —— 老一代 52 帧,和 `shots/diff_base.png` 配。
    ★ 老实说:probe 那批和 diff_base 已经对不上(实测 diff 恒为整帧),
      所以它给的 region 就是整帧。留着是因为它**卡名认出来的多**,
      正好当"候选集不许变"的回归集。
    """
    out = []
    for base_name in ("base1.png", "base2.png"):
        base = cv2.imread(os.path.join(SHOTS, "diffdiag", base_name))
        if base is None:
            continue
        for p in sorted(glob.glob(os.path.join(SHOTS, "diffdiag", "hover_*.png"))):
            f = cv2.imread(p)
            if f is None or f.shape != base.shape:
                continue
            box = diff_bbox(base, f)
            if box:
                out.append((f"{base_name}/{os.path.basename(p)}", box, f))
    base = cv2.imread(os.path.join(SHOTS, "diff_base.png"))
    if base is not None:
        for p in sorted(glob.glob(os.path.join(SHOTS, "probe", "probe_*.png"))):
            f = cv2.imread(p)
            if f is None or f.shape != base.shape:
                continue
            box = diff_bbox(base, f)
            if box:
                out.append((f"diff_base/{os.path.basename(p)}", box, f))
    return out


def warmup(sc):
    """先把 OCR 引擎和模板匹配热起来,否则第一张卡的耗时全是初始化。"""
    frame = cv2.imread(os.path.join(SHOTS, "live_probe.png"))
    if frame is None:
        frame = cv2.imread(os.path.join(SHOTS, "diffdiag", "hover_x460.png"))
    sc._classify(frame[:200, :300].copy(), y0=0, box=(0, 0, 300, 200), frame=frame)


def result_key(info):
    return (info.get("name"), info.get("type"), info.get("cost"))


def ab(sc, frames, reps=1):
    print("=" * 100)
    print("A/B:整块 diff bbox(老) vs 近正方窗口(新)")
    print("=" * 100)
    hs.NAME_OCR_WINDOW = False
    old = {}
    t_old = 0.0
    for i, (name, box, f) in enumerate(frames):
        x, y, w, h = box
        for _ in range(reps):
            t = time.time()
            info = sc._classify(f[y:y + h, x:x + w], y0=y, box=box, frame=f)
            t_old += time.time() - t
        old[name] = info
    hs.NAME_OCR_WINDOW = True
    new = {}
    t_new = 0.0
    win_narrow = win_full = 0
    for name, box, f in frames:
        x, y, w, h = box
        for _ in range(reps):
            t = time.time()
            info = sc._classify(f[y:y + h, x:x + w], y0=y, box=box, frame=f)
            t_new += time.time() - t
        new[name] = info
        if info.get("ocr_window") == "narrow":
            win_narrow += 1
        else:
            win_full += 1
    n = len(frames)
    diffs = []
    for name, box, f in frames:
        o, w_ = old[name], new[name]
        if result_key(o) != result_key(w_):
            diffs.append((name, box, o, w_))
    print(f"帧数 {n}(重复 {reps} 次)")
    print(f"老行为 总 {t_old:6.1f}s  平均 {t_old / (n * reps):5.2f}s/张")
    print(f"新行为 总 {t_new:6.1f}s  平均 {t_new / (n * reps):5.2f}s/张"
          f"   -> 快了 {t_old / max(t_new, 1e-9):.2f}x")
    print(f"新行为里走窄窗口 {win_narrow} 帧 / 退回整块 {win_full} 帧")
    print(f"\n★ 结果不同的帧:{len(diffs)} / {n}")
    for name, box, o, w_ in diffs:
        print(f"  {name}  box={box}")
        print(f"     老: name={o.get('name')!r} type={o.get('type')!r} cost={o.get('cost')!r}")
        print(f"     新: name={w_.get('name')!r} type={w_.get('type')!r} cost={w_.get('cost')!r}")
    if not diffs:
        print("   (一个都没有 —— 候选集没变)")
    return len(diffs)


def parts(sc, frames):
    print()
    print("=" * 100)
    print("耗时拆解:类型图标模板匹配 vs OCR(det/cls/rec)")
    print("=" * 100)
    import hover_card_reader as hcr
    eng = hcr._OCR_ENGINE
    t_icon = t_det = t_cls = t_rec = 0.0
    t_cls_all = 0.0
    for name, box, f in frames:
        x, y, w, h = box
        region = f[y:y + h, x:x + w]
        hs.NAME_OCR_WINDOW = True
        narrow = sc._name_window(region, y, box)
        win = region if narrow is None else narrow
        t = time.time()
        for nm in sc.icon_names:
            match_one(win, sc.templates[nm])
        t_icon += time.time() - t
        z0 = min(win.shape[0], hs.NAME_ZONE_MAX_Y - y)
        zone = win[:z0, :] if z0 > 0 else win[:0, :]
        t = time.time()
        res, el = eng(zone)
        t_cls_all += time.time() - t
        t_det += el[0]
        t_cls += el[1]
        t_rec += el[2]
    n = len(frames)
    print(f"{n} 帧,新窗口下:")
    print(f"  类型图标 7 模板匹配   {t_icon / n:5.2f}s/张")
    print(f"  OCR 合计              {t_cls_all / n:5.2f}s/张")
    print(f"     ├ 文本检测 det      {t_det / n:5.2f}s")
    print(f"     ├ 方向分类 cls      {t_cls / n:5.2f}s")
    print(f"     └ 文字识别 rec      {t_rec / n:5.2f}s")
    print(f"  ------------------------------")
    print(f"  合计                  {(t_icon + t_cls_all) / n:5.2f}s/张")


def shapes(frames):
    print()
    print("=" * 100)
    print("成本模型:detector 的纯耗时 vs 输入长宽比")
    print("=" * 100)
    import hover_card_reader as hcr
    eng = hcr._OCR_ENGINE
    det = eng.text_detector
    name, box, f = frames[0]
    x, y, w, h = box
    region = f[y:y + h, x:x + w]
    cases = [
        ("整块 diff bbox", region),
        ("旧 zone y<550(整宽)", region[:max(1, 550 - y), :]),
        ("新窗口 x300-980/y<600", sc_win(region, y, box)),
    ]
    # 追加几个"教具"形状,把长宽比这一维单独摆出来
    z = region[:550, :] if region.shape[0] >= 550 else region
    if z.shape[1] >= 1138 and z.shape[0] >= 550:
        cases += [
            ("教具 1138x550 (1:2.07)", z[:550, :1138]),
            ("教具  550x550 (1:1.00)", z[:550, :550]),
            ("教具  192x1138 (1:5.93)", region[180:372, :1138] if region.shape[0] >= 372 else z[:192, :1138]),
        ]
    print(f"{'形状':<26}{'尺寸':>12}{'长宽比':>8}{'模型输入':>10}{'det':>9}")
    for label, img in cases:
        if img is None or img.size == 0:
            continue
        hh, ww = img.shape[:2]
        M, m = max(hh, ww), min(hh, ww)
        px = 736 * 736 * M / m
        ts = []
        for _ in range(3):
            _, el = det(img)
            ts.append(el)
        print(f"{label:<26}{f'{ww}x{hh}':>12}{M / m:>8.2f}{px / 1e6:>9.2f}M"
              f"{min(ts):>8.3f}s   (中位 {statistics.median(ts):.3f}s)")


def sc_win(region, y, box):
    rx0 = box[0]
    h, w = region.shape[:2]
    c0 = max(0, hs.NAME_OCR_X0 - rx0)
    c1 = min(w, hs.NAME_OCR_X1 - rx0)
    r1 = min(h, max(0, hs.NAME_OCR_Y1 - y))
    return region[:r1, c0:c1]


def main(argv):
    meta = load_meta(os.path.join(PROJECT_ROOT, "config", "templates.json"))
    tpls = load_templates(meta)
    _load_db()
    import hover_card_reader as hcr
    hcr._ocr(cv2.imread(os.path.join(SHOTS, "live_probe.png"))[:64, :64])
    sc = HandScannerV2(0, tpls)
    frames = corpus()
    if not frames:
        print("没有可用帧(shots/diffdiag 或 shots/probe)")
        return 1
    which = set(a for a in argv if a.startswith("--"))
    if not which:
        which = {"--ab"}
    if "--shapes" in which:
        shapes(frames)
    if "--parts" in which:
        parts(sc, frames)
    if "--ab" in which:
        ab(sc, frames)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
