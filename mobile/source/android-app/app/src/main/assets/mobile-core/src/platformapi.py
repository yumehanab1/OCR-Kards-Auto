"""
platformapi.py - **平台层**:引擎碰"这台机器"的每一个口子都从这里过。

为什么要有这个文件(2026-09-17,用户定了最终形态之后):
    * 用户的要求是"**把整个脚本挪到手机上跑**",最终做成**原生手机 app + 悬浮窗**。
    * 全项目盘过一遍:35 个文件 `from win import ...`、`actions.py` 直接用 `win32api`
      —— 但**它们调的就那么几个动作**:拿一帧、点一下、拖一下、问窗口多大。
    * 所以把那几个动作抽成一层,Windows 一份实现、Android 一份实现,
      **识别层/判据层/回合引擎一行都不用改**(这是这个文件存在的全部理由)。

★ 设计上刻意做的三个选择:
  ① **`win.py` / `actions.py` 自己转向,而不是改 35 个调用方**。
     调用方照旧 `from win import capture_client_bgr`,在 Windows 上走的还是老代码
     (一个字节都没动),在 Android 上自动换成 android 实现。**改动面最小 = 回归风险最小。**
  ② **接口就是引擎真正用到的那些**,不多一个不少一个。写多了就等于凭空造 API,
     以后没人知道哪个是真的在用。
  ③ **输入用"原语"(按下/移动/松开)+ `flush_input()`**,不是 `click()/drag()`。
     原因很实在:引擎的拖拽是**分步移动 + 抖动 + 停在目标上**(`actions.move_drag`),
     在电脑上那是一条条即时生效的鼠标事件;在 Android 上每一条 `input` 都是一次
     **进程启动**(实测每条 30~100ms),照搬会把一个拖拽拖成好几秒。
     所以 Android 那侧**先把原语记下来,`flush_input()` 时合并成一条 `input swipe`** ——
     对游戏来说那是一条更真实的触摸轨迹(带中间点),又快。

规矩(和项目其它部分一致):
    * **读数失败要能区分"拿不到"和"拿到了空"** —— `capture_client_bgr` 拿不到返回 None;
    * **平台不支持的动作要明确报错**,不许静默什么都不做(静默 = 排查时最贵的那种 bug);
    * 每个平台的**真实尺寸**由它自己报(`client_size`),引擎按它缩放,不假设分辨率。
"""

from __future__ import annotations

import os
import sys

#: 引擎赖以工作的基准客户区(全部判据/坐标表都是按这个尺寸标的)。
BASE_CLIENT = (1280, 720)

_current = None


class Platform:
    """
    平台接口 —— 引擎需要的**全部**机器相关能力。

    实现这一层就够移植,别的都不用碰。
    """

    name = "base"

    # ---- 画面 ----
    def capture_client(self, hwnd=None):
        """抓一帧**游戏客户区**的 BGR 图(`numpy.ndarray`);拿不到返回 `None`。"""
        raise NotImplementedError

    def capture_screen(self, monitor_index: int = 0):
        """抓一帧整屏(诊断用);拿不到返回 `None`。"""
        return None

    # ---- 几何 ----
    def find_game_window(self):
        """找到游戏窗口,返回句柄(找不到返回 `None`)。Android 上返回一个占位标记。"""
        raise NotImplementedError

    def client_size(self, hwnd) -> tuple:
        """客户区尺寸 (w, h)。"""
        raise NotImplementedError

    def set_client_size(self, hwnd, w: int, h: int) -> bool:
        """把客户区调成 w×h(做不到就返回 False,**不抛异常**)。"""
        return False

    def client_to_screen(self, hwnd, cx: int, cy: int) -> tuple:
        """客户区坐标 -> 屏幕坐标(点鼠标用的那套坐标)。"""
        raise NotImplementedError

    def window_capturable(self, hwnd, quiet: bool = True) -> bool:
        """现在能不能稳定抓到画面(被遮挡/最小化时返回 False)。"""
        return True

    def foreground_window(self):
        """当前前台窗口(用来判断"用户是不是切走了")。"""
        return None

    def bring_to_front(self, hwnd) -> None:
        """把游戏窗口提到最前(做不到就什么都不做)。"""
        pass

    def set_dpi_aware(self) -> None:
        """让本进程按物理像素看屏幕(DPI 缩放会让坐标全错)。"""
        pass

    # ---- 光标 / 输入原语 ----
    def cursor_pos(self):
        """当前光标位置;这个平台没有光标概念时返回 `None`。"""
        return None

    def set_cursor(self, x: int, y: int) -> None:
        """把光标移到 (x,y)(**屏幕坐标**)。"""
        raise NotImplementedError

    def mouse_down(self) -> None:
        raise NotImplementedError

    def mouse_move(self, x: int, y: int) -> None:
        raise NotImplementedError

    def mouse_up(self) -> None:
        raise NotImplementedError

    def flush_input(self) -> None:
        """
        原语发完之后调一次,让实现有机会把攒下来的动作**合并成一条**发出去。

        Windows 上什么都不用做(每条鼠标事件本来就是即时的);
        Android 上这一步才真正执行 —— 见文件头 ③。
        """
        pass


