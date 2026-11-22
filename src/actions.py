"""
actions.py - human-ish mouse input (click at template-matched locations).

Coordinates come from template match regions. Movement is stepped with
randomized delays instead of teleporting, and click position jitters a few
pixels around the box center to avoid pixel-perfect repetition.
"""

from __future__ import annotations

import math
import random
import time
from typing import Optional

import win32api
import win32con

CLICK_DOWN_MS = (40, 90)
_stop_checker = None
_stop_latched = False
_message_held = None
_yield_enabled = False
_yield_idle_seconds = 5.0
_yield_tol = 25
_yield_log_fn = None
_last_bot_cursor = None


class UserYielded(Exception):
    """Reserved for callers opting into cancellation; boolean input APIs do not raise it."""


def configure_user_yield(enabled: bool = False, idle_seconds: float = 5.0,
                         tol: int = 25, log_fn=None) -> None:
    """Opt in per controller session; legacy callers remain unchanged."""
    global _yield_enabled, _yield_idle_seconds, _yield_tol, _yield_log_fn, _last_bot_cursor
    if not math.isfinite(idle_seconds) or idle_seconds < 0 or tol < 0:
        raise ValueError("User yield requires finite, nonnegative idle seconds and tolerance")
    _yield_enabled = bool(enabled)
    _yield_idle_seconds, _yield_tol, _yield_log_fn = float(idle_seconds), int(tol), log_fn
    _last_bot_cursor = None


def user_took_cursor(tol: int | None = None) -> bool:
    if not _yield_enabled or INPUT_MODE == "message":
        return False
    try:
        cur = win32api.GetCursorPos()
    except Exception:
        return False
    t = _yield_tol if tol is None else tol
    return _last_bot_cursor is not None and (
        abs(cur[0] - _last_bot_cursor[0]) > t or abs(cur[1] - _last_bot_cursor[1]) > t)


def wait_if_user_active(poll_interval: float = 0.25, sleep_fn=None, clock_fn=None) -> bool:
    """Wait for continuous idle without moving the cursor; Stop always propagates."""
    global _last_bot_cursor
    if not _yield_enabled or INPUT_MODE == "message":
        return False
    if not math.isfinite(poll_interval) or poll_interval <= 0:
        raise ValueError("poll_interval must be positive and finite")
    _check_input_stop()
    if not (user_took_cursor() or cursor_is_moving(samples=2, interval=0.05, tol=6)):
        return False
    sleep, clock = sleep_fn or time.sleep, clock_fn or time.monotonic
    if _yield_log_fn:
        _yield_log_fn(f"[yield] 检测到人工移动鼠标，暂停接管，鼠标静止 {_yield_idle_seconds:.0f} 秒后自动恢复")
    anchor, idle_since = None, clock()
    while True:
        _check_input_stop()
        now = clock()
        try:
            cur = win32api.GetCursorPos()
        except Exception:
            anchor, idle_since = None, now  # unreadable is not evidence of idle
        else:
            # Compare with the idle anchor, not just the last poll: slow drift counts too.
            if anchor is None or abs(cur[0] - anchor[0]) > 6 or abs(cur[1] - anchor[1]) > 6:
                anchor, idle_since = cur, now
            if now - idle_since >= _yield_idle_seconds:
                _last_bot_cursor = cur
                if _yield_log_fn:
                    _yield_log_fn("[yield] 鼠标已空闲，恢复自动操作")
                return True
        sleep(poll_interval)


def _user_yield_abort() -> bool:
    if not _yield_enabled or INPUT_MODE == "message":
        return False
    _check_input_stop()
    if user_took_cursor():
        _input_failed("物理输入", "检测到人工移动鼠标，已让权")
        return True
    return False


def _pause_physical(seconds: float) -> bool:
    """Never wait for idle with a button held: abort and let finally release it."""
    if not _yield_enabled:
        _pause_input(seconds)
        return True
    remaining = max(0.0, seconds)
    while remaining > 0:
        if _user_yield_abort():
            return False
        delay = min(.05, remaining)
        _pause_input(delay)
        remaining -= delay
    return not _user_yield_abort()


