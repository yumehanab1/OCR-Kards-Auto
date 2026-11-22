"""
actions_test.py - 鼠标动作的**离线**用例(不需要游戏、不需要窗口)。

为什么值得单独一套
------------------
2026-09-19 那份实机日志(`E:\\kards-auto`,v0.1.5)里,引擎走到卡组页面、
点「开始」时崩在这儿:

    pywintypes.error: (0, 'SetCursorPos', 'No error message is available')
    -> 异常一路冒到 main() -> 记下 traceback -> **整个引擎退出**

用户看到的现象是"**运行到卡组页面不会点确定**"。所以这一套用例只考两件事:

  ① **失败不许抛异常**("输入被系统挡住"是可预期的环境问题,不是崩溃);
  ② ★ **光标挪不过去就绝不许按下去** —— 按下/松开落在光标**当时**所在的地方,
     那是屏幕上别的位置,可能正好是别的窗口的按钮(比"这一下不点"危险得多)。

`win32api` 用假替身喂进去,所以整套用例不碰真实鼠标。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))

import actions  # noqa: E402

ALLOK = True


def C(label, cond, extra=""):
    global ALLOK
    ALLOK &= bool(cond)
    print(f"  {'OK ' if cond else 'FAIL'} {label}" + (f"   {extra}" if extra else ""))


class FakeWin32:
    """假 win32api:可以设定"移动会不会失败""按了几次鼠标"。"""

    def __init__(self, fail_move=False, fail_read=False):
        self.fail_move = fail_move
        self.fail_read = fail_read
        self.pos = (100, 100)
        self.moves = 0
        self.buttons = []          # 记录按下/松开,用来判"有没有乱点"

    def SetCursorPos(self, pt):
        if self.fail_move:
            raise OSError(0, "SetCursorPos", "No error message is available")
        self.moves += 1
        self.pos = (int(pt[0]), int(pt[1]))

    def GetCursorPos(self):
        if self.fail_read:
            raise OSError("读不到光标")
        return self.pos

    def mouse_event(self, flag, *a):
        self.buttons.append(flag)


real = actions.win32api

print("=" * 84)
print("① 正常情况:动作照旧,返回值是 True")
print("=" * 84)
ok = FakeWin32()
actions.win32api = ok
C("set_cursor 成功 -> True", actions.set_cursor(500, 400) is True)
C("光标真的到了 (500,400)", ok.pos == (500, 400), ok.pos)
C("click 成功 -> True", actions.click(600, 500) is True)
C("按了鼠标(按下+松开各一次)", len(ok.buttons) == 2, ok.buttons)
C("没有残留的错误说明", actions.take_input_error() is None)

print()
print("=" * 84)
print("② ★ 系统不让动鼠标:不许抛异常、不许乱点")
print("=" * 84)
bad = FakeWin32(fail_move=True)
actions.win32api = bad
try:
    r = actions.set_cursor(500, 400)
    raised = False
except Exception as e:                      # 就是这条要挡住
    raised, r = True, e
C("★ set_cursor 不抛异常,返回 False", (not raised) and r is False, r)
C("失败时写了人话说明", bool(actions.take_input_error()))
bad = FakeWin32(fail_move=True)
actions.win32api = bad
try:
    r = actions.click(600, 500)
    raised = False
except Exception as e:
    raised, r = True, e
C("★ click 也不抛异常,返回 False", (not raised) and r is False, r)
C("★★ 挪不过去时**一次都没按鼠标**(乱点会点到别的窗口)",
  bad.buttons == [], bad.buttons)

print()
print("=" * 84)
print("③ ★ 拖拽:起点挪不过去就不按;中途挪不动要松手(别让鼠标一直按着)")
print("=" * 84)
d1 = FakeWin32(fail_move=True)
actions.win32api = d1
raised = False
try:
    r = actions.move_drag(400, 400, 800, 600)
except Exception as e:
    raised, r = True, e
C("★ 拖拽不抛异常,返回 False", (not raised) and r is False, r)
C("★ 起点都到不了 -> 不许按下", d1.buttons == [], d1.buttons)


class HalfWay(FakeWin32):
    """前几步能走,走到一半开始失败(模拟拖动途中被挡住)。"""

    def __init__(self):
        super().__init__()
        self.n = 0

    def SetCursorPos(self, pt):
        self.n += 1
        if self.n > 2:
            raise OSError(0, "SetCursorPos", "No error message is available")
        self.moves += 1
        self.pos = (int(pt[0]), int(pt[1]))


d2 = HalfWay()
actions.win32api = d2
raised = False
try:
    r = actions.move_drag(400, 400, 800, 600)
except Exception as e:
    raised, r = True, e
C("★ 半路挪不动也不抛异常", (not raised) and r is False, r)
C("★★ 已经按下去了 -> 必须**松开**(不能让鼠标一直按着)",
  d2.buttons.count(win32con_down := d2.buttons[0]) >= 1 and len(d2.buttons) >= 2
  if d2.buttons else False, f"按下/松开共 {len(d2.buttons)} 次")

print()
print("=" * 84)
print("④ 连着失败几次 -> 补一句『怎么办』(而不是每 tick 刷屏)")
print("=" * 84)
actions.LAST_INPUT_ERROR = None
actions._input_fails = 0          # ★ 前面的小节也失败过,这里必须清零再考
f = FakeWin32(fail_move=True)
actions.win32api = f
first = None
for i in range(actions.INPUT_FAIL_HINT_AT):
    actions.set_cursor(10, 10)
    msg = actions.LAST_INPUT_ERROR or ""
    if first is None:
        first = msg
C("第一条只有『是什么』,没有长篇大论", "管理员" not in (first or ""), (first or "")[:50])
C("★ 连到第 N 次才补『怎么办』", "管理员" in (actions.LAST_INPUT_ERROR or ""),
  (actions.LAST_INPUT_ERROR or "")[:80])
C("提示里点名了真正的原因(管理员权限 / SetWindowPos 拒绝访问)",
  "管理员" in actions.LAST_INPUT_ERROR and "SetWindowPos" in actions.LAST_INPUT_ERROR)
C("恢复之后计数清零(下次失败会重新提示)",
  (lambda: (setattr(actions.win32api, "fail_move", False),
            actions.set_cursor(1, 1),
            actions._input_fails == 0)[-1])())

actions.win32api = real

print()
print("=" * 84)
print("⑤ ★★★ 「不抢鼠标」那条路:窗口消息模式(默认关,行为不许变)")
print("=" * 84)
# 背景(用户 2026-09-20):"程序运行抢鼠标很烦"。物理层做不到不抢(系统只有一个光标),
# 真正不抢的一条是"不碰光标、直接往窗口发消息" —— 能不能用要先在游戏上实测
# (`dev\click_probe.py --selftest` 验链路,`--click` 验游戏认不认)。
# 这一节只考**离线能考的那部分**:默认行为没变 + 消息模式的开关真的能整条切过去。
C('默认仍是物理模式(改了代码不许悄悄改行为)', actions.INPUT_MODE == "physical",
  f"实得 {actions.INPUT_MODE!r}")

C("lParam 打包:x 在低 16 位、y 在高 16 位",
  actions._lp(0x1234, 0x5678) == 0x56781234, hex(actions._lp(0x1234, 0x5678)))
C("lParam 打包:超出 16 位的部分要截断(不能溢出到另一个坐标里)",
  actions._lp(70000, 1) == (70000 & 0xFFFF) | (1 << 16)
  and actions._lp(-1, -1) == 0xFFFFFFFF, hex(actions._lp(-1, -1)))

# 切到消息模式之后:click / move_drag 都必须走消息,**一次都不许碰真实鼠标**
_clicked, _dragged = [], []
_real_click_msg, _real_drag_msg = actions.click_message, actions.drag_message
_real_mouse_event = real.mouse_event if hasattr(real, "mouse_event") else None
try:
    actions.click_message = lambda x, y, **k: (_clicked.append((x, y)) or True)
    actions.drag_message = lambda *a, **k: (_dragged.append(a) or True)
    actions.INPUT_MODE = "message"
    r1 = actions.click(640, 360)
    r2 = actions.move_drag(100, 200, 300, 400)
    C("★ INPUT_MODE=message 之后 click() 走消息", r1 and _clicked == [(640, 360)],
      f"实得 {_clicked}")
    C("★ INPUT_MODE=message 之后 move_drag() 走消息", r2 and len(_dragged) == 1,
      f"实得 {_dragged}")
    C("消息模式下没碰真实光标(假 win32api 的 SetCursorPos 一次都没调)",
      getattr(real, "moves", 0) == 0, f"实得 {getattr(real, 'moves', 0)} 次")
finally:
    actions.click_message, actions.drag_message = _real_click_msg, _real_drag_msg
    actions.INPUT_MODE = "physical"

# 点到底下没有窗口的地方 -> (None,0,0),不许抛异常
import types  # noqa: E402
_fake_gui = types.ModuleType("win32gui")
_fake_gui.WindowFromPoint = lambda pt: 0
_fake_gui.GetAncestor = lambda h, f: 0
_fake_gui.ScreenToClient = lambda h, pt: pt
_saved = sys.modules.get("win32gui")
sys.modules["win32gui"] = _fake_gui
try:
    C("底下没有窗口时 window_under() 返回 (None,0,0),不抛异常",
      actions.window_under(10, 10) == (None, 0, 0))
finally:
    if _saved is not None:
        sys.modules["win32gui"] = _saved
    else:
        sys.modules.pop("win32gui", None)

print()
print("=" * 84)
import unittest
from contextlib import ExitStack
from unittest.mock import patch, Mock


class UserYieldTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.mouse = FakeWin32()
        self.stack.enter_context(patch.object(actions, 'win32api', self.mouse))
        self.sleep = self.stack.enter_context(patch.object(actions.time, 'sleep'))
        self.logs = []
        self.now = 0.0
        actions.configure_input('physical')
        actions.configure_stop()
        actions.configure_user_yield(True, idle_seconds=1, log_fn=self.logs.append)
        self.addCleanup(actions.configure_user_yield)
        self.addCleanup(actions.configure_stop)
        self.addCleanup(actions.configure_input, 'physical')

    def advance(self, seconds):
        self.now += seconds

    def wait(self, sleep=None):
        return actions.wait_if_user_active(sleep_fn=sleep or self.advance, clock_fn=lambda: self.now)

    def grab(self):
        actions.set_cursor(100, 100)
        self.mouse.pos = (140, 100)

    def test_configuration_and_disabled_default(self):
        self.grab()
        self.assertTrue(actions.user_took_cursor())
        actions.configure_user_yield()
        self.assertFalse(actions._yield_enabled)
        self.assertIsNone(actions._last_bot_cursor)
        with patch.object(actions, 'cursor_is_moving', side_effect=AssertionError('disabled')):
            self.assertFalse(self.wait())
            self.assertFalse(actions.user_took_cursor())
        actions.configure_user_yield(True, 2.5, 12, self.logs.append)
        self.assertEqual((actions._yield_idle_seconds, actions._yield_tol), (2.5, 12))

    def test_cursor_tolerance_actual_position_and_read_failure(self):
        self.assertFalse(actions.user_took_cursor())
        with patch.object(self.mouse, 'SetCursorPos', side_effect=lambda p: setattr(self.mouse, 'pos', (103, 98))):
            self.assertTrue(actions.set_cursor(100, 100))
        self.assertEqual(actions._last_bot_cursor, (103, 98))
        self.mouse.pos = (128, 123)
        self.assertFalse(actions.user_took_cursor())
        self.assertTrue(actions.user_took_cursor(tol=24))
        self.mouse.pos = (103, 124)
        self.assertTrue(actions.user_took_cursor())
        self.mouse.fail_read = True
        self.assertFalse(actions.user_took_cursor())
        self.assertTrue(actions.set_cursor(9, 8))
        self.assertEqual(actions._last_bot_cursor, (9, 8))

    def test_no_motion_returns_without_pause(self):
        self.assertFalse(self.wait())
        self.assertEqual(self.logs, [])
        self.assertEqual(self.now, 0)

    def test_wait_requires_continuous_idle_and_rebases_cursor(self):
        self.grab()
        def move_then_idle(seconds):
            self.advance(seconds)
            if self.now <= .5:
                self.mouse.pos = (140 + int(self.now * 40), 100)
        self.assertTrue(self.wait(move_then_idle))
        self.assertEqual(self.now, 1.5)
        self.assertEqual(actions._last_bot_cursor, self.mouse.pos)
        self.assertFalse(self.wait())
        self.assertEqual(len(self.logs), 2)
        self.assertIn('暂停接管', self.logs[0])
        self.assertEqual(self.logs[1], '[yield] 鼠标已空闲，恢复自动操作')

    def test_slow_drift_resets_idle_anchor(self):
        self.grab()
        def drift(seconds):
            self.advance(seconds)
            if self.now <= 1:
                self.mouse.pos = (140 + int(self.now * 16), 100)
        self.assertTrue(self.wait(drift))
        self.assertEqual(self.now, 2)

    def test_initial_motion_without_bot_anchor_triggers(self):
        self.sleep.side_effect = lambda _: setattr(self.mouse, 'pos', (110, 100))
        self.assertTrue(self.wait())
        self.assertEqual(self.now, 1)

    def test_wait_propagates_stop_and_does_not_resume(self):
        self.grab()
        actions.configure_stop(lambda: self.now >= .25)
        with self.assertRaises(actions.InputStopped):
            self.wait()
        self.assertEqual(self.now, .25)
        self.assertEqual(len(self.logs), 1)
        self.assertEqual(self.mouse.buttons, [])

    def test_message_mode_never_reads_cursor_or_waits(self):
        self.grab()
        actions.configure_input('message')
        actions.configure_stop(lambda: True)
        with patch.object(self.mouse, 'GetCursorPos', side_effect=AssertionError('message cursor')):
            self.assertFalse(actions.user_took_cursor())
            self.assertFalse(self.wait())

    def test_move_aborts_before_next_step(self):
        actions.set_cursor(100, 100)
        self.sleep.side_effect = lambda _: setattr(self.mouse, 'pos', (999, 999))
        self.assertFalse(actions.move_stepped(100, 100, 400, 400, steps=3))
        self.assertEqual(self.mouse.moves, 2)
        self.assertIn('检测到人工移动鼠标，已让权', actions.take_input_error())
        self.assertEqual(self.mouse.buttons, [])

    def test_click_does_not_press_after_last_step_grab(self):
        with patch.object(actions, 'wait_if_user_active') as wait:
            def steal_after_last_step(_):
                if self.mouse.moves == 2:
                    self.mouse.pos = (999, 999)
            self.sleep.side_effect = steal_after_last_step
            self.assertFalse(actions.click(110, 110, jitter=0))
            wait.assert_called_once()
        self.assertEqual(self.mouse.moves, 2)
        self.assertEqual(self.mouse.buttons, [])

    def test_failed_cursor_reads_cannot_count_as_idle(self):
        self.grab()
        def unreadable_then_idle(seconds):
            self.advance(seconds)
            self.mouse.fail_read = self.now < .75
        self.assertTrue(self.wait(unreadable_then_idle))
        self.assertEqual(self.now, 1.75)

    def test_drag_yields_during_settle_press_and_dwell(self):
        for phase in ('settle', 'press', 'dwell'):
            with self.subTest(phase=phase):
                actions.configure_user_yield(True)
                self.mouse.buttons.clear()
                def steal(_):
                    if phase == 'settle' or (phase == 'press' and self.mouse.buttons) or (
                            phase == 'dwell' and self.mouse.pos[0] >= 398):
                        self.mouse.pos = (999, 999)
                self.sleep.side_effect = steal
                with patch.object(actions, 'wait_if_user_active') as wait:
                    self.assertFalse(actions.move_drag(100, 100, 400, 400))
                    wait.assert_called_once()
                self.assertEqual(self.mouse.buttons, [] if phase == 'settle' else [
                    actions.win32con.MOUSEEVENTF_LEFTDOWN, actions.win32con.MOUSEEVENTF_LEFTUP])

    def test_stop_during_held_drag_releases(self):
        actions.configure_stop(lambda: bool(self.mouse.buttons))
        with patch.object(actions, 'wait_if_user_active'), self.assertRaises(actions.InputStopped):
            actions.move_drag(100, 100, 400, 400)
        self.assertEqual(self.mouse.buttons, [actions.win32con.MOUSEEVENTF_LEFTDOWN,
                                            actions.win32con.MOUSEEVENTF_LEFTUP])

    def test_controller_opt_in_and_tick_order(self):
        import main_loop
        with patch.object(main_loop, 'load_meta'), patch.object(main_loop, 'load_templates'), \
                patch.object(main_loop, 'load_states'), patch.object(main_loop, 'log') as log:
            for dry, message, enabled in [(False, False, True), (True, False, False), (False, True, False)]:
                ctl = main_loop.Controller('fake', dry, 0, False, message_input=message,
                                           yield_to_user=True, yield_idle=2)
                self.assertEqual(actions._yield_enabled, enabled)
                self.assertEqual(ctl.yield_to_user, enabled)
            ctl = main_loop.Controller('fake', False, 0, False, yield_to_user=True)
            ctl.max_ticks = 1
            ctl.grab_frame = Mock(side_effect=AssertionError('capture before idle'))
            with patch.object(actions, 'wait_if_user_active', side_effect=actions.InputStopped), \
                    self.assertRaises(actions.InputStopped):
                ctl.run()
            ctl.grab_frame.assert_not_called()
            self.assertTrue(any('已启用动鼠标让权' in c.args[0] for c in log.call_args_list))
            main_loop.Controller('fake', False, 0, False)
            self.assertFalse(actions._yield_enabled)


ALLOK &= unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(UserYieldTests)).wasSuccessful()
print("全部通过" if ALLOK else "存在失败项")
print("=" * 84)
sys.exit(0 if ALLOK else 1)