class NullPlatform(Platform):
    """
    什么都不会的平台 —— **用来让"平台没选对"当场暴露**,而不是静默跑一局空转。

    ★ 为什么要有这个东西:如果某个平台上 `capture_client` 悄悄返回 None、
    `set_cursor` 悄悄什么都不干,表现就是"引擎在跑、但一次都不动作",
    而日志里只有一堆 `state -> None`(2026-09-15 那次 PrintWindow 空壳图就是这个形状)。
    所以这里**一律把话说清楚**。
    """

    name = "null"

    def _no(self, what):
        raise RuntimeError(
            f"当前平台没有实现 {what} —— platformapi 没选对平台?"
            f"(sys.platform={sys.platform!r})")

    def capture_client(self, hwnd=None):
        return None

    def find_game_window(self):
        return None

    def client_size(self, hwnd):
        self._no("client_size")

    def client_to_screen(self, hwnd, cx, cy):
        self._no("client_to_screen")

    def set_cursor(self, x, y):
        self._no("set_cursor")

    def mouse_down(self):
        self._no("mouse_down")

    def mouse_move(self, x, y):
        self._no("mouse_move")

    def mouse_up(self):
        self._no("mouse_up")


def is_android() -> bool:
    """
    这台机器是不是 Android(Termux / 原生 app 里跑)。

    ★ 判据取"能证伪的那一条":`sys.platform == 'android'`(CPython 官方的 Android 构建会这么报),
      或者 Termux 的 `PREFIX`/家目录存在(实测 Termux 里 `sys.platform` 还是 `'linux'`,
      它是**打补丁的 CPython**,不能只看 platform)。
    """
    if sys.platform == "android":
        return True
    if os.environ.get("ANDROID_ROOT") and os.environ.get("PREFIX", "").startswith(
            "/data/data/com.termux"):
        return True
    return os.path.isdir("/data/data/com.termux/files/usr")


def choose() -> Platform:
    """
    按当前环境挑一个实现。

    ★ **import 放在函数里**:Windows 那份实现要 import win32*,在 Android 上那些模块
      根本不存在 —— 放在文件顶层会让整个模块 import 失败(而它是所有人的入口)。

    ★ `KARDS_PLATFORM` 环境变量可以**强制**选一个(值:`android` / `windows` / `null`)。
      为什么需要它:有一类用法是"**引擎跑在电脑上,手脚接在设备上**"
      (调解器/调试时很有用),还有用例要指定平台。
      没有它的话,平台只能由"跑在哪台机器上"决定,那种用法就没法试了。
    """
    force = (os.environ.get("KARDS_PLATFORM") or "").strip().lower()
    if force == "null":
        return NullPlatform()
    if force == "android" or (not force and not os.name == "nt" and is_android()):
        from platform_android import AndroidPlatform
        return AndroidPlatform(
            host=os.environ.get("KARDS_ADB_HOST", "127.0.0.1"),
            port=int(os.environ.get("KARDS_ADB_PORT", "16512")),
            serial=os.environ.get("KARDS_ADB_SERIAL", ""),
            use_su=(os.environ.get("KARDS_ADB_SU", "").strip() in ("1", "true", "yes")),
        )
    if force == "windows" or os.name == "nt":
        from platform_win import WindowsPlatform
        return WindowsPlatform()
    return NullPlatform()


def get() -> Platform:
    """拿当前平台(第一次调用时定下来,之后一直是同一个)。"""
    global _current
    if _current is None:
        _current = choose()
    return _current


def set_platform(p: Platform) -> None:
    """
    强制换一个实现 —— **给用例用的**(这样平台层本身也能离线考,不需要真的设备)。
    """
    global _current
    _current = p
