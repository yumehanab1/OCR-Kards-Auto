"""
win.py - Windows window helpers for KARDS automation (M0).

Find a window by title fragment, force it to a fixed client size / position,
bring it to foreground, and capture its client area to a numpy BGR image.

Only uses public Win32 APIs (EnumWindows / SetWindowPos / PrintWindow via
GetWindowDC fallback). No injection, no memory access.
"""

from __future__ import annotations

import ctypes
import os
from typing import Optional

import numpy as np
import win32con
import win32gui
import win32process


def set_dpi_aware() -> None:
    """
    Declare per-monitor DPI awareness for this process so that all Win32
    coordinates (SetWindowPos / GetWindowRect / ClientToScreen) and mss grabs
    use physical pixels consistently. Without this, on a 125%/150% scaled
    display a '1280x720' client ends up physically 1600x900 and captures
    only a cropped part of the window.
    """
    try:
        # Try per-monitor v2 first (best), then v1, then legacy SetProcessDPIAware.
        for func, arg in (
            ("SetProcessDpiAwarenessContext", ctypes.c_void_p(-4)),  # PER_MONITOR_AWARE_V2
            ("SetProcessDpiAwarenessContext", ctypes.c_void_p(-3)),  # PER_MONITOR_AWARE
        ):
            if hasattr(ctypes.windll.user32, func):
                if ctypes.windll.user32[func](arg):
                    return
        if hasattr(ctypes.windll.shcore, "SetProcessDpiAwareness"):
            if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:  # PER_MONITOR_DPI_AWARE
                return
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# --- Win32 GDI constants needed for capture ---
SRCCOPY = 0x00CC0020
PW_CLIENTONLY = 0x00000001


def find_windows(title_fragment: str, exact: bool = False) -> list[dict]:
    """Return visible top-level windows whose title contains / equals fragment."""
    out = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        length = win32gui.GetWindowTextLength(hwnd)
        if length == 0:
            return True
        title = win32gui.GetWindowText(hwnd)
        if exact:
            hit = title == title_fragment
        else:
            hit = title_fragment.lower() in title.lower()
        if hit:
            try:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                out.append(
                    {
                        "hwnd": hwnd,
                        "title": title,
                        "rect": (left, top, right, bottom),
                        "pid": pid,
                    }
                )
            except Exception:
                pass
        return True

    win32gui.EnumWindows(cb, None)
    return out