class InputStopped(KeyboardInterrupt):
    """Cooperative stop; release finally blocks run before the engine exits."""


def configure_stop(checker=None) -> None:
    global _stop_checker, _stop_latched
    _stop_checker, _stop_latched = checker, False


def stop_requested() -> bool:
    global _stop_latched
    if not _stop_latched and _stop_checker is not None:
        try:
            _stop_latched = bool(_stop_checker())
        except Exception:
            _stop_latched = True  # an unreadable stop channel cannot authorize input
    return _stop_latched


def _check_input_stop() -> None:
    if stop_requested():
        raise InputStopped()


def _pause_input(seconds: float) -> None:
    _check_input_stop()
    remaining = max(0.0, seconds)
    if _stop_checker is None:
        time.sleep(remaining)
    else:
        while remaining > 0:
            delay = min(.05, remaining)
            time.sleep(delay)
            remaining -= delay
            _check_input_stop()
    _check_input_stop()

# ★★ 安全点(和 `hand_scanner_v2.SAFE_POINT` 同一个点:屏幕中线最右侧,悬停不弹面板)。
#   2026-09-12 实机抓到的后果:攻击/上前线阶段**从不把光标挪走** ——
#   上一次拖拽把光标留在落点(战场上),于是 KARDS 弹出**放大的悬停面板**,
#   把旁边那张卡**整张盖住**:那一帧我方支援线 2 张卡只检出 1 张、徽章 0 个
#   (`shots/attack_frames/0912_032521_attack.png` 能看到那个面板把中间的坦克卡盖掉了)。
#   → 凡是要**读战场**,先把光标停到 SAFE_POINT(§10 坑 #3 那条规矩)。
SAFE_POINT_CLIENT = (1270, 360)


def park_cursor(hwnd, settle: float = 0.20) -> bool:
    """
    把光标停到安全点,让悬停面板消失,再读战场。

    返回是否成功(截图/坐标转换失败时返回 False,调用方照常继续 ——
    这只是让读数更干净,不该因为它失败就中断动作)。
    """
    try:
        from win import client_to_screen
        sx, sy = client_to_screen(hwnd, *SAFE_POINT_CLIENT)
        if not set_cursor(sx, sy):
            return False
        time.sleep(settle)
        return True
    except Exception:
        return False


# ---- 拖拽时序(2026-09-11 下午按实机观察重标;**2026-09-13 按用户要求提速**)----
# 用户实测(小号测试对局,两条都**稳定复现**):
#   ① 拖到**已有卡的位置**上松手 -> 牌**回手**(游戏不会自动吸附到邻近空位)
#   ② **快松 vs 停一秒再松**,结果不一样 -> 松太早这次投放不算数
# 所以把三段等待都摆出来。★ 2026-09-13 用户明确说:
#   "**拖动之后的确认时间(就是在目标上停留的时间)缩短到 400ms 就够**"
#   —— 于是 DWELL 1.0 -> **0.4**(实测这条占掉每回合好几秒:一个回合要拖 6~8 次)。
#   PRESS_DELAY(进拖拽态)和 RELEASE_SETTLE(结算)不动太多:
#   前者太短会被当成"点了一下卡",后者要够游戏把这次投放记下来。
PRESS_DELAY = 0.20
DWELL = 0.40
RELEASE_SETTLE = 0.20
# 停顿期间原地做的"小抖动"次数:有些 UI 只在收到鼠标**移动**事件时才刷新投放判定,
# 光标一动不动可能被当成"没在拖"。
DWELL_JIGGLE = 3
DWELL_JIGGLE_PX = 2


