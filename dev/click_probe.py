# -*- coding: utf-8 -*-
"""
click_probe.py - 「能不能不抢鼠标」的实测探针(★ 只读之外的唯一动作就是**发消息**)。

背景(用户 2026-09-20):*"程序运行抢鼠标很烦,有没有可能模拟鼠标点击……前提是
不注入内存,完全物理操作"*。

结论先说(详见 `src\\actions.py` 末尾那一段):
  · **物理层做不到"不抢"** —— Windows 只有一个系统光标,`SendCursorPos`/`mouse_event`
    动的就是它;硬件盒子(KMBox / Arduino HID)也一样,它模拟的是真鼠标,动的还是
    同一个光标。⇒ "换硬件"解决不了抢鼠标。
  · 真正不抢的只有两条:① **不碰光标、直接往窗口发消息**(本探针测的就是这条);
    ② **换一个会话/机器**(把游戏放进另一个 Windows 会话或虚拟机)。
  · ① 能不能用**完全取决于游戏**:它可能压根不看窗口消息(改成 Raw Input 直接读设备)。
    ⇒ 所以必须实测,而且判据要硬:**点一个"点了必然有反应"的按钮,看界面状态变不变**。

用法:
  :: 0. 自检(不需要游戏):自己开一个窗口,验证"消息点击"这条链路本身是通的
  .venv\\Scripts\\python.exe dev\\click_probe.py --selftest

  :: 1. 只读:报当前界面状态(不动鼠标、不发消息)
  .venv\\Scripts\\python.exe dev\\click_probe.py --state

  :: 2. 实测:在游戏主界面上,点「开始」按钮(用模板匹配定位,**不用手填坐标**)
  .venv\\Scripts\\python.exe dev\\click_probe.py --click-template play_btn

  :: 2b. 手填坐标也行(客户区坐标,左上角是 0,0)
  .venv\\Scripts\\python.exe dev\\click_probe.py --click 640 120

  :: 2c. 想测"游戏在后台也能点吗"(这是最想要的那条)
  .venv\\Scripts\\python.exe dev\\click_probe.py --click-template play_btn --background

  :: 3. 对照:同一位置用**老办法**(物理移光标)点一下
  .venv\\Scripts\\python.exe dev\\click_probe.py --click-template play_btn --physical

  :: 4. 拖拽(部署/攻击走这条):客户区 (x1,y1) -> (x2,y2)
  .venv\\Scripts\\python.exe dev\\click_probe.py --drag 560 700 640 420

判据(脚本自己会打印):
  界面状态(state)**变了** = 游戏吃窗口消息 ⇒ 把 `actions.INPUT_MODE` 改成 "message",
  整条链路(click / move_drag)就切过去了。
  state 没变、但画面变了 = 游戏有反应但不完全(多半只认移动,不认点击)。
  两个都没变 = 这条路对 KARDS 走不通,只能走"换会话/虚拟机"那条。
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

import actions  # noqa: E402
from ui_state import (classify, load_meta, load_states,  # noqa: E402
                      load_templates, match_one)
from win import (bring_to_front, capture_client_bgr, client_to_screen,  # noqa: E402
                 find_by_process, set_dpi_aware, set_window_client_size)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOT_DIR = os.path.join(PROJECT_ROOT, "shots", "click_probe")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

# ★ ctypes 的默认返回类型是 **c_int**(32 位),而 HWND/LRESULT 在 64 位上是指针宽度 ——
#   不声明就等着句柄被悄悄截断(这类错很难看出来:大部分时候句柄恰好很小)。
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.DefWindowProcW.restype = ctypes.c_longlong
user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                  ctypes.c_ulonglong, ctypes.c_longlong]
user32.RegisterClassExW.restype = wintypes.WORD
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE          # ★ 它在 kernel32 里
user32.WindowFromPoint.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = [wintypes.POINT]


# ---------------------------------------------------------------------------
# 一、自检用的窗口:自己开一个,记录收到的鼠标消息
#    ★ 为什么要它:"消息点击没反应"有两种可能 —— 游戏不认,或者**我的探针写错了**。
#      先在这个窗口上验一遍(它必然认标准消息),把"探针自己"排除掉再谈游戏。
# ---------------------------------------------------------------------------
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, ctypes.c_uint,
                             ctypes.c_ulonglong, ctypes.c_longlong)

WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
WM_CLOSE, WM_DESTROY = 0x0010, 0x0002


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class TestWindow:
    """一个空白窗口,把收到的鼠标消息按 (msg, x, y) 记下来。

    ★★ 窗口必须**在跑消息循环的那个线程里创建** —— 第一次自检就栽在这儿:
      PostMessage 投出去的消息进的是**创建窗口那个线程**的队列,而我的循环跑在
      另一个线程,于是窗口一条消息都收不到(现象是"消息发了、没人接",
      和"游戏不认窗口消息"长得一模一样 —— 差点误判成 KARDS 的问题)。
    """

    CLS = "KardsClickProbeWnd"

    def __init__(self) -> None:
        self.events: list[tuple[int, int, int]] = []
        self.hwnd = None
        self._ready = threading.Event()
        self._proc = WNDPROC(self._on_msg)          # 必须留住引用,否则回调会被回收
        threading.Thread(target=self._create_and_pump, daemon=True).start()
        if not self._ready.wait(3.0):
            raise RuntimeError("自检窗口没能在 3 秒内建起来")

    def _create_and_pump(self):
        hinst = kernel32.GetModuleHandleW(None)
        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(wc)
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.hbrBackground = gdi32.GetStockObject(5)     # WHITE_BRUSH(★ 它在 gdi32 里)
        wc.lpszClassName = self.CLS
        user32.RegisterClassExW(ctypes.byref(wc))
        # ★ 必须真的显示出来:`WindowFromPoint` **跳过不可见窗口**,加 WS_EX_TOPMOST
        #   免得被别的窗口压住(否则消息会发到底下那个窗口去)。
        self.hwnd = user32.CreateWindowExW(
            0x00000008, self.CLS, "click probe (自检窗口)", 0x00CF0000,
            120, 120, 320, 220, None, None, hinst, None)
        user32.ShowWindow(self.hwnd, 5)                # SW_SHOW
        user32.UpdateWindow(self.hwnd)
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _on_msg(self, hwnd, msg, wparam, lparam):
        if msg in (WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP):
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            self.events.append((msg, x, y))
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def center_screen(self) -> tuple[int, int]:
        rc = wintypes.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rc))
        pt = wintypes.POINT(rc.right // 2, rc.bottom // 2)
        user32.ClientToScreen(self.hwnd, ctypes.byref(pt))
        return pt.x, pt.y

    def close(self):
        user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        time.sleep(0.2)


def selftest() -> int:
    print("=" * 74)
    print("自检:自己开一个窗口,验证「不碰光标、只发消息」这条链路是通的")
    print("=" * 74)
    set_dpi_aware()
    w = TestWindow()
    time.sleep(0.6)
    sx, sy = w.center_screen()
    rc = wintypes.RECT()
    user32.GetClientRect(w.hwnd, ctypes.byref(rc))
    want = (rc.right // 2, rc.bottom // 2)
    print(f"自检窗口 hwnd={w.hwnd} 客户区 {rc.right}x{rc.bottom},"
          f"中心客户区 {want} -> 屏幕 ({sx},{sy})")

    hwnd_found, cx, cy = actions.window_under(sx, sy)
    ok_win = hwnd_found == w.hwnd
    print(f"  {'OK ' if ok_win else '✗  '} window_under() 找到的是自检窗口"
          f"(实得 hwnd={hwnd_found},客户区 {cx},{cy})")
    ok_xy = (cx, cy) == want
    print(f"  {'OK ' if ok_xy else '✗  '} 屏幕坐标 -> 客户区坐标换算正确"
          f"(要 {want},得 {(cx, cy)})")

    before = len(w.events)
    sent = actions.click_message(sx, sy, jitter=0)
    time.sleep(0.4)
    got = w.events[before:]
    kinds = [m for m, _, _ in got]
    print(f"  {'OK ' if sent else '✗  '} click_message() 返回 {sent},"
          f"窗口收到 {len(got)} 条消息:{['MOVE' if m==WM_MOUSEMOVE else 'DOWN' if m==WM_LBUTTONDOWN else 'UP' for m in kinds]}")
    ok_seq = WM_LBUTTONDOWN in kinds and WM_LBUTTONUP in kinds
    print(f"  {'OK ' if ok_seq else '✗  '} 收到了 按下+松开(这是'点击'的最小条件)")
    ok_pos = bool(got) and all((x, y) == want for _, x, y in got)
    print(f"  {'OK ' if ok_pos else '✗  '} 消息里的坐标就是点击位置")

    # 光标必须**没被挪到点击点** —— 这才是整件事的目的
    #   ★ 判据写成"没跑到点击点附近",而不是"和上次读到的位置一模一样":
    #     用户自己动一下鼠标就会让后者失败(实测第一次自检就撞上了这个假警报)。
    import win32api
    p0 = win32api.GetCursorPos()
    tx, ty = sx + 20, sy + 10
    actions.click_message(tx, ty, jitter=0)
    time.sleep(0.3)
    p1 = win32api.GetCursorPos()
    ok_still = abs(p1[0] - tx) > 8 or abs(p1[1] - ty) > 8
    print(f"  {'OK ' if ok_still else '✗  '} ★ 光标**没有被挪到点击点**"
          f"({p0} -> {p1},点击点 ({tx},{ty}))")

    w.close()
    good = all([ok_win, ok_xy, sent, ok_seq, ok_pos, ok_still])
    print("\n" + ("自检通过:消息链路是通的,可以拿去测游戏了"
                  if good else "自检没过:先修探针,别去怪游戏"))
    return 0 if good else 1


# ---------------------------------------------------------------------------
# 二、对游戏实测
# ---------------------------------------------------------------------------
def _state_now(hwnd, tpls, states):
    frame = capture_client_bgr(hwnd)
    if frame is None:
        return None, {}, None
    st, _ = classify(frame, tpls, states)
    return st, _, frame


def main() -> int:
    ap = argparse.ArgumentParser(description="「不抢鼠标」实测探针")
    ap.add_argument("--selftest", action="store_true", help="不需要游戏:验证消息链路")
    ap.add_argument("--state", action="store_true", help="只读:报当前界面状态")
    ap.add_argument("--click", nargs=2, type=int, metavar=("X", "Y"),
                    help="点客户区 (X,Y)")
    ap.add_argument("--click-template", metavar="名字",
                    help="点某个模板**匹配到的位置**(例如 play_btn / deck_ok_btn / "
                         "end_turn_btn)—— 比手填坐标可靠,省得猜")
    ap.add_argument("--drag", nargs=4, type=int, metavar=("X1", "Y1", "X2", "Y2"),
                    help="从客户区 (X1,Y1) 拖到 (X2,Y2)")
    ap.add_argument("--physical", action="store_true",
                    help="对照:用**老办法**(真的移动光标)做同一个动作")
    ap.add_argument("--sync", action="store_true", help="用 SendMessage 而不是 PostMessage")
    ap.add_argument("--background", action="store_true",
                    help="**不把游戏置前** —— 测'游戏在别的窗口后面时还能不能点'")
    ap.add_argument("--wait", type=float, default=1.2, help="动作后等多久再看画面")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("没找到 kards 窗口(游戏没开?)")
        return 1
    w = wins[0]
    hwnd = w["hwnd"]
    print(f"kards 窗口:hwnd={hwnd} title={w.get('title')!r} exe={w.get('exe')}")

    if not args.background:
        bring_to_front(hwnd)
        time.sleep(0.4)
    else:
        print("★ --background:不置前,游戏可能被别的窗口盖着(这一条才是我们最想要的场景)")
    rect = set_window_client_size(hwnd, 1280, 720, 100, 100)
    print(f"客户区已强制 1280x720,窗口 rect {rect}")
    time.sleep(0.8)

    tpls = load_templates(load_meta(os.path.join(PROJECT_ROOT, "config", "templates.json")))
    states = load_states(os.path.join(PROJECT_ROOT, "config", "states.json"))

    st0, _, frame0 = _state_now(hwnd, tpls, states)
    print(f"\n动作前:state={st0!r}")

    # --click-template:先在这一帧上匹配那个模板,拿**匹配到的位置**去点
    #   (手填坐标要么靠猜、要么得先跑一次只读探针;这个直接省掉那一步)
    if args.click_template:
        name = args.click_template
        if name not in tpls:
            print(f"没有模板 {name!r}。现有的是:{', '.join(sorted(tpls))}")
            return 1
        score, reg = match_one(frame0, tpls[name])
        print(f"模板 {name}:匹配分 {score:.3f},位置 {reg}")
        if not reg or score < 0.5:
            print(f"⚠️ 这一帧上没找到 {name}(分数太低)—— 先把游戏切到有它的那个界面")
            return 1
        args.click = [reg[0] + reg[2] // 2, reg[1] + reg[3] // 2]
        print(f"→ 点它的中心:客户区 {tuple(args.click)}")

    if args.state or (not args.click and not args.drag):
        print("(只读,没做任何动作。要实测请加 --click X Y)")
        return 0

    os.makedirs(SHOT_DIR, exist_ok=True)
    cv2.imwrite(os.path.join(SHOT_DIR, "before.png"), frame0)

    mode = "物理(真的移光标)" if args.physical else \
           ("窗口消息 SendMessage" if args.sync else "窗口消息 PostMessage")
    print(f"模式:{mode}" + ("  ★ 不碰真实光标" if not args.physical else ""))

    if args.click:
        cx, cy = args.click
        sx, sy = client_to_screen(hwnd, cx, cy)
        print(f"点客户区 ({cx},{cy}) -> 屏幕 ({sx},{sy})")
        if args.physical:
            ok = actions.click(sx, sy)
        else:
            ok = actions.click_message(sx, sy, sync=args.sync)
    else:
        x1, y1, x2, y2 = args.drag
        sx1, sy1 = client_to_screen(hwnd, x1, y1)
        sx2, sy2 = client_to_screen(hwnd, x2, y2)
        print(f"拖客户区 ({x1},{y1}) -> ({x2},{y2})")
        if args.physical:
            act = actions.move_drag
            actions.INPUT_MODE = "physical"
            ok = act(sx1, sy1, sx2, sy2)
        else:
            ok = actions.drag_message(sx1, sy1, sx2, sy2, sync=args.sync)

    print(f"动作已发出:{ok}(True 只代表'消息投出去了/鼠标动了',不代表游戏认了)")
    time.sleep(max(0.2, args.wait))

    st1, _, frame1 = _state_now(hwnd, tpls, states)
    cv2.imwrite(os.path.join(SHOT_DIR, "after.png"), frame1)
    diff = float(cv2.absdiff(frame0, frame1).mean()) if frame1 is not None else -1.0
    changed = diff > 0.5
    print(f"动作后:state={st1!r}  画面平均差 {diff:.2f}  画面变了={changed}")
    print(f"存帧:{SHOT_DIR}\\before.png / after.png")

    print("\n判定:")
    if st1 != st0:
        print(f"  ✅ **游戏吃这一下** —— state {st0!r} -> {st1!r}")
        if not args.physical:
            print("     ⇒ 可以把 src\\actions.py 的 INPUT_MODE 改成 \"message\","
                  "整条链路(click / move_drag)就切过去了")
    elif changed:
        print("  ⚠️ 画面变了但界面状态没变:游戏有反应,但这一步没走成"
              "(也可能是这个坐标本来就不该有反应 —— 换一个'点了必然有反应'的按钮再试)")
    else:
        print("  ❌ 没有任何反应。")
        if not args.physical:
            print("     先跑 --physical 用同一个坐标对照一次:物理也点不动 = 坐标不对;")
            print("     物理点得动、消息点不动 = **游戏不认窗口消息**,")
            print("     ⇒ 这条路对 KARDS 走不通,只能走'换一个 Windows 会话 / 虚拟机'。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
