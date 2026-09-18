"""
hand_calibrate.py - 采集"手牌张数 -> 每张牌悬停坐标"对照表。

为什么要这张表
--------------
盲扫要在 x=340~920 打 49 个探针逐个试探有没有面板,实测一次 121 秒,而
KARDS 一个回合有时限,根本来不及。但手牌扇形是【居中布局】:张数决定几何
位置,每种张数下每张牌的中心点都是固定的。所以只要知道张数,就能直接去
悬停那几张牌,跳过所有空白探针(7 张牌约 13 秒)。

张数怎么知道:用【扇形左边缘的 x】反查。张数越少扇形越窄、左边缘越靠右,
单调对应。实测手牌居中于屏幕中心(x≈640)。

本脚本做什么
------------
只读、不部署。它持续监测左边缘 x,对每个新出现的左边缘值跑一次"只找热区
位置、不做 OCR"的扫描(约 25 秒,比完整扫描快得多),记录:

    左边缘 x  ->  手牌张数 + 每张牌的悬停 x 坐标

结果存到 config/hand_layout.json,供快速扫描器使用。

用法(在对局里跑,正常玩即可):
  .venv\\Scripts\\python.exe src\\hand_calibrate.py --seconds 900

采集期间脚本会提示"正在扫描,请暂时不要出牌"。手牌张数在对局中自然变化
(每回合抽牌 +1、出牌 -1),多打几个回合就能覆盖常见张数。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np

from actions import cursor_is_moving, set_cursor
from hand_scanner_v2 import (HandScannerV2, PROBE_Y, SAFE_POINT, SAFE_SETTLE,
                             STEP, X0, X1, diff_bbox, _load_db)
from ui_state import classify, load_meta, load_states, load_templates, match_one
from win import (bring_to_front, capture_client_bgr, client_to_screen,
                 find_by_process, set_dpi_aware, set_window_client_size)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_JSON = os.path.join(ROOT, "config", "hand_layout.json")

# 左边缘检测参数(已用真实帧验证:x 得到 458~461)
EDGE_Y0, EDGE_Y1 = 680, 715
EDGE_THRESH = 45
EDGE_X_MIN, EDGE_X_MAX = 150, 1100
BG_SAMPLE = (150, 250)        # 桌面色参考区域(x 范围)
# ★★ 2026-09-11 傍晚实机踩的坑:**扇形最左边那张牌露出来的宽度**是有下限的
#    (实测 ≥70px),而桌面装饰/玩家名/挂件往往是十几像素宽的亮条。
#    原来的判据"第一个连续 6 列超阈值的位置"会被那种装饰骗到 ——
#    实测绿色德式桌面那一局,左下角"手枪装饰 + 玩家名"在 x277..311 造出两段
#    16/18px 的亮区,左边缘就被判成 **277**,而真正的卡面从 **390** 才开始。
#    后果不是"扫得慢",是**整局一张牌都没出**(布局表查不到 -> 惰性扫描直接放弃)。
#    所以加一条:run 宽度不够就不认,继续往后找。
MIN_FAN_RUN_W = 40


def _edge_runs(diff, reverse=False):
    """把"连续 ≥6 列超阈值"的区段都找出来,返回 [(起点, 宽度)],按扫描方向排。"""
    runs = []
    run = 0
    rng = (range(min(EDGE_X_MAX, len(diff)) - 1, EDGE_X_MIN - 1, -1)
           if reverse else range(EDGE_X_MIN, min(EDGE_X_MAX, len(diff))))
    last = None
    for x in rng:
        if diff[x] > EDGE_THRESH:
            run += 1
            last = x
        else:
            if run >= 6:
                # reverse 时 last 是这段的"最左端",x+1 是"最右端"
                start = (x + 1) if reverse else (x - run)
                runs.append((start, run))
            run = 0
    if run >= 6:
        start = (last - run + 1) if reverse else (last - run + 1)
        runs.append((start, run))
    return runs


def detect_left_edge(frame):
    """
    返回手牌扇形左边缘的 x,找不到返回 None。

    做法:在 y 680-715 这段(卡面露出区)逐列比较与桌面背景色的平均差异,
    取第一段**够宽**的连续超阈值区段的起点。

    ★ 2026-09-11 傍晚修:"第一个连续 6 列"会被**桌面装饰**骗到(见 MIN_FAN_RUN_W),
      实测把左边缘判成 277(真值 390),于是布局表查不到 -> **整局不出牌**。
      现在只有宽度 ≥ MIN_FAN_RUN_W 的区段才认;被跳过的会记在
      `detect_left_edge.skipped` 里,方便诊断工具打出来。

    ★ 重要:必须在【鼠标停在 SAFE_POINT、没有悬停任何手牌】时调用。
    KARDS 悬停手牌时会把扇形展开(被悬停的牌上移、其余让位),左边缘会跟着
    变(实测同一副手牌,悬停左边时 x=367、悬停中间时 x=394)。测量条件不一致
    的话,这张对照表就废了。校准和使用两边都要先回 SAFE_POINT。
    """
    x0, x1 = BG_SAMPLE
    bg = frame[EDGE_Y0:EDGE_Y1, x0:x1].reshape(-1, 3).mean(axis=0)
    strip = frame[EDGE_Y0:EDGE_Y1, :].astype(np.int16)
    diff = np.abs(strip - bg).mean(axis=(0, 2))

    runs = _edge_runs(diff, reverse=False)
    detect_left_edge.skipped = [r for r in runs if r[1] < MIN_FAN_RUN_W]
    for start, w in runs:
        if w >= MIN_FAN_RUN_W:
            return start
    return runs[0][0] if runs else None


def detect_right_edge(frame):
    """
    返回手牌扇形右边缘的 x,找不到返回 None。

    与 detect_left_edge 完全对称(从右往左扫)**而且同样要求区段够宽**
    (见 MIN_FAN_RUN_W:右边也可能有装饰,比如右侧那块鹰徽面板)。

    同样要在鼠标停 SAFE_POINT 时调用(见 detect_left_edge 的说明)。
    """
    x0, x1 = BG_SAMPLE
    bg = frame[EDGE_Y0:EDGE_Y1, x0:x1].reshape(-1, 3).mean(axis=0)
    strip = frame[EDGE_Y0:EDGE_Y1, :].astype(np.int16)
    diff = np.abs(strip - bg).mean(axis=(0, 2))

    runs = _edge_runs(diff, reverse=True)
    detect_right_edge.skipped = [r for r in runs if r[1] < MIN_FAN_RUN_W]
    for start, w in runs:
        if w >= MIN_FAN_RUN_W:
            return start + w - 1
    return (runs[0][0] + runs[0][1] - 1) if runs else None


def detect_edges(frame):
    """一次拿到 (左边缘, 右边缘)。"""
    return detect_left_edge(frame), detect_right_edge(frame)


def sample_at_safe(hwnd, scanner=None):
    """
    把鼠标放到 SAFE_POINT(不悬停任何手牌),静置后截图。
    这是测量左边缘的唯一合法条件,校准与使用都必须走这里。

    传 scanner 时会走它的 _move(从而更新 _last_cursor),让行判断才准。
    """
    if scanner is not None:
        scanner._move(*SAFE_POINT)
    else:
        set_cursor(*client_to_screen(hwnd, *SAFE_POINT))
    time.sleep(SAFE_SETTLE)
    return capture_client_bgr(hwnd)


def left_edge_at_safe(hwnd, scanner=None):
    """在标准测量条件下取手牌扇形左边缘。"""
    frame = sample_at_safe(hwnd, scanner)
    if frame is None:
        return None, None
    return detect_left_edge(frame), frame


def scan_hotspots(scanner):
    """
    用现成的扫描器找出每张牌的悬停点,返回 [{x, name, type, cost}, ...]。

    为什么不用"只看 diff 有无"的轻量办法:KARDS 悬停手牌时会把【整个扇形
    重排】(被悬停的牌上移、其余让位),于是 diff 覆盖的是整片手牌区而不是
    单张面板 —— 实测那样得到"热区 x 460-832"(372px 宽),明显不是一张牌。

    现有扫描器用 OCR 结果(name/type)判断"换没换卡",所以不受重排影响,
    实战里已能正确数出 5 张、6 张。代价是要做 OCR,一次较慢。
    """
    return scanner.scan()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=900, help="采集时长(秒)")
    ap.add_argument("--debug", action="store_true", help="打印每次探针")
    ap.add_argument("--min-stable", type=float, default=2.5,
                    help="左边缘需稳定多少秒才认为是同一个张数")
    ap.add_argument("--force", action="store_true", help="已采集过的张数也重新采")
    ap.add_argument("--yield-cooldown", type=float, default=20.0,
                    help="发现你在操作鼠标后,安静这么多秒不碰光标(默认 20)")
    args = ap.parse_args()

    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("找不到 kards 窗口(游戏在运行吗?)")
        return 1
    hwnd = wins[0]["hwnd"]
    print(f"kards hwnd={hwnd}")
    bring_to_front(hwnd)
    time.sleep(0.5)
    set_window_client_size(hwnd, 1280, 720, 100, 100)
    time.sleep(1.0)
    _load_db()
    tpls = load_templates(load_meta(os.path.join(ROOT, "config", "templates.json")))
    states = load_states(os.path.join(ROOT, "config", "states.json"))
    scanner = HandScannerV2(hwnd, tpls)

    # 载入已有结果,支持分次采集
    layouts = {}
    if os.path.exists(OUT_JSON):
        try:
            with open(OUT_JSON, "r", encoding="utf-8") as f:
                layouts = json.load(f).get("layouts", {})
            print(f"已有 {len(layouts)} 条记录,继续补充")
        except Exception:
            pass

    print(f"输出文件:{OUT_JSON}")
    print(f"采集 {args.seconds:.0f} 秒。左边缘稳定 {args.min_stable}s 且没采过就扫一次。")
    print(">>> 只读操作,不会出牌。提示扫描时请暂时不要出牌。")
    print()

    t0 = time.time()
    stable_edge = None
    stable_since = 0.0
    done_edges = []
    scans = 0
    last_user_activity = 0.0      # 最近一次发现用户在操作鼠标的时刻

    while time.time() - t0 < args.seconds:
        # ★ 让路机制(两级)
        # 一级:刚发现你在操作,就安静 args.yield_cooldown 秒,期间完全不碰光标。
        # 二级:冷却结束后先"空手"探一下你有没有在动鼠标(不占位),你一动就
        #       重新开始冷却。这样你不会被反复抢鼠标。
        if time.time() - last_user_activity < args.yield_cooldown:
            time.sleep(0.5)
            continue
        if cursor_is_moving():
            last_user_activity = time.time()
            stable_edge, stable_since = None, 0.0
            print(f">>> 检测到你在操作鼠标,退让 {args.yield_cooldown:.0f} 秒")
            continue
        # 扫描/监测途中你一动手就立刻中止
        if scanner.user_took_over():
            last_user_activity = time.time()
            stable_edge, stable_since = None, 0.0
            continue

        edge, frame = left_edge_at_safe(hwnd, scanner)
        if frame is None:
            time.sleep(0.4)
            continue
        now = time.time()

        if edge is None:
            stable_edge, stable_since = None, 0.0
            time.sleep(0.4)
            continue
        if stable_edge is None or abs(edge - stable_edge) > 4:
            stable_edge, stable_since = edge, now
            time.sleep(0.4)
            continue

        # 稳定够久了?
        if now - stable_since < args.min_stable:
            time.sleep(0.4)
            continue

        key = str(int(round(edge)))
        if key in layouts and not args.force:
            time.sleep(0.4)
            continue
        if key in done_edges:
            time.sleep(0.4)
            continue

        # 必须确认真的在对局里:主菜单 / 结算页底部也有 UI,可能被误当成
        # "手牌扇形",那样会白扫一次(30-50s)。
        state, _m = classify(frame, tpls, states)
        if state != "in_game":
            stable_edge, stable_since = None, 0.0
            time.sleep(0.8)
            continue

        # 是我方回合吗?(对手回合手牌不会变,但扫描会干扰)
        score, _ = match_one(frame, tpls["end_turn_btn"])
        print(f"\n>>> 检测到稳定的手牌扇形(左边缘 x={edge}, "
              f"结束回合模板分 {score:.3f})")
        print(f">>> 开始扫描定位(可能要 1-2 分钟),请【保持手牌不变、不要出牌】...")

        t_scan = time.time()
        cards = scan_hotspots(scanner)
        scans += 1
        done_edges.append(key)

        if not cards:
            print(">>> 没找到任何牌,跳过(可能是非对局画面)")
            stable_edge, stable_since = None, 0.0
            continue

        # 扫描期间手牌被改动的话结果作废
        edge_after, _ = left_edge_at_safe(hwnd, scanner)
        if edge_after is None or abs(edge_after - edge) > 4:
            print(f">>> 扫描期间手牌变了(左边缘 {edge} -> {edge_after}),"
                  f"本次结果作废,稍后重试")
            stable_edge, stable_since = None, 0.0
            continue

        centers = [c["x"] for c in cards]
        n = len(centers)
        layouts[key] = {
            "left_edge": edge,
            "count": n,
            "probes": centers,
            "names": [c.get("name") for c in cards],
            "types": [c.get("type") for c in cards],
            "costs": [c.get("cost") for c in cards],
            # 原始连续段:调整展开参数时可离线重算坐标,不必重新采集
            "segments": [[s["x0"], s["x1"], s["key"][0], s["key"][1]]
                         for s in scanner.last_segments],
            "scan_seconds": round(time.time() - t_scan, 1),
            "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        print(f">>> 记录:左边缘 {edge} -> {n} 张牌 "
              f"(扫描耗时 {time.time() - t_scan:.0f}s)")
        for i, c in enumerate(cards):
            print(f"      第{i + 1}张: 悬停点 x={c['x']:<5}"
                  f"{c.get('name')}({c.get('cost')}) [{c.get('type')}]")

        os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
        with open(OUT_JSON, "w", encoding="utf-8") as f:
            json.dump({"layouts": layouts}, f, ensure_ascii=False, indent=2)
        print(f">>> 已写入 {OUT_JSON}")

        stable_edge, stable_since = None, 0.0
        time.sleep(1.0)

    # ---- 汇总 ----
    print()
    print("=" * 76)
    print(f"采集结束:扫描 {scans} 次,共记录 {len(layouts)} 种手牌布局")
    print("=" * 76)
    if layouts:
        rows = sorted(layouts.values(), key=lambda v: v["left_edge"])
        print(f"{'左边缘x':<10}{'张数':<6}{'悬停点(从左到右)'}")
        print("-" * 76)
        for r in rows:
            print(f"{r['left_edge']:<10}{r['count']:<6}"
                  f"{', '.join(str(p) for p in r['probes'])}")
        print()
        print(f"文件:{OUT_JSON}")
        print("下一步:快速扫描器会用 左边缘 -> 张数/坐标 直接悬停,跳过盲扫。")
    else:
        print("没采到任何布局。请确认在对局中、窗口可见,并让手牌张数变化过。")

    # 张数是否单调对应左边缘?(张数越多左边缘越靠左)
    if len(layouts) >= 2:
        rows = sorted(layouts.values(), key=lambda v: v["left_edge"])
        counts = [r["count"] for r in rows]
        mono = all(counts[i] <= counts[i + 1] for i in range(len(counts) - 1))
        print(f"\n单调性检查(张数应随左边缘右移而减少):{'正常' if mono else '异常!'}")
        print(f"  左边缘从小到大:{[r['left_edge'] for r in rows]}")
        print(f"  对应张数      :{counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