#: ★★★ 2026-09-19(v0.1.6):**输入失败必须"软着陆",不许把引擎带走。**
#
# 实机证据(用户 `E:\kards-auto` 那份日志,2026-09-19 13:47:12):
#   引擎走到卡组页面 -> 点「开始」-> `win32api.SetCursorPos` 抛异常:
#       pywintypes.error: (0, 'SetCursorPos', 'No error message is available')
#   -> 异常一路冒到 `main()`,被顶层处理器记下 traceback 然后**整个引擎退出**。
#   用户看到的现象是"**运行到卡组页面不会点确定**" —— 其实是点了就崩、原地不动。
#   同一份日志里还有 `SetWindowPos ... 拒绝访问`(想强制窗口 1280x720 时),
#   两个症状指向同一件事:**Windows 不让这个进程驱动游戏窗口**(典型原因是
#   游戏/Steam 以管理员身份运行,而本面板不是;也可能是不在同一个输入桌面)。
#
# 所以:鼠标操作**返回 bool**,失败时
#   ① 绝不继续按下/松开(那会点到别的地方,可能误关别的窗口 —— 比不点更糟);
#   ② 把"为什么"写成一句人话,由引擎打进 `logs/main_loop.log`(和 `kredits.LAST_REJECT`
#      同一个套路:模块记账,调用方负责说出去);
#   ③ 连着失败几次就补一句**该怎么办**的提示,而不是每 tick 刷屏。
LAST_INPUT_ERROR = None
#: 连续失败到几次时,补一条"怎么办"的提示(第一条和这一条会写日志,中间不刷屏)
INPUT_FAIL_HINT_AT = 3
_input_fails = 0

_INPUT_HINT = (
    "系统不让本程序移动鼠标(SetCursorPos 失败)。常见原因:**游戏/Steam 是以"
    "管理员身份运行的,而本面板不是** —— 那样 Windows 会挡住我们对游戏的"
    "移动/点击(同一次运行里往往还会看到 `SetWindowPos ... 拒绝访问`)。"
    "试试也**用管理员身份运行 KARDS AUTO.exe**(右键 -> 以管理员身份运行),"
    "或者让 Steam 和游戏都用普通权限启动。"
)


def _input_failed(what: str, err) -> None:
    """记一次"输入被系统挡住"。返回人话说明(由调用方决定打不打印)。"""
    global LAST_INPUT_ERROR, _input_fails
    _input_fails += 1
    LAST_INPUT_ERROR = f"{what} 失败({type(err).__name__}: {err})"
    if _input_fails >= INPUT_FAIL_HINT_AT and err != "检测到人工移动鼠标，已让权":
        hint = ("窗口消息输入未成功；确认 KARDS 前台可见且客户区为1280×720。"
                "游戏可能不响应消息输入；停止后关闭『不抢鼠标』可切回物理模式，不自动回退。"
                if INPUT_MODE == "message" else _INPUT_HINT)
        LAST_INPUT_ERROR += " —— " + hint
    return LAST_INPUT_ERROR


def set_cursor(x: int, y: int) -> bool:
    """
    把光标放到 (x, y)(**屏幕坐标**)。成功 True,失败 False(**不抛异常**)。

    ★ 2026-09-19:以前这里是一句裸的 `win32api.SetCursorPos`,它一抛异常,
      整轮就结束了(见文件头那段实机证据)。现在失败只记账,由调用方决定怎么办。
    """
    global _input_fails, _last_bot_cursor
    _check_input_stop()
    if INPUT_MODE == "message":
        return move_message(x, y)
    if _user_yield_abort():
        return False
    try:
        win32api.SetCursorPos((int(x), int(y)))
        try:
            _last_bot_cursor = win32api.GetCursorPos()
        except Exception:
            _last_bot_cursor = (int(x), int(y))
        if _input_fails:            # 恢复了 -> 清零(下次失败会重新提示)
            _input_fails = 0
        return True
    except Exception as e:
        _input_failed(f"把光标移到 ({int(x)},{int(y)})", e)
        return False


def take_input_error() -> str:
    """取走"上一次输入失败"的说明(取走即清,避免同一条反复打)。"""
    global LAST_INPUT_ERROR
    msg, LAST_INPUT_ERROR = LAST_INPUT_ERROR, None
    return msg



def cursor_position() -> tuple:
    """当前鼠标屏幕坐标。"""
    return win32api.GetCursorPos()


