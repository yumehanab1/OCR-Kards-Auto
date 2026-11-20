"""Message input/GUI persistence regression. Synthetic Win32 only; no game/input."""
from __future__ import annotations
import json
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / 'src/actions.py').exists():
    ROOT = Path.cwd()  # scratch staging before installation
sys.path.insert(0, str(ROOT / 'src'))
import actions
import gui
import hand_scanner_v2 as hs
import main_loop
import numpy as np
import win32con


class MessageInput(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ('INPUT_MODE', 'MESSAGE_HWND', 'LAST_INPUT_ERROR', '_input_fails',
                     '_stop_checker', '_stop_latched', '_message_held'):
            self.stack.enter_context(patch.object(actions, name, getattr(actions, name)))
        self.native = Mock()
        self.native.SetCursorPos.side_effect = AssertionError('physical cursor forbidden')
        self.native.mouse_event.side_effect = AssertionError('physical button forbidden')
        self.native.GetCursorPos.side_effect = AssertionError('system cursor read forbidden')
        self.stack.enter_context(patch.object(actions, 'win32api', self.native))
        self.sleep = self.stack.enter_context(patch.object(actions.time, 'sleep'))
        self.api = Mock()
        self.api.IsWindow.return_value = True
        self.api.IsIconic.return_value = False
        self.api.IsWindowVisible.return_value = True
        self.api.GetForegroundWindow.return_value = 123
        self.api.GetAncestor.side_effect = lambda h, flag: h
        self.api.WindowFromPoint.return_value = 123
        self.api.ScreenToClient.side_effect = lambda h, p: (p[0] - 100, p[1] - 200)
        self.api.GetClientRect.return_value = (0, 0, 1280, 720)
        self.api.ClientToScreen.return_value = (100, 200)
        self.stack.enter_context(patch.dict(sys.modules, {'win32gui': self.api}))
        actions.configure_input('message', 123)

    def tearDown(self):
        self.native.SetCursorPos.assert_not_called()
        self.native.mouse_event.assert_not_called()

    def test_hover_and_checked_hover_do_not_read_or_move_system_cursor(self):
        self.assertTrue(actions.set_cursor(540, 800))
        self.assertEqual(actions.set_cursor_checked(550, 800), (550, 800))
        self.assertFalse(actions.cursor_moved_from(550, 800))
        self.native.GetCursorPos.assert_not_called()
        self.assertEqual(self.api.PostMessage.call_count, 2)
        self.assertEqual(self.api.PostMessage.call_args.args[:3], (123, win32con.WM_MOUSEMOVE, 0))

    def test_click_and_drag_route_without_physical_fallback(self):
        self.assertTrue(actions.click(540, 800, jitter=0))
        pressed = Mock()
        self.assertTrue(actions.move_drag(540, 800, 740, 500,
                                         settle=.3, press_delay=.2, dwell=.4, on_pressed=pressed))
        pressed.assert_called_once()
        delays = [c.args[0] for c in self.sleep.call_args_list]
        for delay in (.3, .2, .4, actions.RELEASE_SETTLE):
            self.assertIn(delay, delays)
        for call in self.api.PostMessage.call_args_list:
            self.assertEqual(call.args[0], 123)
        self.assertEqual(self.api.PostMessage.call_args.args[1], win32con.WM_LBUTTONUP)

    def test_scanner_hover_and_user_mouse_motion_are_independent(self):
        scanner = hs.HandScannerV2.__new__(hs.HandScannerV2)
        scanner.hwnd = 123
        scanner._check_scan_deadline = Mock()
        scanner.cursor_clamped = 0
        with patch.object(hs, 'client_to_screen', side_effect=lambda h, x, y: (x + 100, y + 200)):
            scanner._move(450, 650)
        self.assertEqual(scanner._last_cursor, (550, 850))
        self.assertFalse(scanner.user_took_over())
        self.native.GetCursorPos.assert_not_called()

    def test_unbound_runtime_never_targets_another_window(self):
        actions.bind_message_window(None)
        self.assertFalse(actions.click(540, 800))
        self.assertFalse(actions.set_cursor(540, 800))
        self.assertFalse(actions.move_drag(540, 800, 740, 500))
        self.api.PostMessage.assert_not_called()
        self.api.WindowFromPoint.assert_not_called()

    def test_invalid_or_occluded_target_refuses_all_transports(self):
        cases = [('IsWindow', False), ('IsIconic', True), ('IsWindowVisible', False),
                 ('GetForegroundWindow', 456), ('WindowFromPoint', 456),
                 ('GetClientRect', (0, 0, 1024, 576))]
        for name, value in cases:
            with self.subTest(name=name):
                with patch.object(self.api, name, return_value=value):
                    self.api.PostMessage.reset_mock()
                    self.assertFalse(actions.click(540, 800, jitter=0))
                    self.assertFalse(actions.set_cursor(540, 800))
                    self.assertFalse(actions.move_drag(540, 800, 740, 500))
                    self.api.PostMessage.assert_not_called()

    def test_bad_destination_is_rejected_before_button_down(self):
        self.api.ScreenToClient.side_effect = OSError('conversion failed')
        self.assertFalse(actions.move_drag(540, 800, 740, 500))
        self.api.PostMessage.assert_not_called()
        self.api.ScreenToClient.side_effect = lambda h, p: (p[0] - 100, p[1] - 200)
        self.assertFalse(actions.move_drag(540, 800, 3000, 500))
        self.api.PostMessage.assert_not_called()

    def test_drag_midway_failure_releases_same_window(self):
        def post(hwnd, msg, flags, pt):
            if msg == win32con.WM_MOUSEMOVE and flags == win32con.MK_LBUTTON:
                raise OSError('blocked midway')
        self.api.PostMessage.side_effect = post
        self.assertFalse(actions.move_drag(540, 800, 740, 500))
        self.assertEqual(self.api.PostMessage.call_args.args[:2], (123, win32con.WM_LBUTTONUP))
        self.assertIn('blocked midway', actions.take_input_error())

    def test_click_failed_down_attempts_release(self):
        def post(hwnd, msg, flags, pt):
            if msg == win32con.WM_LBUTTONDOWN:
                raise OSError('blocked down')
        self.api.PostMessage.side_effect = post
        self.assertFalse(actions.click(540, 800, jitter=0))
        self.assertEqual(self.api.PostMessage.call_args.args[:2], (123, win32con.WM_LBUTTONUP))

    def test_callback_failure_does_not_leave_button_held(self):
        cb = Mock(side_effect=OSError('diagnostic IO'))
        self.assertTrue(actions.move_drag(540, 800, 740, 500, on_pressed=cb))
        self.assertEqual(self.api.PostMessage.call_args.args[1], win32con.WM_LBUTTONUP)

    def test_park_does_not_report_failed_hover_as_success(self):
        with patch('win.client_to_screen', return_value=(1370, 560)):
            self.assertTrue(actions.park_cursor(123))
            self.api.GetForegroundWindow.return_value = 456
            self.assertFalse(actions.park_cursor(123))

    def test_controller_binds_and_clears_after_capture_misses(self):
        with patch.object(main_loop, 'load_meta', return_value={}), \
             patch.object(main_loop, 'load_templates', return_value={}), \
             patch.object(main_loop, 'load_states', return_value={}), \
             patch.object(main_loop, 'find_by_process', return_value=[{'hwnd': 123}]), \
             patch.object(main_loop, 'capture_client_bgr', return_value=np.zeros((2, 2, 3))) as capture:
            ctl = main_loop.Controller('kards', False, 1, False, message_input=True)
            self.assertEqual(actions.INPUT_MODE, 'message')
            self.assertIsNone(actions.MESSAGE_HWND)
            ctl.grab_frame()
            self.assertEqual(actions.MESSAGE_HWND, 123)
            capture.return_value = None
            for _ in range(3):
                ctl.grab_frame()
            self.assertIsNone(actions.MESSAGE_HWND)
            self.assertIsNone(ctl.hwnd)
            main_loop.Controller('kards', False, 1, False)
            self.assertEqual(actions.INPUT_MODE, 'physical')

    def test_window_moving_during_hover_refuses_press(self):
        self.sleep.side_effect = lambda _: setattr(self.api.ClientToScreen, 'return_value', (200, 200))
        self.assertFalse(actions.click(540, 800, jitter=0))
        self.assertFalse(any(c.args[1] == win32con.WM_LBUTTONDOWN
                             for c in self.api.PostMessage.call_args_list))

    def test_window_moving_during_drag_releases_without_fallback(self):
        def post(hwnd, msg, flags, point):
            if msg == win32con.WM_LBUTTONDOWN:
                self.api.ClientToScreen.return_value = (200, 200)
        self.api.PostMessage.side_effect = post
        self.assertFalse(actions.move_drag(540, 800, 740, 500))
        self.assertEqual(self.api.PostMessage.call_args.args[:2], (123, win32con.WM_LBUTTONUP))

    def test_message_failure_hint_and_recovery_do_not_claim_physical_problem(self):
        actions.bind_message_window(None)
        for _ in range(actions.INPUT_FAIL_HINT_AT):
            self.assertFalse(actions.set_cursor(540, 800))
        note = actions.take_input_error()
        self.assertIn('窗口消息', note)
        self.assertNotIn('管理员', note)
        actions.bind_message_window(123)
        self.assertTrue(actions.set_cursor(540, 800))
        self.assertEqual(actions._input_fails, 0)

    def test_unanswered_click_stops_after_one_delivery(self):
        ctl = main_loop.Controller.__new__(main_loop.Controller)
        ctl.input_mode, ctl.hwnd, ctl.dry, ctl.current_state = 'message', 123, False, 'in_game'
        frame = np.indices((720, 1280))[0].astype(np.uint8)
        ctl.templates, ctl.states = {'end_turn_btn': frame[:10, :10], 'play_btn': frame[:10, :10]}, {}
        ctl.grab_frame = Mock(return_value=frame)
        ctl.client_to_screen = Mock(return_value=(540, 800))
        for name in ('play_btn', 'end_turn_btn'):
            ctl.last_click = 0
            with self.subTest(name=name), patch.object(main_loop, 'foreground_window', return_value=123), \
                 patch.object(main_loop, 'window_is_capturable', return_value=True), \
                 patch.object(main_loop, 'capture_client_bgr', return_value=frame), \
                 patch.object(main_loop, 'match_one', return_value=(.99, (0, 0, 10, 10))), \
                 patch.object(main_loop, 'classify', return_value=('main_menu', {'play_btn': .99})), \
                 patch.object(main_loop.time, 'monotonic', side_effect=[10, 10.2, 11, 15]), \
                 patch.object(main_loop, 'log'):
                self.api.PostMessage.reset_mock()
                with self.assertRaises(main_loop.MessageInputUnconfirmed):
                    ctl.click_template(name)
                self.assertEqual(sum(v.args[1] == win32con.WM_LBUTTONDOWN for v in self.api.PostMessage.call_args_list), 1)
                self.assertEqual(ctl.last_click, 0)

    def test_confirmed_change_requires_two_usable_frames(self):
        ctl = main_loop.Controller.__new__(main_loop.Controller)
        ctl.input_mode, ctl.hwnd, ctl.dry = 'message', 123, False
        ctl.templates, ctl.states = {}, {}
        good = np.indices((720, 1280))[0].astype(np.uint8)
        with patch.object(main_loop, 'foreground_window', return_value=123), \
             patch.object(main_loop, 'window_is_capturable', return_value=True), \
             patch.object(main_loop, 'capture_client_bgr', side_effect=[good, None, good, good]) as cap, \
             patch.object(main_loop, 'classify', return_value=('main_menu', {'play_btn': .99, 'deck_ok_btn': .98})):
            ctl._confirm_message_click('play_btn')
            self.assertEqual(cap.call_count, 4)
        self.api.PostMessage.assert_not_called()

    def test_gui_default_argv_and_restart_persistence(self):
        self.assertFalse(gui.normalize_options({})['message_input'])
        self.assertNotIn('--message-input', gui.build_argv({'play': True}))
        self.assertIn('--message-input', gui.build_argv({'play': True, 'message_input': True}))
        switch = next(s for s in gui.SWITCHES if s['key'] == 'message_input')
        self.assertIn('实验', switch['label'])
        with tempfile.TemporaryDirectory() as folder, patch.object(gui, 'PROJECT_ROOT', folder):
            api = gui.Api()
            self.assertTrue(api.save_settings({'message_input': True, 'max_rounds': 2})['ok'])
            self.assertTrue(gui.Api().saved_options['message_input'])
            self.assertIsNone(gui.Api().proc)
            self.assertTrue(api.save_settings({'message_input': False, 'max_rounds': 2})['ok'])
            self.assertFalse(gui.Api().saved_options['message_input'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
