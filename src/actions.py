"""
actions.py - human-ish mouse input (click at template-matched locations).

Coordinates come from template match regions. Movement is stepped with
randomized delays instead of teleporting, and click position jitters a few
pixels around the box center to avoid pixel-perfect repetition.
"""

from __future__ import annotations

import random
import time
from typing import Optional

import win32api
import win32con

CLICK_DOWN_MS = (40, 90)

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
        set_cursor(sx, sy)
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
    if _input_fails >= INPUT_FAIL_HINT_AT:
        LAST_INPUT_ERROR += " —— " + _INPUT_HINT
    return LAST_INPUT_ERROR


def set_cursor(x: int, y: int) -> bool:
    """
    把光标放到 (x, y)(**屏幕坐标**)。成功 True,失败 False(**不抛异常**)。

    ★ 2026-09-19:以前这里是一句裸的 `win32api.SetCursorPos`,它一抛异常,
      整轮就结束了(见文件头那段实机证据)。现在失败只记账,由调用方决定怎么办。
    """
    global _input_fails
    try:
        win32api.SetCursorPos((int(x), int(y)))
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
    jx = x + random.randint(-jitter, jitter)
    jy = y + random.randint(-jitter, jitter)
    try:
        cur = win32api.GetCursorPos()
    except Exception:
        cur = (jx, jy)                 # 读不到当前位置就直接过去(不再是"从(0,0)划过去")
    if not move_stepped(cur[0], cur[1], jx, jy):
        _input_failed(f"点到 ({jx},{jy})", "光标没挪到位")
        return False
    try:
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(random.uniform(*CLICK_DOWN_MS) / 1000.0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    except Exception as e:
        _input_failed(f"在 ({jx},{jy}) 按下鼠标", e)
        return False
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
        return drag_message(sx, sy, ex, ey, hold=dwell, press_delay=press_delay)

    # ★ 2026-09-19:按下之前先确认"光标真能挪到起点" —— 挪不过去就**不要按**,
    #   否则按下/松开落在光标当时所在的地方(屏幕上别的位置),那比不拖更糟。
    if not set_cursor(sx, sy):
        _input_failed(f"拖拽起点 ({sx},{sy})", "光标没挪到位")
        return False
    time.sleep(settle)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(press_delay)
    if on_pressed is not None:
        # 诊断回调:现在光标上就挂着"被拖起来的那张牌"。
        # ★ 绝不许它把拖拽弄崩(§7 第 57 条:诊断代码只许丢一行日志)。
        try:
            on_pressed()
        except Exception:
            pass
    try:
        cur = win32api.GetCursorPos()
    except Exception:
        cur = (ex, ey)
    if not move_stepped(cur[0], cur[1], ex, ey):
        # 已经按下去了,但挪不到目标 —— **松手回原位**(放回手牌)比乱放好。
        # 中途松手会落在光标当前所在的格子上;这里选择直接松开并如实报失败,
        # 交给上层按"这一发没发出去"记账(和 `attack._attack` 的 fail-soft 一致)。
        try:
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        except Exception:
            pass
        _input_failed(f"拖到 ({ex},{ey})", "中途挪不动")
        return False

    # ② 精确落位:分步移动的末步带抖动,不钉一下的话落点是随机的
    set_cursor(ex, ey)
    # ③ 在目标上停住:小幅抖动几下 + 保持 dwell 秒,再松手
    #   ★★ 2026-09-13:"抖动"的时间**算在 dwell 里面**,不再额外加 ——
    #      用户的判据是"**在目标上停留总共 400ms 就够**",所以整段停留必须 ≈ dwell,
    #      而不是 dwell + 抖动(旧写法实际停 1.36s,后来会变成 0.7s,和用户说的不符)。
    _per = min(0.12, max(0.04, dwell / (jiggle + 1))) if jiggle else 0.0
    for i in range(max(0, jiggle)):
        off = DWELL_JIGGLE_PX if i % 2 == 0 else -DWELL_JIGGLE_PX
        set_cursor(ex + off, ey + off)
        time.sleep(_per)
    set_cursor(ex, ey)
    time.sleep(max(0.0, dwell - _per * max(0, jiggle)))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(RELEASE_SETTLE)
    return True


# ===========================================================================
# ★★★ 2026-09-20:**"不抢鼠标"那条路 —— 窗口消息输入**(默认关,先实测再开)
#
# 用户原话:*"程序运行抢鼠标很烦,有没有可能模拟鼠标点击……前提是不注入内存,
# 完全物理操作"*。先把结论写在这儿,免得以后又绕回来:
#
#   ① **物理层做不到"不抢"** —— Windows **只有一个系统光标**,`SendInput` /
#      `mouse_event` / `SetCursorPos` 动的就是它。硬件盒子(KMBox / Arduino HID)
#      也一样:它模拟的是一只**真鼠标**,动的还是**同一个**光标,只是更难被
#      软件发现 —— 所以"换硬件"并不能解决抢鼠标这件事。
#   ② 真正不抢的只有两条路:**不碰光标、直接往窗口发消息**(本段),或者
#      **换一个会话/机器**(把游戏放进另一个 Windows 会话或虚拟机)。
#
# ① 能不能用**完全取决于游戏**:消息是"投递"给窗口的,而游戏有可能压根不看窗口
#   消息(改成 Raw Input 直接读设备;UE 就有 `Slate.ForceRawInputSimulation`
#   这类开关)。**这一条只能实测** —— `dev\click_probe.py` 就是干这个的,它走的
#   就是本段这几个函数:探针说能用,把 `INPUT_MODE` 改成 `"message"`,
#   `click` / `move_drag` 两条路会**整体**切过去。
#
# ★ 实测通过之后也要记住的取舍:
#   · 消息点击**没有"光标在哪"这回事** —— `park_cursor`(把光标挪到安全点、让悬停
#     面板消失)在消息模式下没有意义;不过画面上那个放大悬停面板是**上一次物理
#     悬停**留下的,只要不再物理移动光标,它就不会被刷新(想清掉还是得物理挪一次)。
#   · 让行判据 `cursor_moved_from` 只对物理模式有意义(消息模式本来就没占光标,
#     也就没有"用户在抢"这回事)。
# ===========================================================================
INPUT_MODE = "physical"          # "physical"(默认,老行为) | "message"


def window_under(sx: int, sy: int):
    """
    屏幕坐标 (sx, sy) 底下那个**顶层窗口**,连同它的客户区坐标一起返回。

    为什么用"点底下是谁"、而不是让调用方把 hwnd 一路传下来:引擎里几百个调用点
    手里只有屏幕坐标(`click(sx, sy)`),这样**改一处**就能整体切到消息模式。
    """
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


def _lp(x: int, y: int) -> int:
    """WM_* 鼠标消息的 lParam:低 16 位是 x、高 16 位是 y(**客户区坐标**)。"""
    return (int(x) & 0xFFFF) | ((int(y) & 0xFFFF) << 16)


def _send(hwnd, msg: int, wparam: int, lparam: int, sync: bool) -> None:
    import win32gui
    (win32gui.SendMessage if sync else win32gui.PostMessage)(hwnd, msg, wparam, lparam)


def click_message(sx: int, sy: int, jitter: int = 5, hold: float = 0.05,
                  sync: bool = False, moves: int = 2) -> bool:
    """
    往 (sx, sy) 底下的窗口**发消息**点一下 —— **完全不碰真实光标**。

    `sync=True` 用 `SendMessage`(等窗口处理完才返回,更像真点击,但游戏卡住时
    会把我们自己也卡住);默认 `PostMessage`(投递完就返回)。

    ★ 返回 True 只代表"消息投出去了",**不代表游戏认了** —— 认没认要看界面有没有变
      (`dev\\click_probe.py` 就是拿界面状态当判据)。
    """
    jx = sx + random.randint(-jitter, jitter)
    jy = sy + random.randint(-jitter, jitter)
    hwnd, cx, cy = window_under(jx, jy)
    if not hwnd:
        _input_failed(f"消息点到 ({jx},{jy})", "那个位置底下没有窗口")
        return False
    try:
        # 先送几次"移动":很多 UI 只在收到鼠标移动之后才做命中判定/画高亮
        for _ in range(max(1, moves)):
            _send(hwnd, win32con.WM_MOUSEMOVE, 0, _lp(cx, cy), sync)
            time.sleep(0.012)
        _send(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, _lp(cx, cy), sync)
        time.sleep(hold)
        _send(hwnd, win32con.WM_LBUTTONUP, 0, _lp(cx, cy), sync)
        return True
    except Exception as e:
        _input_failed(f"消息点到 ({jx},{jy})", e)
        return False


def drag_message(sx: int, sy: int, ex: int, ey: int, steps: int = 14,
                 hold: float = 0.40, press_delay: float = 0.20,
                 sync: bool = False) -> bool:
    """
    窗口消息版的拖拽(部署手牌、攻击敌方目标走的都是这条)。

    ★ 和物理版一样保留三段时序(按下后等一会儿才动 / 在目标上停住 / 停够再松),
      因为那三段是**实测出来**的(见 `move_drag` 的说明),换成消息投递之后
      游戏那边的判定逻辑没变,时序大概也得照旧。

    ★ 起点和终点都在游戏窗口里(拖拽本来就是窗口内操作),所以只取**起点**底下的
      窗口,终点按同一个窗口换算客户区坐标。
    """
    import win32gui
    hwnd, cx0, cy0 = window_under(sx, sy)
    if not hwnd:
        _input_failed(f"消息拖拽起点 ({sx},{sy})", "那个位置底下没有窗口")
        return False
    try:
        cx1, cy1 = win32gui.ScreenToClient(hwnd, (int(ex), int(ey)))
    except Exception:
        cx1, cy1 = cx0, cy0
    try:
        _send(hwnd, win32con.WM_MOUSEMOVE, 0, _lp(cx0, cy0), sync)
        time.sleep(0.05)
        _send(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, _lp(cx0, cy0), sync)
        time.sleep(press_delay)
        n = max(2, int(steps))
        for i in range(1, n + 1):
            t = i / n
            mx = int(cx0 + (cx1 - cx0) * t)
            my = int(cy0 + (cy1 - cy0) * t)
            _send(hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, _lp(mx, my), sync)
            time.sleep(0.02)
        # 在目标上停住(和物理版同一个理由:快松会被当成没投放)
        time.sleep(max(0.0, hold))
        _send(hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, _lp(cx1, cy1), sync)
        _send(hwnd, win32con.WM_LBUTTONUP, 0, _lp(cx1, cy1), sync)
        return True
    except Exception as e:
        _input_failed(f"消息拖到 ({ex},{ey})", e)
        return False
