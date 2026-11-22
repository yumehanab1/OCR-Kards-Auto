"""Offline input edge regressions. Native input/capture are replaced before use."""
from __future__ import annotations
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path.cwd()
if (Path(__file__).resolve().parents[1] / 'src/actions.py').exists():
    ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import actions
import gui
import main_loop
import turn_engine as te
import win
import numpy as np
import win32con

FRAME = np.zeros((720, 1280, 3), dtype=np.uint8)


class MessageEdges(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ('INPUT_MODE', 'MESSAGE_HWND', 'LAST_INPUT_ERROR', '_input_fails',
                     '_stop_checker', '_stop_latched', '_message_held'):
            if hasattr(actions, name):
                self.stack.enter_context(patch.object(actions, name, getattr(actions, name)))
        self.native = Mock()
        self.native.SetCursorPos.side_effect = AssertionError('physical cursor forbidden')
        self.native.mouse_event.side_effect = AssertionError('physical button forbidden')
        self.stack.enter_context(patch.object(actions, 'win32api', self.native))
        self.sleep = self.stack.enter_context(patch.object(actions.time, 'sleep'))
        self.api = Mock()
        self.origin = [100, 200]
        self.api.IsWindow.return_value = True
        self.api.IsIconic.return_value = False
        self.api.IsWindowVisible.return_value = True
        self.api.GetForegroundWindow.return_value = 123
        self.api.GetAncestor.side_effect = lambda h, flag: h
        self.api.WindowFromPoint.return_value = 123
        self.api.ScreenToClient.side_effect = lambda h, p: (p[0] - self.origin[0], p[1] - self.origin[1])
        self.api.GetClientRect.return_value = (0, 0, 1280, 720)
        self.api.ClientToScreen.side_effect = lambda h, p: (p[0] + self.origin[0], p[1] + self.origin[1])
        self.stack.enter_context(patch.dict(sys.modules, {'win32gui': self.api}))
        self.stack.enter_context(patch.object(win, 'win32gui', self.api))
        actions.configure_input('message', 123)

    def tearDown(self):
        self.native.SetCursorPos.assert_not_called()
        self.native.mouse_event.assert_not_called()

    def test_click_rechecks_foreground_origin_size_and_cover_after_down(self):
        changes = [lambda: setattr(self.api.GetForegroundWindow, 'return_value', 456),
                   lambda: self.origin.__setitem__(0, 150),
                   lambda: setattr(self.api.GetClientRect, 'return_value', (0, 0, 1024, 576)),
                   lambda: setattr(self.api.WindowFromPoint, 'return_value', 456)]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                self.api.GetForegroundWindow.return_value = 123
                self.api.GetClientRect.return_value = (0, 0, 1280, 720)
                self.api.WindowFromPoint.return_value = 123
                self.origin[:] = [100, 200]
                self.api.PostMessage.reset_mock()
                self.sleep.side_effect = lambda seconds: change() if seconds == .05 else None
                self.assertIs(actions.click(540, 800, jitter=0), False)
                self.assertEqual(self.api.PostMessage.call_args.args[:2], (123, win32con.WM_LBUTTONUP))

    def test_conversion_source_rejects_move_before_click_including_jitter(self):
        sx, sy = win.client_to_screen(123, 440, 600)
        self.origin[0] += 50
        self.assertIs(actions.click(sx, sy, jitter=5), False)
        self.api.PostMessage.assert_not_called()

    def test_conversion_source_rejects_move_between_drag_endpoints(self):
        sx, sy = win.client_to_screen(123, 440, 600)
        self.origin[0] += 50
        ex, ey = win.client_to_screen(123, 640, 300)
        self.assertIs(actions.move_drag(sx, sy, ex, ey), False)
        self.api.PostMessage.assert_not_called()

    def test_conversion_source_routes_controller_clicks(self):
        ctl = main_loop.Controller.__new__(main_loop.Controller)
        ctl.hwnd = 123
        sx, sy = ctl.client_to_screen(440, 600)
        self.origin[0] += 50
        self.assertIs(actions.click(sx, sy, jitter=0), False)
        self.api.PostMessage.assert_not_called()

    def test_unchanged_conversion_delivers_original_client_point(self):
        sx, sy = win.client_to_screen(123, 440, 600)
        self.assertTrue(actions.click(sx, sy, jitter=0))
        self.assertEqual(self.api.PostMessage.call_args.args[3], actions._lp(440, 600))

    def test_stop_during_drag_releases_then_blocks_future_input(self):
        stop = [False]
        actions.configure_stop(lambda: stop[0])
        def post(hwnd, msg, flags, point):
            if msg == win32con.WM_LBUTTONDOWN:
                stop[0] = True
        self.api.PostMessage.side_effect = post
        with self.assertRaises(actions.InputStopped):
            actions.move_drag(540, 800, 740, 500)
        self.assertEqual(self.api.PostMessage.call_args.args[:2], (123, win32con.WM_LBUTTONUP))
        calls = self.api.PostMessage.call_count
        stop[0] = False  # stop is latched, even if the marker disappears
        with self.assertRaises(actions.InputStopped):
            actions.click(540, 800)
        self.assertEqual(self.api.PostMessage.call_count, calls)

    def test_stop_during_click_hold_releases(self):
        stop = [False]
        actions.configure_stop(lambda: stop[0])
        self.api.PostMessage.side_effect = lambda h, msg, *a: stop.__setitem__(0, True) if msg == win32con.WM_LBUTTONDOWN else None
        with self.assertRaises(actions.InputStopped):
            actions.click(540, 800, jitter=0)
        self.assertEqual(self.api.PostMessage.call_args.args[:2], (123, win32con.WM_LBUTTONUP))


class PhysicalEdges(unittest.TestCase):
    def test_normal_physical_drag_still_releases_once_and_returns_true(self):
        with patch.object(actions, 'INPUT_MODE', 'physical'), patch.object(actions, 'win32api') as native, patch.object(actions, 'set_cursor', return_value=True), patch.object(actions, 'move_stepped', return_value=True), patch.object(actions.time, 'sleep'):
            native.GetCursorPos.return_value = (400, 400)
            self.assertIs(actions.move_drag(400, 400, 800, 600), True)
            self.assertEqual([call.args[0] for call in native.mouse_event.call_args_list],
                             [win32con.MOUSEEVENTF_LEFTDOWN, win32con.MOUSEEVENTF_LEFTUP])

    def test_each_late_cursor_failure_returns_false_and_releases(self):
        for fail_at in (2, 3, 4, 5, 6):
            with self.subTest(fail_at=fail_at), ExitStack() as stack:
                stack.enter_context(patch.object(actions, 'INPUT_MODE', 'physical'))
                native = stack.enter_context(patch.object(actions, 'win32api'))
                native.GetCursorPos.return_value = (400, 400)
                stack.enter_context(patch.object(actions.time, 'sleep'))
                stack.enter_context(patch.object(actions, 'move_stepped', return_value=True))
                setter = stack.enter_context(patch.object(actions, 'set_cursor', side_effect=[True] * (fail_at - 1) + [False] + [True] * 8))
                self.assertIs(actions.move_drag(400, 400, 800, 600, jiggle=3), False)
                self.assertEqual(setter.call_count, fail_at, 'do not continue after a failed landing/jiggle')
                self.assertEqual(native.mouse_event.call_args.args[0], win32con.MOUSEEVENTF_LEFTUP)

    def test_button_error_is_soft_and_attempts_release(self):
        with patch.object(actions, 'INPUT_MODE', 'physical'), patch.object(actions, 'win32api') as native, patch.object(actions, 'set_cursor', return_value=True), patch.object(actions.time, 'sleep'):
            native.mouse_event.side_effect = [OSError('down blocked'), None]
            self.assertIs(actions.move_drag(400, 400, 800, 600), False)
            self.assertEqual(native.mouse_event.call_args.args[0], win32con.MOUSEEVENTF_LEFTUP)


class EngineEdges(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(te, 'capture_client_bgr', return_value=FRAME))
        self.stack.enter_context(patch.object(te.time, 'sleep'))
        for name in ('click', 'set_cursor', 'move_drag'):
            self.stack.enter_context(patch.object(actions, name, side_effect=AssertionError('native input forbidden')))
        self.drag = self.stack.enter_context(patch.object(te, 'drag_deploy', return_value=False))
        self.click = self.stack.enter_context(patch.object(te, 'click', return_value=True))
        self.stack.enter_context(patch.object(te, 'park_cursor', return_value=True))
        self.stack.enter_context(patch.object(te, 'client_to_screen', side_effect=lambda h, x, y: (x, y)))
        self.stack.enter_context(patch.object(te.board, 'read_field', return_value={'rows': []}))
        self.stack.enter_context(patch.object(te, 'deploy_candidates', return_value=[(400, 520), (800, 520)]))
        self.engine = te.TurnEngine(123, {'end_turn_btn': FRAME}, log=Mock(), lazy_scan=False)
        e = self.engine
        e._enter_screen_selection = Mock(return_value=False)
        e._end_turn_visible = Mock(return_value=True)
        e._end_turn_region = Mock(return_value=(.95, (1120, 453, 130, 36)))
        e._orange_enabled = Mock(return_value=False)
        e._support_line_full = Mock(return_value=False)
        e._deploy_capped = Mock(return_value=False)
        e._field = Mock(return_value={'frame': FRAME, 'our_support': (1, {})})
        e._judge_deploy = Mock(return_value=(True, 'apparent zero-cost success', False))
        e.afford.note_deploy_ok = Mock()
        e.memory.note_played = Mock()
        e._budget = Mock(return_value=True)
        e.kredits_left = 5
        e._ident_text = Mock(return_value='synthetic identity')

    def test_failed_zero_cost_deploy_never_runs_posterior_or_records_success(self):
        e = self.engine
        e.phase = 'play'
        e.cards = [{'x': 500, 'name': 'synthetic unit', 'type': 'infantry', 'cost': 0}]
        self.assertEqual(e.think(), 'deploy_input_failed')
        e._judge_deploy.assert_not_called()
        self.assertEqual(e._field.call_count, 1, 'pre-action snapshot only')
        self.assertEqual(e.deployed_this_turn, 0)
        self.assertEqual(e.deploy_refused, 0)
        self.assertEqual(e.deploy_input_failed, 1)
        e.afford.note_deploy_ok.assert_not_called()
        e.memory.note_played.assert_not_called()
        self.assertEqual(e.phase, 'end_turn')
        e.think()
        self.drag.assert_called_once()

    def test_failed_deploy_never_retries_slot_or_calls_failure_verdict(self):
        e = self.engine
        e.phase = 'play'
        e.cards = [{'x': 500, 'name': 'synthetic unit', 'type': 'infantry', 'cost': 2}]
        e._judge_deploy.return_value = (False, 'apparently refused', True)
        self.assertEqual(e.think(), 'deploy_input_failed')
        self.drag.assert_called_once()
        e._judge_deploy.assert_not_called()
        self.assertEqual(e.deploy_refused, 0)

    def test_deploy_exception_is_bounded_and_not_game_refusal(self):
        self.drag.side_effect = OSError('blocked transport')
        e = self.engine
        e.phase = 'play'
        e.cards = [{'x': 500, 'name': 'synthetic unit', 'type': 'infantry', 'cost': 2}]
        self.assertEqual(e.think(), 'deploy_input_failed')
        self.assertEqual(e.deploy_input_failed, 1)
        self.assertEqual(e.deploy_refused, 0)

    def test_end_delivery_keeps_failure_locks_until_button_disappears(self):
        e = self.engine
        e.phase = 'end_turn'
        e.attacker.input_failed = 1
        e.front_mover.input_failed = 1
        e.failed_x.add(500)
        e.deployed_this_turn = 2
        self.assertEqual(e.think(), 'end_turn_pending')
        for _ in range(3):
            self.assertEqual(e.think(), 'end_turn_pending')
            self.assertEqual(e.attacker.input_failed, 1)
            self.assertEqual(e.front_mover.input_failed, 1)
            self.assertEqual(e.failed_x, {500})
            self.assertEqual(e.deployed_this_turn, 2)
        self.click.assert_called_once()
        e._end_turn_visible.return_value = False
        self.assertEqual(e.think(), 'ended_turn')
        self.assertEqual(e.phase, 'wait_our_turn')
        self.assertEqual(e.attacker.input_failed, 0)
        self.assertEqual(e.front_mover.input_failed, 0)
        self.assertFalse(e.failed_x)

    def test_missing_confirmation_frame_does_not_reset(self):
        e = self.engine
        e.phase = 'end_turn'
        e.attacker.input_failed = 1
        self.assertEqual(e.think(), 'end_turn_pending')
        with patch.object(te, 'capture_client_bgr', return_value=None):
            self.assertEqual(e.think(), 'no_frame')
        self.assertEqual(e.attacker.input_failed, 1)
        self.assertEqual(e.phase, 'end_turn_pending')

    def test_uncertain_click_return_is_not_success(self):
        self.click.return_value = None
        self.engine.phase = 'end_turn'
        self.assertEqual(self.engine.think(), 'end_turn_click_failed')
        self.assertEqual(self.engine.phase, 'end_turn')


class StopEdges(unittest.TestCase):
    def test_launch_mode_is_fixed_and_stop_channel_is_unique_to_run(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            script = root / 'src/main_loop.py'
            script.parent.mkdir()
            script.write_text('# no actual launch', encoding='utf-8')
            stack.enter_context(patch.object(gui, 'PROJECT_ROOT', folder))
            stack.enter_context(patch.object(gui, 'MAIN_LOOP', str(script)))
            stack.enter_context(patch.object(gui, 'LOG_DIR', str(root / 'logs')))
            stack.enter_context(patch.object(gui, 'GUI_RUN_LOG', str(root / 'logs/run.log')))
            stack.enter_context(patch.object(gui, 'engine_python', return_value='fake-python.exe'))
            stack.enter_context(patch.object(gui.time, 'sleep'))
            launch = stack.enter_context(patch.object(gui.subprocess, 'Popen'))
            child = launch.return_value
            child.poll.return_value = None
            child.pid = 42
            api = gui.Api()
            launch.side_effect = lambda *a, **k: (setattr(child.poll, 'return_value', None), child)[1]
            self.addCleanup(api._close_run_log)
            self.assertTrue(api.start({'play': True, 'message_input': True})['ok'])
            first = launch.call_args.kwargs['env']['KARDS_AUTO_STOP_FILE']
            self.assertTrue(Path(first).is_relative_to(root / 'logs/controls'))
            self.assertFalse(Path(first).exists())
            self.assertIn('--message-input', launch.call_args.args[0])
            self.assertTrue(api.save_settings({'play': True, 'message_input': False})['ok'])
            self.assertTrue(api.last_opts['message_input'], 'saving options must not hot-switch running child')
            child.poll.return_value = 0
            self.assertTrue(api.start({'play': True, 'message_input': True})['ok'])
            second = launch.call_args.kwargs['env']['KARDS_AUTO_STOP_FILE']
            child.poll.return_value = 0
            self.assertNotEqual(first, second)
            self.assertTrue(api.start({'play': True, 'message_input': False})['ok'])
            third = launch.call_args.kwargs['env']['KARDS_AUTO_STOP_FILE']
            self.assertTrue(Path(third).is_relative_to(root / 'logs/controls'))
            self.assertNotIn(third, (first, second))
            self.assertNotIn('--message-input', launch.call_args.args[0])
            api._close_run_log()

    def test_message_stop_requests_marker_without_terminating_child(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(gui, 'PROJECT_ROOT', folder):
            api = gui.Api()
            api.proc = Mock(returncode=0)
            api.proc.poll.side_effect = [None, 0]
            api.last_opts = {'message_input': True}
            api._stop_file = str(Path(folder) / 'stop.request')
            result = api.stop()
            self.assertTrue(result['ok'])
            self.assertTrue(Path(api._stop_file).exists())
            api.proc.terminate.assert_not_called()
            api.proc.kill.assert_not_called()

    def test_message_stop_timeout_keeps_process_and_log_alive(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(gui, 'PROJECT_ROOT', folder):
            api = gui.Api()
            api.proc = Mock(pid=42)
            api.proc.poll.return_value = None
            api.proc.wait.side_effect = subprocess.TimeoutExpired('fake child', 6)
            api.last_opts = {'message_input': True}
            api._stop_file = str(Path(folder) / 'stop.request')
            api._fh = Mock()
            result = api.stop()
            self.assertTrue(result['ok'])
            self.assertIn('等待', result['msg'])
            api.proc.terminate.assert_not_called()
            api.proc.kill.assert_not_called()
            api._fh.close.assert_not_called()

    def test_loop_stop_precedes_capture_and_dispatch(self):
        ctl = main_loop.Controller.__new__(main_loop.Controller)
        ctl.grab_frame = Mock(side_effect=AssertionError('must not capture after stop'))
        ctl.max_ticks = 0
        ctl.dry = False
        ctl.end_turn = False
        ctl.max_rounds = 0
        ctl.input_mode = 'message'
        with patch.object(main_loop, 'log'), patch.object(actions, 'stop_requested', return_value=True):
            self.assertEqual(ctl.run(), 0)
        ctl.grab_frame.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