def set_cursor_checked(x: int, y: int):
    """
    把光标放到 (x,y),返回**实际**落点(读不到/放不下返回 None)。

    为什么不能想当然地认为"请求点 = 落点":Windows 会把光标裁剪在屏幕
    (或多显示器组成的桌面)范围内,窗口位置/DPI 一旦让目标点落到屏幕外,
    SetCursorPos 就会静默地把它拉回来。

    这在自动化里是要命的:如果按【请求点】记账,下一次 `cursor_moved_from()`
    就会把这点误差当成"用户正在操作鼠标",于是扫描在第一个探针就中止 ——
    实测表现就是 `hand scan #N: 0 cards in 0.8s`(根本没扫,但日志看不出原因)。

    ★ 2026-09-19:**放不下就不要读落点** —— 否则会把"上一次的旧位置"当成落点
      报回去,调用方会以为光标已经到了(比返回 None 更坏)。
    """
    if not set_cursor(x, y):
        return None
    if INPUT_MODE == "message":
        return (int(x), int(y))  # virtual hover point, never read the user's cursor
    try:
        return win32api.GetCursorPos()
    except Exception:
        return None


def cursor_moved_from(x: int, y: int, tol: int = 8) -> bool:
    """
    鼠标是否已经离开 (x,y) 超过 tol 像素。

    用途:自动化脚本把鼠标放到某处后,如果光标自己跑掉了,说明【用户正在操作】,
    脚本应当让路而不是继续抢鼠标。
    """
    if INPUT_MODE == "message":
        return False  # this channel does not own the system cursor
    try:
        cx, cy = win32api.GetCursorPos()
    except Exception:
        return False
    return abs(cx - x) > tol or abs(cy - y) > tol


def cursor_is_moving(samples: int = 4, interval: float = 0.07,
                     tol: int = 3) -> bool:
    """
    采样几次判断用户是否正在移动鼠标。

    和 cursor_moved_from 的区别:这个不需要脚本先"占位"再检查,所以可以在
    【还没碰鼠标之前】就判断用户忙不忙 —— 校准脚本用它来决定要不要开始。
    """
    try:
        prev = win32api.GetCursorPos()
    except Exception:
        return False
    for _ in range(max(1, samples - 1)):
        time.sleep(interval)
        try:
            cur = win32api.GetCursorPos()
        except Exception:
            return False
        if abs(cur[0] - prev[0]) > tol or abs(cur[1] - prev[1]) > tol:
            return True
        prev = cur
    return False


def move_stepped(x0: int, y0: int, x1: int, y1: int,
                 steps: Optional[int] = None) -> bool:
    """
    分几步把光标挪过去(带抖动,少一点机器味)。**全部成功才返回 True**。

    ★ 2026-09-19:第一步就失败的话**立刻停手** —— 后面的步子只会重复失败,
      而调用方(click/move_drag)要靠这个返回值决定"要不要按下去"。
    """
    dx = x1 - x0
    dy = y1 - y0
    dist = max(abs(dx), abs(dy))
    steps = steps or max(2, min(14, int(dist / 60)))
    for i in range(1, steps + 1):
        if _user_yield_abort():
            return False
        t = i / steps
        # slight easing + lateral jitter
        jx = random.randint(-3, 3)
        jy = random.randint(-3, 3)
        cx = int(x0 + dx * t + jx)
        cy = int(y0 + dy * t + jy)
        if not set_cursor(cx, cy):
            return False
        time.sleep(random.uniform(0.006, 0.022))
    return True