def _proc_name_of(pid: int) -> str:
    """Return the base executable name of a pid ('' if unavailable)."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = ctypes.c_ulong(260)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


# ---------------------------------------------------------------------------
# ★★★ 2026-09-16(用户实测报的 bug):**"名字里有 kards"不等于"这是游戏"**。
#
# 现象(用户原话):*"我把 exe 放项目文件夹了,实测能跑,有一个问题:为啥我点击开始
#   之后他会把自己的窗口改成 1280x720"*。
# 机理:引擎启动时会 `wins0 = find_by_process("kards")` + `set_window_client_size(...,
#   1280, 720)`(那是给**游戏**窗口定的规矩)。而 `find_by_process` 判的是"**进程名里
#   包含 'kards'**" —— 我们的面板 exe 叫 **`KARDS AUTO.exe`**,正好包含。
#   于是引擎抓到的"游戏窗口"是**面板自己的窗口**,把面板强制成了 1280x720。
#
# 修法:把"什么算游戏窗口"写成**实测出来的精确特征**:
#   · 进程名 `kards-Win64-Shipping.exe`(启动器 `kards.exe` 没有主窗口);
#   · 窗口类 `UnrealWindow`(UE 的窗口类;面板是 WinForms + WebView2,类名完全不同)。
# ★ 为什么不做"找不到就退回宽匹配":那等于又回到这个 bug 上(游戏没开时,
#   宽匹配会抓到面板,然后**照样**把面板改尺寸)。宁可不找(fail-closed,
#   引擎会打印"没找到窗口"并等),也不许抓错。
# ---------------------------------------------------------------------------
GAME_EXE_NAMES = ("kards-win64-shipping.exe", "kards.exe")
GAME_WINDOW_CLASS = "UnrealWindow"
#: 绝不该被当成游戏窗口的进程(我们自己的东西:面板 exe / python)。
NOT_GAME_EXE_FRAGMENTS = ("python.exe", "pythonw.exe", "kards auto.exe")


def looks_like_game(exe_name: str, class_name: str = "") -> bool:
    """
    这个(进程名, 窗口类)是不是**游戏窗口**? —— 纯函数,用例可以直接考它。

    判据(见上面那段实测说明):精确进程名命中 -> 是;我们自己那几个进程 -> 否;
    其余要求窗口类是 `UnrealWindow`。
    """
    name = (exe_name or "").lower()
    if not name:
        return False
    if name in GAME_EXE_NAMES:
        return True
    if any(x in name for x in NOT_GAME_EXE_FRAGMENTS):
        return False
    return class_name == GAME_WINDOW_CLASS


def find_by_process(
    exe_name_fragment: str, title_contains: str = "", strict_game: bool = True
) -> list[dict]:
    """
    Find visible top-level windows whose owning process executable name
    contains exe_name_fragment (e.g. 'kards'), optionally also requiring the
    window title to contain title_contains. Much safer than matching titles
    alone: a file-explorer folder named 'kards-auto' will never match.

    ★★★ 2026-09-16:光"进程名包含"**不够** —— 我们自己的面板 exe 叫 `KARDS AUTO.exe`,
      它也包含 "kards",于是引擎把自己的面板当成了游戏窗口(见上面那段实测记录)。
      现在默认 `strict_game=True`,多过一道 `looks_like_game`(精确名 / 排除自己 /
      `UnrealWindow` 类)。`strict_game=False` 是**老行为**,留给 A/B 和特殊场景:
      ★ 它**只在有明确理由时**才该用 —— 游戏没开的时候,老行为会抓错窗口。
    """
    frag = (exe_name_fragment or "").lower()
    out = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            pid = win32process.GetWindowThreadProcessId(hwnd)[1]
            name = _proc_name_of(pid).lower()
        except Exception:
            return True
        if frag and frag not in name:
            return True
        if strict_game:
            try:
                cls = win32gui.GetClassName(hwnd)
            except Exception:
                cls = ""
            if not looks_like_game(name, cls):
                return True
        title = win32gui.GetWindowText(hwnd)
        if title_contains and title_contains.lower() not in title.lower():
            return True
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            out.append(
                {
                    "hwnd": hwnd,
                    "title": title,
                    "rect": (left, top, right, bottom),
                    "pid": pid,
                    "exe": name,
                }
            )
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    return out


def list_all_windows() -> list[dict]:
    """List all visible top-level windows (titles only). For discovery."""
    return find_windows("")


def bring_to_front(hwnd: int) -> None:
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass


def window_is_capturable(hwnd: int, quiet: bool = False) -> bool:
    """
    True when the window is on screen, not minimised and not covered.

    ★ 为什么这是硬前提(见 PROJECT_STATE §7 第 12 条):截图走的是 mss 的
    **屏幕矩形抓取**(PrintWindow 对 GPU 窗口返回全黑),所以窗口一旦被别的
    窗口盖住,抓到的就是别的程序的画面 —— 差分立刻报出假面板,扫描器会
    "看"出根本不存在的牌,主循环还会照着这些假坐标去点别人的窗口。

    ★ 实测踩过:机器上同时跑着别的自动化(ALAS 这类)时,它的 **GUI 窗口 /
    模拟器窗口**会盖在 KARDS 上面。ALAS 自己走 adb、**不碰 Windows 光标**,
    所以问题不是"抢鼠标",而是"盖住窗口" —— 截图立刻变成别人的画面。
    ★ 而"抢鼠标"是另一回事,而且是本项目自己造成的:只要同时跑了两个
    main_loop 实例,它们就会互相把对方的光标移走,让行判据(user_took_over)
    一路为真,扫描在第一个探针就中止(表现:`0 cards in 0.8s`)。
    那一条由 `acquire_single_instance_lock` 挡,不由这个函数挡。

    quiet=True 时不打印原因(调用方自己会汇总刷屏)。
    """
    if win32gui.IsIconic(hwnd):
        if not quiet:
            print("   (窗口已最小化)")
        return False
    if not win32gui.IsWindowVisible(hwnd):
        if not quiet:
            print("   (窗口不可见)")
        return False
    # 客户区中心点上是哪个窗口?不是本窗口(或它的顶层父窗口)就是被遮挡了。
    left, top = win32gui.ClientToScreen(hwnd, (0, 0))
    cx, cy = left + 640, top + 360
    covering = win32gui.WindowFromPoint((cx, cy))
    if covering and covering != hwnd:
        root = win32gui.GetAncestor(covering, win32con.GA_ROOT)
        if root not in (0, hwnd):
            if not quiet:
                print(f"   (窗口被遮挡: hwnd={root} "
                      f"{win32gui.GetWindowText(root)!r})")
            return False
    return True


def foreground_window() -> int:
    """当前前台窗口句柄(诊断用:判断是不是别的程序抢了焦点)。"""
    try:
        return int(win32gui.GetForegroundWindow())
    except Exception:
        return 0


# 单实例锁的句柄必须活到进程结束 —— 一旦被垃圾回收,互斥体就释放了。
_INSTANCE_LOCK = {}


def acquire_single_instance_lock(name: str = "kards_auto_main_loop"):
    """
    取得"全机只有一个本程序实例"的锁。

    返回 `(ok, reason)`:
      (True,  "acquired")        拿到锁,可以继续
      (False, "held-by-other")   已经有实例在跑 -> **必须拒绝启动**
      (False, "error: ...")      锁机制本身出错 -> **也要拒绝启动**

    ★ 为什么"出错"也要拒绝启动(实测踩过):第一版在异常时返回字符串
      `"unknown"` 表示"放行但存疑",而调用方写的是 `if ... is None` 才算被拒 ——
      `"unknown"` 是 truthy,于是**锁失效时第二个实例照样启动**并开始抢鼠标。
      真正的错误是 `win32event.CloseHandle` 根本不存在(是 win32api.CloseHandle),
      抛 AttributeError 被 except 吞掉。**"存疑"在锁这种地方必须按失败处理。**

    ★★ 为什么必须要有这个(实测踩过,2026-09-11 02:17-02:23 的日志):
      那时候有两个 main_loop **同时在跑**(日志里两条 `main_loop start`:
      02:17:32 和 02:21:45;扫描计数器一个走到 #12、另一个在 #3,交错出现)。
      两个进程驱动同一个游戏窗口、抢**同一个鼠标光标**:

          A 把光标放到手牌上 -> B 又把光标移到别处
          -> A 的让行判据 user_took_over() 一路为真
          -> 扫描在第一个探针就中止 -> 日志 `hand scan: 0 cards in 0.8s`

      表现和"功能坏了"一模一样,而且完全看不出是自己人打架 —— 当时我甚至
      怀疑是别的自动化抢鼠标(其实 ALAS 走 adb,根本不碰 Windows 光标)。
      还出现过"刚出完牌,另一个进程立刻把回合结束掉"。

    ★★ 判据必须用【所有权】,不能用 GetLastError:
      更早一版用 `CreateMutex(..., False, name)` + `GetLastError() ==
      ERROR_ALREADY_EXISTS`。**它同样不工作。** GetLastError 是**线程级**的,
      任何中间的 Win32 调用都会覆盖它,而我偏偏在 CreateMutex 之后写了
      `import win32api` —— 首次导入要加载 DLL、调一堆 API,读到的 last-error
      变成 0,"已存在"被吃掉。(自检里没暴露,是因为那里这两个模块早就导入过。)

      现在的做法完全不依赖 last-error:用 `bInitialOwner=True` 创建,**然后
      用 0 超时 Wait**,问"我到底有没有拿到所有权":
        WAIT_OBJECT_0  -> 新建成功,或前一个持有者已退出 -> 拿到
        WAIT_ABANDONED -> 前一个进程崩了/被 kill,系统把锁留给我们 -> 拿到
        WAIT_TIMEOUT   -> 别人正持有 -> 拒绝启动
      进程一死(正常退出、崩溃、被 kill)系统都自动释放,不会有残留锁。
    """
    try:
        import win32api
        import win32event

        handle = win32event.CreateMutex(None, True, name)   # True = 请求所有权
        rc = win32event.WaitForSingleObject(handle, 0)
        if rc in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
            _INSTANCE_LOCK[name] = handle                   # 保住句柄,别被 GC 掉
            return True, "acquired"
        # 别人持有 -> 关掉我们这次打开的句柄,别在系统里多留一份引用
        win32api.CloseHandle(handle)
        return False, "held-by-other"
    except Exception as e:
        return False, f"error: {type(e).__name__}: {e}"


def set_window_client_size(
    hwnd: int, width: int, height: int, x: Optional[int] = None, y: Optional[int] = None
) -> tuple[int, int, int, int]:
    """
    Force the *client area* of hwnd to width x height (that is what matters for
    pixel-perfect templates) and move it to x,y (screen coords, top-left of the
    window frame). Returns final window rect (frame).
    """
    # Compute frame size needed for the requested client size.
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    frame_w = right - left
    frame_h = bottom - top

    rect = win32gui.GetClientRect(hwnd)
    client_w = rect[2]
    client_h = rect[3]
    border_w = frame_w - client_w
    border_h = frame_h - client_h

    new_w = width + border_w
    new_h = height + border_h
    if x is None:
        x = left
    if y is None:
        y = top

    win32gui.SetWindowPos(
        hwnd,
        win32con.HWND_TOP,
        x,
        y,
        new_w,
        new_h,
        win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
    )
    return win32gui.GetWindowRect(hwnd)


def capture_client_bgr(hwnd: int, allow_screen_fallback: bool = True) -> Optional[np.ndarray]:
    """
    Capture the client area of hwnd into a BGR numpy array. Frame decorations
    are excluded.

    Strategy:
      1. Try PrintWindow (works for most normal windows, no need to be visible).
      2. If the result is featureless (all black, all white, or flat color -
         GPU-rendered windows often fail PrintWindow this way), fall back to an
         mss grab of the client-area rectangle on screen. This requires the
         window to be on-screen and not fully obscured — which is the normal
         case for a bot run in the foreground.

    ★★★ 2026-09-15(实机抓到的**整轮空转** bug):上面第 2 条**不够**。
      KARDS 的窗口类是 `UnrealWindow`,PrintWindow 有时候不给"全黑/平坦"那张,
      而是给一张**高对比垃圾图**:实测一整帧里 **纯白 40.5% + 纯黑 58.7% = 99.2%**
      (`shots/win_capture/printwindow_shell.png`)。它 mean=105、**std=125**,
      于是 `_is_blank` 的"平坦"判据**放它过去** -> 永远轮不到按矩形抓屏那条退路
      -> 主循环每一 tick 拿到的都是这张垃圾图 -> 判不出界面 -> 一直 `state -> None`
      (**一次都不动作**,而且日志里只有一行 `state -> None`,看不出所以然)。
      而同一时刻同一矩形从桌面上裁下来是 mean=58.9 / 纯白 0.0% / 纯黑 2.2% ——
      游戏画面本来长什么样,4 张不同界面的实机帧实测:纯白 **0.0%**、纯黑 **<=7.1%**,
      和那张垃圾图差一个数量级。所以这里加一道 `_is_shell_fill` 判据把它挡掉,
      让流程走到"按矩形抓屏"那条**本来就是实机主路**的退路上。
    """
    img = _capture_client_printwindow(hwnd)
    if img is not None and not _is_blank(img) and not _is_shell_fill(img):
        return img
    if allow_screen_fallback:
        img2 = _capture_client_screenrect(hwnd)
        if img2 is not None and not _is_blank(img2):
            return img2
    return img


def _is_blank(img: np.ndarray, threshold: float = 8.0) -> bool:
    """
    True when the image is essentially featureless: near-uniform color (which
    covers all-black AND all-white) or a solid light/dark frame. PrintWindow on
    GPU windows can return a black, white or flat surface; all must trigger the
    mss screen fallback.
    """
    mean = float(img.mean())
    std = float(img.std())
    if std < threshold:
        return True  # flat color (black, white, or any uniform fill)
    return mean < threshold or mean > 255.0 - threshold


#: 纯白(>=250)+ 纯黑(<=5)的像素占比超过它就判成"窗口的空壳表面"。
#  实测:那张 PrintWindow 垃圾图 **99.2%**,游戏画面(4 张不同界面)**0.0%~7.1%**。
#  门槛取 0.5,落在中间那一大段空档里,两头都留着余量。
SHELL_FILL_FRAC_MAX = 0.5


def _is_shell_fill(img: np.ndarray, frac_max: float = SHELL_FILL_FRAC_MAX) -> bool:
    """
    True when the frame is mostly **pure white / pure black** —— 那是窗口的"空壳"
    表面(PrintWindow 在 UE 窗口上会返回它),**不是游戏画面**。

    为什么不能并用 `_is_blank`:那张图不是"平坦"的(std=125),它是一张**高对比**
    的垃圾图,`_is_blank` 按设计放它过去(见 `capture_client_bgr` 的说明)。
    """
    if img is None or not hasattr(img, "shape"):
        return False
    gray = img.mean(axis=2) if img.ndim == 3 else img.astype(np.float32)
    if gray.size == 0:
        return True
    frac = float(((gray >= 250.0) | (gray <= 5.0)).mean())
    return frac >= frac_max


def _capture_client_printwindow(hwnd: int) -> Optional[np.ndarray]:
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        try:
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            w = right - left
            h = bottom - top
            if w <= 0 or h <= 0:
                return None

            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32

            hdc_mem = gdi32.CreateCompatibleDC(hwnd_dc)

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", ctypes.c_uint32),
                    ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32),
                    ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16),
                    ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32),
                    ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32),
                    ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32),
                ]

            bih = BITMAPINFOHEADER()
            bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bih.biWidth = w
            bih.biHeight = -h  # top-down
            bih.biPlanes = 1
            bih.biBitCount = 32
            bih.biCompression = 0  # BI_RGB
            bih.biSizeImage = w * h * 4

            bits = ctypes.c_void_p()
            hbmp = gdi32.CreateDIBSection(
                hdc_mem,
                ctypes.byref(bih),
                0,  # DIB_RGB_COLORS
                ctypes.byref(bits),
                None,
                0,
            )
            if not hbmp:
                gdi32.DeleteDC(hdc_mem)
                return None

            old = gdi32.SelectObject(hdc_mem, hbmp)
            ok = user32.PrintWindow(hwnd, hdc_mem, PW_CLIENTONLY)
            if not ok:
                gdi32.BitBlt(hdc_mem, 0, 0, w, h, hwnd_dc, 0, 0, SRCCOPY)

            gdi32.SelectObject(hdc_mem, old)
            buf = (ctypes.c_ubyte * (w * h * 4))()
            ctypes.memmove(buf, bits, w * h * 4)
            arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)  # BGRA
            gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(hdc_mem)
            return arr[:, :, :3].copy()  # drop alpha -> BGR
        finally:
            win32gui.ReleaseDC(hwnd, hwnd_dc)
    except Exception:
        return None


def _capture_client_screenrect(hwnd: int) -> Optional[np.ndarray]:
    """mss grab of the window client area (requires visible, unobscured)."""
    import mss

    try:
        # Client area origin in screen coordinates.
        origin = win32gui.ClientToScreen(hwnd, (0, 0))
        l, t, r, b = win32gui.GetClientRect(hwnd)
        mon = {
            "left": origin[0],
            "top": origin[1],
            "width": r - l,
            "height": b - t,
        }
        if mon["width"] <= 0 or mon["height"] <= 0:
            return None
        with mss.mss() as sct:
            shot = sct.grab(mon)
        return np.asarray(shot, dtype=np.uint8)[:, :, :3].copy()
    except Exception:
        return None


def capture_screen_bgr(monitor_index: int = 0) -> Optional[np.ndarray]:
    """Full-screen capture of a monitor via mss (robust, no window needed)."""
    import mss

    with mss.mss() as sct:
        monitors = sct.monitors  # index 0 = virtual all, 1.. = physical
        idx = min(monitor_index + 1, len(monitors) - 1)
        shot = sct.grab(monitors[idx])
        # mss gives BGRA; convert to BGR
        arr = np.asarray(shot, dtype=np.uint8)[:, :, :3].copy()
        return arr


def client_to_screen(hwnd: int, cx: int, cy: int) -> tuple[int, int]:
    """Convert client-area point (cx, cy) to screen coordinates."""
    pt = win32gui.ClientToScreen(hwnd, (cx, cy))
    return pt
