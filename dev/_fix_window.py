"""把 KARDS 的 UnrealWindow 摆回屏幕内,并设成客户区 1280x720。

为什么需要这个独立脚本:
  我之前一次 MoveWindow 把游戏自己的窗口摆放位置(rcNormalPosition)污染成了
  (32767,32767) —— 游戏每次"恢复窗口"就落到那个哨兵值上,再自己校正成负坐标,
  于是整个窗口跑到屏幕左边界之外。引擎的 `set_window_client_size` **只改尺寸、
  不动位置**(x=left, y=top),所以它救不回来;而窗口在屏幕外时
  `SetCursorPos` 没法把光标放过去 -> **所有点击都会失败**。

用法:  python dev\\_fix_window.py [x] [y]     默认 (40, 30)
安全性:只动窗口位置和尺寸,不碰游戏内容、不点击。
"""
import ctypes
import ctypes.wintypes as wt
import sys

sys.stdout.reconfigure(encoding="utf-8")

user32 = ctypes.WinDLL("user32", use_last_error=True)

ENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [ENUMPROC, wt.LPARAM]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.IsIconic.argtypes = [wt.HWND]

import os
import subprocess

SW_RESTORE, SW_SHOWNORMAL = 9, 1
SWP_NOZORDER, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0004, 0x0010, 0x0040

# 找到 kards-Win64-Shipping 进程的所有 pid
out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq kards-Win64-Shipping.exe",
                      "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
pids = set()
for line in out.splitlines():
    parts = [p.strip('"') for p in line.split('","')]
    if len(parts) >= 2 and parts[1].isdigit():
        pids.add(int(parts[1]))
print("kards-Win64-Shipping pids:", pids or "(没找到)")

found = []


def cb(hwnd, _l):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value in pids:
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value == "UnrealWindow":
            found.append(hwnd)
    return True


user32.EnumWindows(ENUMPROC(cb), 0)
if not found:
    print("❌ 没找到 UnrealWindow —— 游戏是不是关了?")
    sys.exit(1)

hwnd = found[0]
print("UnrealWindow hwnd =", hwnd)

r = wt.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(r))
c = wt.RECT()
user32.GetClientRect(hwnd, ctypes.byref(c))
print(f"  修之前: rect=({r.left},{r.top})-({r.right},{r.bottom}) "
      f"尺寸={r.right-r.left}x{r.bottom-r.top} 客户区={c.right}x{c.bottom} "
      f"最小化={bool(user32.IsIconic(hwnd))}")

# 先把窗口恢复成普通状态(它会试图落到被污染的 rcNormalPosition,没关系,下面立刻挪)
user32.ShowWindow(hwnd, SW_RESTORE)
user32.ShowWindow(hwnd, SW_SHOWNORMAL)

# 按"当前边框+标题"反算目标窗口尺寸,让客户区正好 1280x720
user32.GetWindowRect(hwnd, ctypes.byref(r))
user32.GetClientRect(hwnd, ctypes.byref(c))
border_w = (r.right - r.left) - c.right
border_h = (r.bottom - r.top) - c.bottom
if border_w <= 0 or border_h <= 0:      # 尺寸被压坏过 -> 用实测过的常见值
    border_w, border_h = 16, 39
target_x = int(sys.argv[1]) if len(sys.argv) > 2 else 40
target_y = int(sys.argv[2]) if len(sys.argv) > 2 else 30
new_w, new_h = 1280 + border_w, 720 + border_h
print(f"  目标: 窗口 {new_w}x{new_h} @ ({target_x},{target_y}) -> 客户区 1280x720")

user32.SetWindowPos(hwnd, None, target_x, target_y, new_w, new_h,
                    SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW)
user32.SetForegroundWindow(hwnd)

# ★ 迭代校正:上面用的 border 是**缩放过程中**量的,可能偏小(实测差 5x13)。
#   做法:量出"客户区比目标少了多少",把差值加回窗口尺寸,最多试 5 次。
for i in range(5):
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    user32.GetClientRect(hwnd, ctypes.byref(c))
    dw = 1280 - c.right
    dh = 720 - c.bottom
    if dw == 0 and dh == 0:
        break
    new_w += dw
    new_h += dh
    user32.SetWindowPos(hwnd, None, target_x, target_y, new_w, new_h,
                        SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW)
    print(f"  校正第 {i+1} 次: 客户区差 ({dw:+d},{dh:+d}) -> 窗口改成 {new_w}x{new_h}")

user32.GetWindowRect(hwnd, ctypes.byref(r))
user32.GetClientRect(hwnd, ctypes.byref(c))
print(f"  修之后: rect=({r.left},{r.top})-({r.right},{r.bottom}) "
      f"尺寸={r.right-r.left}x{r.bottom-r.top} 客户区={c.right}x{c.bottom}")

onscreen = (r.left >= 0 and r.top >= 0 and r.right <= 1920 and r.bottom <= 1080)
print("  在屏幕内?", "✅ 是" if onscreen else "❌ 否 —— 可能屏幕分辨率不是 1920x1080,请手动拖一下")
print("  客户区 1280x720?", "✅ 是" if (c.right, c.bottom) == (1280, 720) else f"❌ 是 {c.right}x{c.bottom}")
