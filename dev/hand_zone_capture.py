"""
hand_zone_capture.py - 手动框选采集手牌布局(参考 template_capture.py 的交互)。

为什么改成手动框选
------------------
自动扫描要在 x=340~920 打 49 个探针,一次 30-60 秒,而且:
  - 同名牌挨在一起时热区连成一片,张数只能靠"跨度 ÷ 单卡间距"推算,会算错
  - 扫描期间会一直抢鼠标
手动框选一次几秒钟,张数由你亲眼确认,框选动作发生在 OpenCV 窗口里,
完全不碰游戏窗口。

流程(全在 OpenCV 窗口里操作)
----------------------------
  1. 脚本先把鼠标移开、抓一张干净的游戏画面(这样扇形是"未展开"状态,
     左边缘才测得准)
  2. 你依次把每张牌在底部的可见部分框出来,从左到右
  3. 回车保存;脚本自动测出扇形左边缘,把"左边缘 -> 张数 + 每张悬停点"
     写进 config/hand_layout.json
  4. 手牌张数变了就按 r 重新抓图,再框一遍;按 q 退出

按键
----
  拖框    : 添加一张牌的热区(取框的水平中心作为悬停点)
  u       : 撤销上一个框
  r       : 重新抓取游戏画面(手牌变了就按这个)
  Enter   : 保存当前这一组
  q / ESC : 退出

用法(对着真实对局跑):
  .venv\\Scripts\\python.exe src\\hand_zone_capture.py
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

from actions import set_cursor
from hand_scanner_v2 import PROBE_Y, SAFE_POINT
from ui_state import load_meta, load_states, load_templates, classify
from win import (bring_to_front, capture_client_bgr, client_to_screen,
                 find_by_process, set_dpi_aware, set_window_client_size)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_JSON = os.path.join(PROJECT_ROOT, "config", "hand_layout.json")

WINDOW = "hand_zone_capture"
COL_DONE = (0, 200, 255)      # 已记录的框
COL_NEW = (0, 255, 0)         # 正在拖的框


class HandZoneCapture:
    def __init__(self, hwnd, tpls, states, probe_y=PROBE_Y):
        self.hwnd = hwnd
        self.tpls = tpls
        self.states = states
        self.probe_y = probe_y
        self.img = None
        self.work = None
        self.drag_start = None
        self.drag_now = None
        self.boxes = []          # 已确认的框 [(x,y,w,h), ...]
        self.left_edge = None
        self.right_edge = None
        self.pending = False     # True = 已预览,等第二次 Enter 确认
        self.cards_only = True   # True = 所有框都是牌,边缘用自动检测
        self.layouts = {}
        if os.path.exists(OUT_JSON):
            try:
                with open(OUT_JSON, "r", encoding="utf-8") as f:
                    self.layouts = json.load(f).get("layouts", {})
            except Exception:
                pass

    # ---- 抓图 ----
    def grab_clean(self) -> bool:
        """
        先把鼠标移开(到安全点)再抓图。

        这一步很关键:KARDS 悬停手牌时会把扇形展开,左边缘会变
        (实测同一副手牌:悬停左边 367、悬停中间 394、鼠标在安全点 369)。
        不先移开的话,量出来的左边缘跟以后使用时的对不上。
        """
        set_cursor(*client_to_screen(self.hwnd, *SAFE_POINT))
        time.sleep(0.35)
        self.img = capture_client_bgr(self.hwnd)
        if self.img is None:
            print("抓图失败(窗口被最小化/遮挡?)")
            return False
        self.boxes = []
        # 左右边缘都用与 hand_calibrate 完全相同的算法,保证口径一致。
        # 手框的边缘是个"区域"取中心,拿不到真正的边线,所以边缘一律自动检测。
        from hand_calibrate import detect_edges
        self.left_edge, self.right_edge = detect_edges(self.img)
        state, _ = classify(self.img, self.tpls, self.states)
        print(f"抓到画面 {self.img.shape[1]}x{self.img.shape[0]}  "
              f"屏幕状态={state}  左边缘 x={self.left_edge}  "
              f"右边缘 x={self.right_edge}")
        if state != "in_game":
            print("  ⚠ 当前不在对局中 —— 手牌框选要对局里做")
        return True

    # ---- 绘制 ----
    def redraw(self) -> None:
        self.work = self.img.copy()
        h, w = self.work.shape[:2]

        # 已记录的框(现在每个框都是一张牌,边缘自动检测故不画框)
        for i, (x, y, bw, bh) in enumerate(self.boxes, start=1):
            cv2.rectangle(self.work, (x, y), (x + bw, y + bh), COL_DONE, 2)
            cx = x + bw // 2
            cv2.line(self.work, (cx, 0), (cx, h), COL_DONE, 1)
            cv2.putText(self.work, f"#{i}", (x, max(14, y - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, COL_DONE, 2, cv2.LINE_AA)

        # 自动检测到的左右边缘
        for ex, col in ((self.left_edge, (255, 128, 0)),
                        (self.right_edge, (255, 0, 255))):
            if ex is not None:
                cv2.line(self.work, (int(ex), 0), (int(ex), h), col, 2)

        # 正在拖的框
        if self.drag_start and self.drag_now:
            cv2.rectangle(self.work, self.drag_start, self.drag_now, COL_NEW, 2)

        # 顶部信息条
        cv2.rectangle(self.work, (0, 0), (w, 34), (18, 18, 18), -1)
        if self.pending:
            info = (f"确认保存 {len(self.boxes)} 个框?  再按 Enter 确认 | "
                    f"u=撤销 | q=退出")
            col = (0, 255, 255)
        else:
            nb = len(self.boxes)
            step = ("逐张框【每张牌】(从左到右)" if nb == 0
                    else "继续框下一张牌;框完按 Enter 预览")
            info = (f"已框 {nb} 张 | {step} | 自动边缘 L={self.left_edge} "
                    f"R={self.right_edge} | u=撤销 r=重抓 Enter=预览/保存 q=退出")
            col = (255, 255, 255)
        cv2.putText(self.work, info, (8, 23), cv2.FONT_HERSHEY_SIMPLEX,
                    0.52, col, 1, cv2.LINE_AA)
        cv2.imshow(WINDOW, self.work)

    # ---- 鼠标 ----
    def on_mouse(self, event, x, y, _flags, _param) -> None:  # noqa: N802
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drag_start = (x, y)
            self.drag_now = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and self.drag_start:
            self.drag_now = (x, y)
            self.redraw()
        elif event == cv2.EVENT_LBUTTONUP and self.drag_start:
            x0, y0 = self.drag_start
            self.drag_start = None
            self.drag_now = None
            if abs(x - x0) < 3 or abs(y - y0) < 3:
                print("框太小,忽略(请把整张牌露出的部分框住)")
                self.redraw()
                return
            bx, by = min(x0, x), min(y0, y)
            bw, bh = abs(x - x0), abs(y - y0)
            self.boxes.append((bx, by, bw, bh))
            cx = bx + bw // 2
            idx = len(self.boxes)
            if idx == 1:
                what = "左边缘"
            else:
                what = f"第 {idx - 1} 张牌(或最后的右边缘)"
            print(f"  第 {idx} 个框: ({bx},{by}) {bw}x{bh} -> 中心 x={cx}   [{what}]")
            self.redraw()

    # ---- 解析框序列 ----
    def _parse(self):
        """
        返回 (probes, n_boxes_used)。

        cards_only=True(默认):每个框都是一张牌,边缘用自动检测。
        否则沿用旧约定:第一个框=左边缘、最后一个=右边缘、中间是牌。
        """
        if self.cards_only:
            if not self.boxes:
                return [], 0
            probes = [int(b[0] + b[2] / 2)
                      for b in sorted(self.boxes, key=lambda b: b[0] + b[2] / 2)]
            return probes, len(self.boxes)

        if len(self.boxes) < 3:
            return [], 0
        cards = self.boxes[1:-1]
        if not cards:
            return [], 0
        probes = [int(b[0] + b[2] / 2)
                  for b in sorted(cards, key=lambda b: b[0] + b[2] / 2)]
        return probes, len(self.boxes)

    # ---- 保存 ----
    def preview(self) -> bool:
        """显示这次将要保存的内容,等用户再按一次 Enter 确认。"""
        probes, used = self._parse()
        if not probes:
            if self.cards_only:
                print("还没框 —— 请把每张牌依次框一遍(从左到右)")
            else:
                print("框不够:顺序应为 左边缘 → 每张牌 → 右边缘(至少 3 个)")
            return False
        key = str(int(round(self.left_edge))) if self.left_edge is not None else "?"
        old = self.layouts.get(key)
        n = len(probes)
        span = (self.right_edge - self.left_edge
                if (self.left_edge is not None and self.right_edge is not None)
                else None)
        print()
        print(f"  自动检测边缘:左 {self.left_edge} / 右 {self.right_edge}"
              + (f"  (扇形宽 {span}px)" if span else ""))
        print(f"  牌 {n} 张,悬停点 {probes}")
        if n > 1 and span:
            print(f"  平均间距 {span / (n + 1):.1f}px")
        if old is not None:
            print(f"  ⚠ 该左边缘已有记录:{old.get('count')} 张 "
                  f"{old.get('probes')}  —— 确认后会覆盖它")
        print("  ▶ 再按一次 Enter 确认保存;按 u 撤销最后一个框继续改")
        return True

    def save(self) -> bool:
        probes, used = self._parse()
        if not probes:
            print("框不够 / 没框到牌")
            return False
        if self.left_edge is None:
            print("测不到自动左边缘,无法建立对照表(确认是在对局中)")
            return False
        n = len(probes)
        # 查表用的 key 以【自动检测的左边缘】为准:scan_fast 运行时也只能自动
        # 检测,两边口径必须一致。
        key = str(int(round(self.left_edge)))
        self.layouts[key] = {
            "left_edge": int(self.left_edge),
            "right_edge": int(self.right_edge) if self.right_edge is not None else None,
            "count": n,
            "probes": probes,
            "boxes": used,
            "source": "manual",
            "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
        with open(OUT_JSON, "w", encoding="utf-8") as f:
            json.dump({"layouts": self.layouts}, f, ensure_ascii=False, indent=2)
        print(f"\n已保存:左边缘 {self.left_edge} / 右边缘 {self.right_edge} "
              f"-> {n} 张牌")
        print(f"  悬停点 {probes}")
        print(f"  文件 {OUT_JSON}")
        print(f"  当前共 {len(self.layouts)} 种布局: "
              f"{sorted((v['count'], v['left_edge'], v.get('right_edge')) for v in self.layouts.values())}")
        print()
        print("手牌张数变了就按 r 重抓,再把每张牌框一遍。")
        return True


    # ---- 主循环 ----
    def run(self) -> int:
        if not self.grab_clean():
            return 1
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW, self.img.shape[1], self.img.shape[0])
        cv2.setMouseCallback(WINDOW, self.on_mouse)
        self.redraw()
        print()
        print("把每张牌在底部的可见部分【从左到右】依次框出来即可 ——")
        print("  左右边缘由脚本自动检测(比手框准),你不用框边缘")
        print("  框完按 Enter 预览,再按一次 Enter 确认保存")
        print("  u=撤销  r=重抓(手牌变了就按)  q=退出")
        print()
        while True:
            key = cv2.waitKey(30) & 0xFF
            if key in (ord("q"), 27):
                break
            elif key in (13, 10):            # Enter
                if not self.pending:
                    # 第一次 Enter:只预览,等确认
                    self.pending = self.preview()
                else:
                    # 第二次 Enter:真正保存
                    self.save()
                    self.pending = False
                    self.boxes = []
                self.redraw()
            elif key == ord("u"):
                if self.boxes:
                    self.boxes.pop()
                    self.pending = False
                    print(f"撤销一个,剩 {len(self.boxes)} 个")
                self.redraw()
            elif key == ord("r"):
                if self.grab_clean():
                    self.pending = False
                    self.redraw()
        cv2.destroyAllWindows()
        print("退出。")
        return 0


def main() -> int:
    set_dpi_aware()
    ap = argparse.ArgumentParser(description="手牌布局手动框选采集")
    ap.add_argument("--proc", default="kards")
    ap.add_argument("--probe-y", type=int, default=PROBE_Y,
                    help=f"悬停时鼠标的 y(默认 {PROBE_Y})")
    args = ap.parse_args()

    wins = find_by_process(args.proc)
    if not wins:
        print("找不到 kards 窗口(游戏在运行吗?)")
        return 1
    hwnd = wins[0]["hwnd"]
    print(f"kards hwnd={hwnd}")
    bring_to_front(hwnd)
    time.sleep(0.4)
    set_window_client_size(hwnd, 1280, 720, 100, 100)
    time.sleep(0.8)

    from hand_scanner_v2 import _load_db
    _load_db()
    tpls = load_templates(load_meta(os.path.join(PROJECT_ROOT, "config", "templates.json")))
    states = load_states(os.path.join(PROJECT_ROOT, "config", "states.json"))

    return HandZoneCapture(hwnd, tpls, states, args.probe_y).run()


if __name__ == "__main__":
    sys.exit(main())
