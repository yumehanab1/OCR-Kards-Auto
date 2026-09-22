"""
hand_live_probe.py - 只读实机探针:把"扫描器看到了什么"逐探针摊开。

为什么需要它(2026-09-13 第十个会话)
------------------------------------
用户逐回合观察报回来一串症状,全都指向**手牌这一路**:
  · 指令卡(鹰爪,cost 3 / type=order)被当成**单位**拖出去;
  · `38(t) 坦克`(tank/3)被扫到却跳过部署;
  · 有费用却不出牌;
  · **落点/抓点错位**:"百舌鸟没下,把他旁边的 38t 打出去了"。

而现有日志**看不见证据**:`deploying Fw 190 A 百舌鸟 (fighter, cost 6)`
只写了结论,没写"凭什么认定它是百舌鸟"(卡名 OCR 原文?第几级匹配?图标分多少?
费用是查库来的还是徽章兜底?指纹库命中?)。
于是一旦判错,日志里和判对**长得一模一样** —— 这正是本项目反复吃亏的
"静默失败"那一类。

本工具**只移动鼠标,绝不点击**(不会部署、不会结束回合),把下面这些摊开:
  1. 光标停在安全点时测到的扇形左边缘 + 命中的布局条目(纯中立态);
  2. **中立态整帧**(`base.png`)—— 用来人眼核对每个探针 x 落在**哪张牌**上;
  3. 每个探针 x 的悬停帧 + 分类结果:
       卡名 / 类型 / 费用 / 匹配级别 / OCR 原文行(含 conf,y,h)
       7 个类型图标的**逐个分数**(谁赢、赢多少 —— 阈值 0.65 那条线的证据)
       费用来源(查库 / 徽章兜底 / 指纹库)
     ★ 悬停帧会把 x 画成竖线存盘(`hov_x<px>.png`),人眼即可判断
       "分类器说的这张牌"和"画面上被抬起的那张牌"是不是同一张。
  4. 一张把**所有探针 x + 左边缘**画在中立态上的图(`base_marked.png`)。

用法:
  .venv\\Scripts\\python.exe dev\\hand_live_probe.py                 # 当前命中布局的探针
  .venv\\Scripts\\python.exe dev\\hand_live_probe.py --sweep 24      # 再补一遍粗扫(每 24px)
  .venv\\Scripts\\python.exe dev\\hand_live_probe.py --layout 390    # 指定布局条目
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

import hand_scanner_v2 as hs  # noqa: E402
from hand_scanner_v2 import (HandScannerV2, NAME_ZONE_MAX_Y,  # noqa: E402
                             NAME_ZONE_MAX_Y_SPECIAL, _load_db, diff_bbox)
from hover_card_reader import _ocr  # noqa: E402
from ui_state import load_meta, load_templates, match_one  # noqa: E402
from win import (bring_to_front, capture_client_bgr,  # noqa: E402
                 find_by_process, set_dpi_aware)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT_ROOT, "shots", "hand_live")
HAND_STRIP = (600, 720)          # 手牌扇形所在的 y 带(client 坐标)


def _ensure_out():
    os.makedirs(OUT_DIR, exist_ok=True)


def _line(img, x, color=(0, 0, 255), thick=1, label=None):
    h = img.shape[0]
    cv2.line(img, (int(x), 0), (int(x), h - 1), color, thick)
    if label:
        cv2.putText(img, label, (int(x) + 2, 14), cv2.FONT_HERSHEY_SIMPLEX,
                    0.4, color, 1, cv2.LINE_AA)


def icon_scores(scanner, region, y0=0, box=None):
    """7 个类型图标在这一块图上的**逐个分数**(复刻 _classify_core 第 1 步)。"""
    narrow = scanner._name_window(region, y0, box)
    win = region if narrow is None else narrow
    out = []
    for nm in scanner.icon_names:
        s, reg = match_one(win, scanner.templates[nm])
        out.append((nm.replace("_icon", ""), round(float(s), 3), reg))
    out.sort(key=lambda t: -t[1])
    return out, ("narrow" if narrow is not None else "full"), win.shape


def probe_one(scanner, px, tag, save_frame=True, verbose=True):
    """
    在中立态 -> 悬停 px 之间做一次**只读**悬停,返回 (info, box, frame)。
    """
    scanner._move(*scanner.safe)
    time.sleep(hs.SAFE_SETTLE)
    base = capture_client_bgr(scanner.hwnd)
    scanner._move(px, scanner.y)
    time.sleep(scanner.hold)
    hover = capture_client_bgr(scanner.hwnd)
    if base is None or hover is None:
        return None, None, None
    box = diff_bbox(base, hover)
    if box is None:
        print(f"  x={px:<5} [{tag}] **没有差分**(悬停没弹出面板?)")
        return None, None, hover
    bx, by, bw, bh = box
    region = hover[by:by + bh, bx:bx + bw]
    info = scanner._classify(region, y0=by, box=box, frame=hover)
    if verbose:
        print(f"  x={px:<5} [{tag}] box={box} "
              f"name={info.get('name')!r} type={info.get('type')!r} "
              f"cost={info.get('cost')!r} tier={info.get('name_tier')!r} "
              f"窗口={info.get('ocr_window')} "
              f"icon={info.get('icon_score')} cost_src={info.get('cost_source')} "
              f"hash_dist={info.get('hash_hit_distance')}")
        scores, which, shape = icon_scores(scanner, region, y0=by, box=box)
        print("        " + which + f" {shape[1]}x{shape[0]} 图标分: "
              + "  ".join(f"{n}={s}" for n, s, _ in scores))
        # OCR 原文(含 conf / y / 行高)—— "读不出卡名"到底是没读到还是没匹配上
        special = scores[0][0] in ("order", "counter") if scores else False
        zmax = NAME_ZONE_MAX_Y_SPECIAL if special else NAME_ZONE_MAX_Y
        z0 = zmax - by
        zone = region[:z0, :] if z0 > 0 else region[:0, :]
        lines = _ocr(zone) if zone.size else []
        print(f"        OCR zone y<{zmax} (h={zone.shape[0]}) 行数 {len(lines)}: "
              + (" | ".join(f"{ln['text']!r}(conf{ln['conf']:.2f},y{int(ln.get('y', 0))},h{int(ln.get('h', 0))})"
                            for ln in lines[:8]) if lines else "(空)"))
    if save_frame:
        vis = hover.copy()
        _line(vis, px, (0, 0, 255), 1, f"x{px}")
        cv2.rectangle(vis, (bx, by), (bx + bw, by + bh), (0, 255, 0), 1)
        cv2.imwrite(os.path.join(OUT_DIR, f"hov_x{px:04d}_{tag}.png"), vis)
    return info, box, hover


def hand_strip_diff_x(base, hover):
    """中立态 vs 悬停态在**手牌那一条**上的差分 x 范围(被抬起的牌动过的地方)。"""
    if base is None or hover is None or base.shape != hover.shape:
        return None
    y0, y1 = HAND_STRIP
    d = cv2.absdiff(base, hover)[y0:y1]
    g = cv2.cvtColor(d, cv2.COLOR_BGR2GRAY)
    mask = g > hs.DIFF_THRESH
    if mask.sum() < 50:
        return None
    ys, xs = mask.nonzero()
    return int(xs.min()), int(xs.max()), int(mask.sum())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", type=int, default=0,
                    help="额外粗扫的步长(px);0 = 不粗扫")
    ap.add_argument("--layout", default="", help="只用这个布局条目(如 390)")
    ap.add_argument("--no-frames", action="store_true", help="不存悬停帧")
    args = ap.parse_args()

    _ensure_out()
    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("no kards window")
        return 1
    hwnd = wins[0]["hwnd"]
    bring_to_front(hwnd)
    time.sleep(0.4)
    frame = capture_client_bgr(hwnd)
    if frame is None:
        print("抓不到画面(窗口最小化/被遮挡?)")
        return 1
    print(f"客户区 {frame.shape[1]}x{frame.shape[0]}")
    if (frame.shape[1], frame.shape[0]) != (1280, 720):
        print("⚠️ 客户区不是 1280x720 —— 所有模板/探针都不可信,先跑 main_loop 或 live_probe 强制尺寸")
        return 1

    tpls = load_templates(load_meta(os.path.join(PROJECT_ROOT, "config",
                                                "templates.json")))
    _load_db()
    scanner = HandScannerV2(hwnd, tpls)

    # ---- 中立态基准 ----
    scanner._move(*scanner.safe)
    time.sleep(0.5)
    base = capture_client_bgr(hwnd)
    cv2.imwrite(os.path.join(OUT_DIR, "base.png"), base)
    from hand_calibrate import detect_edges
    le, re_ = detect_edges(base)
    print(f"中立态(光标在安全点):左边缘 {le} / 右边缘 {re_}")
    layouts = scanner._load_layouts()
    cands = sorted((v for v in layouts.values()
                    if abs(v.get("left_edge", -999) - le) <= hs.LAYOUT_EDGE_TOL),
                   key=lambda v: abs(v["left_edge"] - le))
    print(f"容差 {hs.LAYOUT_EDGE_TOL} 内的布局候选 {len(cands)} 个:")
    for v in cands:
        print(f"   count={v['count']} left_edge={v['left_edge']} "
              f"probes={v.get('probes')}")
    if not cands:
        near = min(layouts.values(), key=lambda v: abs(v["left_edge"] - le))
        print(f"  **一个都不在容差内**;最近的是 count={near['count']} "
              f"left_edge={near['left_edge']}(差 {abs(near['left_edge'] - le)}px)")
        print("  -> 惰性扫描这时会走**整手盲扫兜底**")
    if args.layout:
        pick = layouts.get(args.layout)
        if pick is None:
            print(f"没有布局条目 {args.layout}")
            return 1
    else:
        pick = cands[0] if cands else None

    # 中立态 + 探针竖线,人眼核对"探针落在哪张牌上"
    marked = base.copy()
    _line(marked, le, (255, 128, 0), 2, f"L{le}")
    if pick:
        for px in pick.get("probes", []):
            _line(marked, px, (0, 255, 0), 1, str(px))
    cv2.imwrite(os.path.join(OUT_DIR, "base_marked.png"), marked)

    # ---- 逐探针 ----
    if pick:
        print(f"\n=== 布局「{pick['count']} 张」的探针 ===")
        for px in pick.get("probes", []):
            probe_one(scanner, px, f"L{pick['count']}",
                      save_frame=not args.no_frames)

    # ---- 粗扫:热区边界(= 相邻两张牌的分界)在哪 ----
    if args.sweep > 0:
        print(f"\n=== 粗扫(步长 {args.sweep}px):看热区边界 ===")
        print(f"{'x':>6}  {'手牌带差分 x 范围':>22}  卡名")
        for px in range(340, 921, args.sweep):
            scanner._move(*scanner.safe)
            time.sleep(hs.SAFE_SETTLE)
            b = capture_client_bgr(hwnd)
            scanner._move(px, scanner.y)
            time.sleep(scanner.hold)
            h = capture_client_bgr(hwnd)
            if b is None or h is None:
                continue
            box = diff_bbox(b, h)
            rng = hand_strip_diff_x(b, h)
            info = None
            if box is not None:
                bx, by, bw, bh = box
                info = scanner._classify(h[by:by + bh, bx:bx + bw], y0=by,
                                         box=box, frame=h)
            print(f"{px:>6}  {str(rng):>22}  "
                  f"{info.get('name') if info else '(无面板)'}"
                  f"  type={info.get('type') if info else None}"
                  f"  cost={info.get('cost') if info else None}")

    scanner._move(*scanner.safe)
    print(f"\n只读探针结束(没有点过任何东西)。产物在 {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