def click(x: int, y: int, jitter: int = 5) -> bool:
    """
    分步挪过去再点一下 (x,y)。成功 True,失败 False(**绝不抛异常**)。

    ★★ 2026-09-19 的硬规矩:**挪不过去就绝不按下去。**
      光标没到位时按下/松开,点的是**光标当时所在的地方** —— 那是屏幕上别的
      位置,可能正好是别的窗口的按钮(实测那类"手一抖点关了什么东西"就是这么来的)。
      宁可这一下不点,也不能乱点。

    ★ 2026-09-20:`INPUT_MODE == "message"` 时走**窗口消息**那条路(不碰真实光标),
      见文件末尾那一大段;能不能用要先靠 `dev\\click_probe.py` 实测。
    """
    if INPUT_MODE == "message":
        return click_message(x, y, jitter=jitter)
    if _yield_enabled:
        wait_if_user_active()
    jx = x + random.randint(-jitter, jitter)
    jy = y + random.randint(-jitter, jitter)
    try:
        cur = win32api.GetCursorPos()
    except Exception:
        cur = (jx, jy)                 # 读不到当前位置就直接过去(不再是"从(0,0)划过去")
    if not move_stepped(cur[0], cur[1], jx, jy):
        if not user_took_cursor():
            _input_failed(f"点到 ({jx},{jy})", "光标没挪到位")
        return False
    if _user_yield_abort():
        return False
    down = False
    try:
        down = True
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        if not _pause_physical(random.uniform(*CLICK_DOWN_MS) / 1000.0):
            return False
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        down = False
    except Exception as e:
        _input_failed(f"在 ({jx},{jy}) 按下鼠标", e)
        return False
    finally:
        if down:
            try:
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            except Exception as error:
                _input_failed("物理点击释放", error)
    return True


def click_center_of(region: dict, jitter: int = 5) -> bool:
    """region: {x,y,w,h} -> click its center (screen coords expected)."""
    cx = region["x"] + region["w"] // 2
    cy = region["y"] + region["h"] // 2
    return click(cx, cy, jitter)


def move_drag(sx: int, sy: int, ex: int, ey: int,
              press_delay: float = None,
              settle: float = 0.15,
              dwell: float = None,
              jiggle: int = None,
              on_pressed=None) -> bool:
    """
    在**屏幕坐标**之间做一次拖拽(按下 -> 分步移动 -> **在目标上停住** -> 松开)。

    部署(手牌 -> 我方阵线)和攻击(场上单位 -> 敌方目标)都是这个鼠标序列,
    所以抽到这里共用。

    ★★ 2026-09-13 下午(第十个会话):**`settle` 现在有两个语义,别搞混** ——
      它既是"光标到位后等多久才按下",也是**按下那一刻画面处在哪个状态**的开关。
      从**手牌**拖牌时它必须是**悬停等待**(`hand_scanner_v2.HOLD`,0.30s):
        · 识别身份是在"悬停之后(扇形已展开)"那一帧做的;
        · 而旧代码只等 `settle=0.15s` 就按下 —— 那一刻扇形**还在展开动画里**,
          同一个 x 底下的牌可能已经换成**邻居**了;
        · 实测证据(2026-09-13 那局日志):第 6/7 回合都写着
          `deploying Fw 190 A 百舌鸟 (fighter, cost 6) 手牌x=455`,
          而**费用读数只掉了 3**(`费用读数 3 与账本 0 不符` / `4 与账本 1 不符`)
          —— 拖出去的其实是一张 **3 费牌**(用户看到的是"旁边的 38t")。
      ⇒ 判据:**读身份用哪个状态,按下就用哪个状态**。`drag_deploy` 会把
        `settle` 设成扫描器的 `HOLD`;`move_drag` 本身不动默认值 ——
        攻击那一路拖的是**盘面上的卡**,没有扇形展开问题,保持 0.15 快一点。

    `on_pressed()`:按下之后立刻回调一次(用来**当场存一帧** —— 拖起来的那张牌
    会画在光标上,是"到底抓了哪张牌"唯一的**地面真值**)。

    ★★ 2026-09-11 下午按实机观察重标的三件事(每一件都对应一个实测现象):
      ① **按下后多等一会儿再动**(`PRESS_DELAY` 0.12 -> 0.25s):
         太短可能连"拖拽态"都没进,游戏把这一下当成"点了一下卡"。
      ② **到达目标后精确落位再停**:`move_stepped` 每一步都带 ±3px 抖动
         (末步也一样),所以"停在哪"是随机的 —— 必须再 `set_cursor` 一次
         把它钉在 (ex, ey) 上,停顿才有意义。
      ③ **停住 1 秒(jiggle 几次)再松手**:用户实测"快松 vs 停一秒"结果不同。
         停顿期间做几次 1-2px 的小幅移动,是为了让游戏**持续收到鼠标移动事件**
         —— 光标一动不动有可能被当成"没在拖"。
    """
    if press_delay is None:
        press_delay = PRESS_DELAY
    if dwell is None:
        dwell = DWELL
    if jiggle is None:
        jiggle = DWELL_JIGGLE

    # ★ 2026-09-20:消息模式(不碰真实光标)—— 见文件末尾那一大段。
    if INPUT_MODE == "message":
        return drag_message(sx, sy, ex, ey, hold=dwell, press_delay=press_delay,
                            settle=settle, on_pressed=on_pressed)
    if _yield_enabled:
        wait_if_user_active()

    # ★ 2026-09-19:按下之前先确认"光标真能挪到起点" —— 挪不过去就**不要按**,
    #   否则按下/松开落在光标当时所在的地方(屏幕上别的位置),那比不拖更糟。
    if not set_cursor(sx, sy):
        if not user_took_cursor():
            _input_failed(f"拖拽起点 ({sx},{sy})", "光标没挪到位")
        return False
    down = False
    try:
        if not _pause_physical(settle):
            return False
        down = True  # even an uncertain DOWN must be followed by a release attempt
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        if not _pause_physical(press_delay):
            return False
        if on_pressed is not None:
            try:
                on_pressed()
            except Exception:
                pass
        try:
            cur = win32api.GetCursorPos()
        except Exception:
            cur = (sx, sy)
        if not move_stepped(cur[0], cur[1], ex, ey):
            if _yield_enabled:
                return False
            raise OSError("拖拽中途挪不动")
        if not set_cursor(ex, ey):
            if _yield_enabled:
                return False
            raise OSError("拖拽精确落位失败")
        per = min(.12, max(.04, dwell / (jiggle + 1))) if jiggle else 0.0
        for i in range(max(0, jiggle)):
            off = DWELL_JIGGLE_PX if i % 2 == 0 else -DWELL_JIGGLE_PX
            if not set_cursor(ex + off, ey + off):
                if _yield_enabled:
                    return False
                raise OSError("拖拽停留移动失败")
            if not _pause_physical(per):
                return False
        if not set_cursor(ex, ey):
            if _yield_enabled:
                return False
            raise OSError("拖拽最终落位失败")
        if not _pause_physical(max(0.0, dwell - per * max(0, jiggle))):
            return False
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        down = False
        _pause_input(RELEASE_SETTLE)
        return True
    except Exception as error:
        _input_failed(f"拖到 ({ex},{ey})", error)
        return False
    finally:
        if down:
            try:
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            except Exception as error:
                _input_failed("物理拖拽释放", error)


# ===========================================================================
# Window-message input is experimental: transport success is not game acceptance.
# The runtime binds the discovered KARDS hwnd; there is never physical fallback.
# Standalone click_probe calls may still resolve a window under a point.
INPUT_MODE = "physical"
MESSAGE_HWND = None


def configure_input(mode: str, hwnd=None) -> None:
    """Select once at engine startup; changing GUI settings does not hot-switch."""
    global INPUT_MODE, MESSAGE_HWND
    if mode not in ("physical", "message"):
        raise ValueError(f"Unknown input mode: {mode}")
    INPUT_MODE = mode
    MESSAGE_HWND = int(hwnd) if mode == "message" and hwnd else None


def bind_message_window(hwnd) -> None:
    global MESSAGE_HWND
    if INPUT_MODE == "message":
        MESSAGE_HWND = int(hwnd) if hwnd else None


def window_under(sx: int, sy: int):
    """Resolve a top-level window for standalone diagnostic probes only."""
    import win32gui
    try:
        hwnd = win32gui.WindowFromPoint((int(sx), int(sy)))
        if not hwnd:
            return None, 0, 0
        root = win32gui.GetAncestor(hwnd, win32con.GA_ROOT) or hwnd
        cx, cy = win32gui.ScreenToClient(root, (int(sx), int(sy)))
        return root, cx, cy
    except Exception:
        return None, 0, 0


def _message_point(sx: int, sy: int, hwnd=None):
    """Fail closed on missing/stale/covered/nonforeground target or bad geometry."""
    import win32gui
    target = hwnd or MESSAGE_HWND
    if not target:
        if INPUT_MODE == "message":
            raise ValueError("未绑定 KARDS 窗口，不发送消息")
        target, _, _ = window_under(sx, sy)
    if not target or not win32gui.IsWindow(target):
        raise ValueError("目标窗口已失效")
    if win32gui.IsIconic(target) or not win32gui.IsWindowVisible(target):
        raise ValueError("目标窗口最小化或不可见")
    foreground = win32gui.GetForegroundWindow()
    foreground = win32gui.GetAncestor(foreground, win32con.GA_ROOT) or foreground
    if foreground != target:
        raise ValueError("KARDS 不在前台")
    covering = win32gui.WindowFromPoint((int(sx), int(sy)))
    covering = win32gui.GetAncestor(covering, win32con.GA_ROOT) or covering
    if covering != target:
        raise ValueError("输入位置被其他窗口遮挡")
    origin = _message_origin(target)
    for coordinate in (sx, sy):
        source = getattr(coordinate, "input_source", None)
        if source is not None and source != (int(target), origin):
            raise ValueError("坐标换算来源窗口已移动或更换，不使用旧屏幕坐标")
    cx, cy = win32gui.ScreenToClient(target, (int(sx), int(sy)))
    if (cx, cy) != (int(sx) - origin[0], int(sy) - origin[1]):
        raise ValueError("坐标换算期间窗口位置发生变化")
    left, top, right, bottom = win32gui.GetClientRect(target)
    if MESSAGE_HWND and (right - left, bottom - top) != (1280, 720):
        raise ValueError("KARDS 客户区不是 1280×720")
    if not (left <= cx < right and top <= cy < bottom and cx <= 32767 and cy <= 32767):
        raise ValueError("消息坐标超出客户区")
    _check_message_origin(target, origin)
    return target, cx, cy


def _message_origin(hwnd):
    import win32gui
    return win32gui.ClientToScreen(hwnd, (0, 0))


def _check_message_origin(hwnd, origin) -> None:
    if _message_origin(hwnd) != origin:
        raise ValueError("窗口位置已变化，停止使用旧屏幕坐标")


def _message_succeeded() -> None:
    global _input_fails
    _input_fails = 0


def _lp(x: int, y: int) -> int:
    return (int(x) & 0xFFFF) | ((int(y) & 0xFFFF) << 16)


def _send(hwnd, msg: int, wparam: int, lparam: int, sync: bool) -> None:
    import win32gui
    global _message_held
    if msg != win32con.WM_LBUTTONUP:
        _check_input_stop()
    if msg == win32con.WM_LBUTTONDOWN:
        _message_held = (hwnd, lparam)
    (win32gui.SendMessage if sync else win32gui.PostMessage)(hwnd, msg, wparam, lparam)
    if msg == win32con.WM_LBUTTONUP:
        _message_held = None


def release_message_input() -> bool:
    """Cleanup only: release the same target without focus/geometry or stop gates."""
    if _message_held is None:
        return True
    hwnd, point = _message_held
    try:
        _send(hwnd, win32con.WM_LBUTTONUP, 0, point, False)
        return True
    except Exception as error:
        _input_failed("停止时释放消息按键", error)
        return False


def move_message(sx: int, sy: int) -> bool:
    """Hover/park without SetCursorPos. True means posted, not visibly hovered."""
    try:
        hwnd, cx, cy = _message_point(sx, sy)
        _send(hwnd, win32con.WM_MOUSEMOVE, 0, _lp(cx, cy), False)
        _message_succeeded()
        return True
    except Exception as e:
        _input_failed(f"消息悬停 ({sx},{sy})", e)
        return False


def click_message(sx: int, sy: int, jitter: int = 5, hold: float = 0.05,
                  sync: bool = False, moves: int = 2) -> bool:
    """Post a click to the bound game only; no physical input or auto-focus."""
    hwnd, cx, cy, down = None, 0, 0, False
    jx, jy = sx, sy
    try:
        hwnd, base_x, base_y = _message_point(sx, sy)  # validate provenance before jitter loses metadata
        origin = (int(sx) - base_x, int(sy) - base_y)
        jx, jy = sx + random.randint(-jitter, jitter), sy + random.randint(-jitter, jitter)
        _, cx, cy = _message_point(jx, jy, hwnd)
        _check_message_origin(hwnd, origin)
        for _ in range(max(1, moves)):
            _send(hwnd, win32con.WM_MOUSEMOVE, 0, _lp(cx, cy), sync)
            _pause_input(0.012)
        _message_point(jx, jy, hwnd)  # state may change during hover
        _check_message_origin(hwnd, origin)
        down = True  # attempt release even if posting DOWN raises
        _send(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, _lp(cx, cy), sync)
        _pause_input(hold)
        _message_point(jx, jy, hwnd)
        _check_message_origin(hwnd, origin)
        _send(hwnd, win32con.WM_LBUTTONUP, 0, _lp(cx, cy), sync)
        down = False
        _message_succeeded()
        return True
    except Exception as e:
        _input_failed(f"消息点击 ({jx},{jy})", e)
        return False
    finally:
        if down and hwnd:
            try:
                _send(hwnd, win32con.WM_LBUTTONUP, 0, _lp(cx, cy), sync)
            except Exception as e:
                _input_failed("消息点击释放", e)


def drag_message(sx: int, sy: int, ex: int, ey: int, steps: int = 14,
                 hold: float = 0.40, press_delay: float = 0.20,
                 sync: bool = False, settle: float = 0.15, on_pressed=None) -> bool:
    """Preserve hover/press/dwell/callback; failed delivery never means accepted."""
    hwnd, cx0, cy0, down = None, 0, 0, False
    try:
        hwnd, cx0, cy0 = _message_point(sx, sy)
        origin = (int(sx) - cx0, int(sy) - cy0)
        _, cx1, cy1 = _message_point(ex, ey, hwnd)
        _check_message_origin(hwnd, origin)
        _send(hwnd, win32con.WM_MOUSEMOVE, 0, _lp(cx0, cy0), sync)
        _pause_input(max(0.0, settle))
        _message_point(sx, sy, hwnd)
        _message_point(ex, ey, hwnd)
        _check_message_origin(hwnd, origin)
        down = True
        _send(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, _lp(cx0, cy0), sync)
        _pause_input(max(0.0, press_delay))
        if on_pressed is not None:
            try:
                on_pressed()
            except Exception:
                pass  # evidence callback must not leave a held button
        n = max(2, int(steps))
        for i in range(1, n + 1):
            t = i / n
            _message_point(sx + (ex - sx) * t, sy + (ey - sy) * t, hwnd)
            _check_message_origin(hwnd, origin)
            mx, my = int(cx0 + (cx1 - cx0) * t), int(cy0 + (cy1 - cy0) * t)
            _send(hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, _lp(mx, my), sync)
            _pause_input(0.02)
        _pause_input(max(0.0, hold))
        _message_point(ex, ey, hwnd)
        _check_message_origin(hwnd, origin)
        _send(hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, _lp(cx1, cy1), sync)
        _send(hwnd, win32con.WM_LBUTTONUP, 0, _lp(cx1, cy1), sync)
        down = False
        _pause_input(RELEASE_SETTLE)
        _message_succeeded()
        return True
    except Exception as e:
        _input_failed(f"消息拖拽 ({sx},{sy})->({ex},{ey})", e)
        return False
    finally:
        if down and hwnd:
            try:
                _send(hwnd, win32con.WM_LBUTTONUP, 0, _lp(cx0, cy0), sync)
            except Exception as e:
                _input_failed("消息拖拽释放", e)
