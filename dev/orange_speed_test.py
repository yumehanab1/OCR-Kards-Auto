"""Orange identity bounds and nested deadlines. Fake frames; no OCR/input."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import hand_cost_filter as hcf
import hand_scanner_v2 as hs
import main_loop
import weather_cards


class OrangeSpeed(unittest.TestCase):
    def scanner(self):
        scanner = hs.HandScannerV2.__new__(hs.HandScannerV2)
        scanner.classic_strategy = False
        scanner._scan_deadline = None
        scanner._orange_identity_active = False
        scanner.safe = (1270, 360)
        scanner.y = 700
        scanner._last_client = (528, 700)
        scanner.user_took_over = Mock(return_value=False)
        scanner._move = Mock()
        scanner.orange_cache = []
        scanner.last_orange = {}
        return scanner

    def test_main_panel_is_bounded_and_clipped_to_frame(self):
        frame = np.zeros((720, 1280, 3), np.uint8)
        self.assertEqual(hs.HandScannerV2._orange_panel_box(frame, {'x': 420, 'y': 300}),
                         (408, 290, 240, 330))
        self.assertEqual(hs.HandScannerV2._orange_panel_box(frame, {'x': 5, 'y': 5}),
                         (0, 0, 240, 330))
        self.assertEqual(hs.HandScannerV2._orange_panel_box(frame, {'x': 1260, 'y': 700}),
                         (1248, 690, 32, 30))

    def test_primary_fee_prefers_header_over_taller_art_fragment(self):
        fee = dict(x=450, y=333, w=16, h=24)
        artwork = dict(x=450, y=480, w=17, h=25)
        for candidates in ([fee, artwork], [artwork, fee]):
            self.assertIs(hs.HandScannerV2._primary_orange_fee(candidates), fee)

    def test_primary_fee_excludes_upper_and_lower_support_regions(self):
        fee = dict(x=450, y=333, w=16, h=24)
        upper = dict(x=450, y=249, w=17, h=35)
        lower = dict(x=450, y=411, w=17, h=40)
        self.assertIs(hs.HandScannerV2._primary_orange_fee([upper, fee, lower]), fee)
        self.assertIsNone(hs.HandScannerV2._primary_orange_fee([upper, lower]))
        for boundary in (250, 410):
            candidate = dict(fee, y=boundary)
            self.assertIs(hs.HandScannerV2._primary_orange_fee([candidate]), candidate)

    def test_primary_fee_refuses_ambiguous_or_missing_header(self):
        fee = dict(x=450, y=333, w=16, h=24)
        other = dict(x=480, y=340, w=17, h=25)
        self.assertIsNone(hs.HandScannerV2._primary_orange_fee([fee, other]))
        self.assertIsNone(hs.HandScannerV2._primary_orange_fee([]))

    def test_first_card_shares_earlier_deadline_and_restores_caller(self):
        for previous, expected in ((None, 14), (12, 12), (30, 14)):
            scanner = self.scanner()
            scanner._scan_deadline = previous
            observed = []
            scanner._scan_orange = lambda *args: observed.append(scanner._scan_deadline) or []
            with patch.object(hs.time, 'monotonic', return_value=10):
                self.assertEqual(scanner.scan_orange(3, first_only=True), [])
            self.assertEqual(observed, [expected])
            self.assertEqual(scanner._scan_deadline, previous)

    def test_inventory_and_classic_do_not_create_new_deadline(self):
        for classic, first_only in ((False, False), (True, True)):
            scanner = self.scanner()
            scanner.classic_strategy = classic
            scanner._scan_deadline = 19
            scanner._scan_orange = Mock(side_effect=lambda *args: scanner._scan_deadline)
            self.assertEqual(scanner.scan_orange(3, first_only=first_only), 19)
            self.assertEqual(scanner._scan_deadline, 19)

    def test_expiry_rejects_partial_identity_and_cleans_up_without_new_work(self):
        for takeover in (False, True):
            scanner = self.scanner()
            scanner._scan_deadline = 9
            scanner.user_took_over.return_value = takeover
            scanner._scan_orange = Mock(side_effect=hs.ScanDeadline())
            self.assertEqual(scanner.scan_orange(3, first_only=True), [])
            self.assertTrue(scanner.last_orange['deadline'])
            self.assertEqual(scanner._scan_deadline, 9)
            if takeover:
                scanner._move.assert_not_called()
            else:
                scanner._move.assert_called_once_with(1270, 360, check_deadline=False)

    def test_unexpected_error_also_restores_outer_deadline(self):
        scanner = self.scanner()
        scanner._scan_deadline = 25
        scanner._scan_orange = Mock(side_effect=ValueError('invalid frame'))
        with self.assertRaisesRegex(ValueError, 'invalid frame'):
            scanner.scan_orange(3, first_only=True)
        self.assertEqual(scanner._scan_deadline, 25)

    def test_orange_unknown_has_one_core_pass_and_no_repeat_hover(self):
        scanner = self.scanner()
        scanner._orange_identity_active = True
        scanner._classify_core = Mock(return_value=dict(name=None, cost=None, type=None))
        scanner._name_window = Mock(side_effect=AssertionError('wide/narrow fallback'))
        scanner._baseline = Mock(side_effect=AssertionError('repeat hover baseline'))
        scanner._hover_frame = Mock(side_effect=AssertionError('repeat hover'))
        frame = np.zeros((330, 240, 3), np.uint8)
        result = scanner._classify(frame, y0=300, box=(400, 300, 240, 330), frame=frame)
        self.assertIsNone(result['name'])
        self.assertIsNone(result['cost'])
        scanner._classify_core.assert_called_once()
        scanner._baseline.assert_not_called()
        scanner._hover_frame.assert_not_called()

    def test_expiry_blocks_wide_name_fallback(self):
        scanner = self.scanner()
        scanner._scan_deadline = 1
        now = [0]
        def first_pass(*args, **kwargs):
            now[0] = 2
            return dict(name=None, cost=None)
        scanner._name_window = Mock(return_value=np.zeros((100, 100, 3), np.uint8))
        scanner._classify_core = Mock(side_effect=first_pass)
        with patch.object(hs.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(hs, 'NAME_OCR_WINDOW', True):
            with self.assertRaises(hs.ScanDeadline):
                scanner._classify_name(np.zeros((330, 240, 3), np.uint8))
        scanner._classify_core.assert_called_once()

    def test_expiry_blocks_weather_effect_ocr(self):
        scanner = self.scanner()
        scanner._orange_identity_active = True
        scanner._scan_deadline = 1
        now = [0]
        def classify(*args, **kwargs):
            now[0] = 2
            return dict(name='旋风', type='order', cost=6)
        scanner._classify_name = Mock(side_effect=classify)
        with patch.object(hs.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(weather_cards, 'identify') as identify:
            with self.assertRaises(hs.ScanDeadline):
                scanner._classify(np.zeros((330, 240, 3), np.uint8))
        identify.assert_not_called()

    def test_expiry_blocks_below_icon_second_ocr(self):
        scanner = self.scanner()
        scanner._scan_deadline = 1
        scanner.icon_names = ['order_icon']
        scanner.templates = {'order_icon': np.zeros((20, 20, 3), np.uint8)}
        now = [0]
        def first_ocr(*args):
            now[0] = 2
            return []
        with patch.object(hs.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(hs, 'match_one', return_value=(.99, (30, 50, 20, 20))), \
                patch.object(hs, '_ocr', side_effect=first_ocr) as ocr:
            with self.assertRaises(hs.ScanDeadline):
                scanner._classify_core(np.zeros((330, 240, 3), np.uint8), y0=200)
        ocr.assert_called_once()

    def replay_scan(self, scanner, enabled=True, fees=None, fan_cost=1, hover_cost=1):
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[100:650, 200:1000] = 200
        scanner._baseline = Mock(return_value=np.zeros_like(frame))
        scanner._hover_frame = Mock(return_value=frame)
        anchor = dict(x=500, y=630, w=12, h=18, probe_x=528)
        fee = dict(x=420, y=300, w=20, h=32, probe_x=452)
        with patch.object(hcf, 'candidates', side_effect=[[anchor], [fee] if fees is None else fees]), \
                patch.object(hcf, 'read_candidate_cost', side_effect=[fan_cost, hover_cost]), \
                patch.object(hs, 'ORANGE_IDENTITY_PANEL', enabled), \
                patch.object(hs.time, 'sleep'):
            return scanner.scan_orange(3, first_only=True)

    def test_scan_uses_verified_badge_for_identity_and_retains_diff_for_deploy(self):
        for enabled, expected in ((True, (408, 290, 240, 330)),
                                  (False, (200, 100, 800, 550))):
            scanner = self.scanner()
            active = []
            def classify(region, **kwargs):
                active.append(scanner._orange_identity_active)
                return dict(name='第 506 空降步兵团', type='infantry', cost=1)
            scanner._classify = Mock(side_effect=classify)
            cards = self.replay_scan(scanner, enabled)
            self.assertEqual(len(cards), 1)
            self.assertEqual(scanner._classify.call_args.kwargs['box'], expected)
            self.assertEqual(scanner._classify.call_args.args[0].shape[:2], (expected[3], expected[2]))
            self.assertEqual(active, [enabled])
            self.assertFalse(scanner._orange_identity_active)
            self.assertEqual(cards[0]['panel'].shape[:2], (550, 800))

    def test_unknown_name_never_authorized_by_verified_fee(self):
        scanner = self.scanner()
        scanner._classify = Mock(return_value=dict(name=None, type='infantry', cost=1))
        self.assertEqual(self.replay_scan(scanner), [])
        self.assertEqual(scanner.orange_cache, [])

    def test_ambiguous_or_wrong_fee_cannot_authorize_classification(self):
        fee = dict(x=420, y=333, w=16, h=24)
        other = dict(x=450, y=340, w=17, h=25)
        artwork = dict(x=450, y=480, w=17, h=25)
        for fees, hover_cost in (([fee, other], 1), ([artwork], 1), ([fee], 2)):
            scanner = self.scanner()
            scanner._classify = Mock(side_effect=AssertionError('unverified hover classified'))
            self.assertEqual(self.replay_scan(scanner, fees=fees, hover_cost=hover_cost), [])
            scanner._classify.assert_not_called()
            self.assertEqual(scanner.last_orange['rejected'][0]['reason'], 'hover cost/color mismatch')

    def test_identity_exception_restores_context_before_deadline_cleanup(self):
        scanner = self.scanner()
        scanner._classify = Mock(side_effect=hs.ScanDeadline())
        self.assertEqual(self.replay_scan(scanner), [])
        self.assertFalse(scanner._orange_identity_active)
        self.assertIsNone(scanner._scan_deadline)
        self.assertTrue(scanner.last_orange['deadline'])

    def controller(self):
        controller = main_loop.Controller.__new__(main_loop.Controller)
        controller.play = True
        controller.dry = False
        controller.classic_strategy = False
        controller.current_state = 'in_game'
        controller.turn_engine = SimpleNamespace(phase='play')
        return controller

    def test_only_active_game_phases_get_short_dispatch_delay(self):
        controller = self.controller()
        for phase in ('attack', 'move_front', 'play', 'end_turn'):
            controller.turn_engine.phase = phase
            self.assertEqual(controller._tick_delay(), .15)
        for phase in ('wait_our_turn', 'selection_pending', 'selection_blocked'):
            controller.turn_engine.phase = phase
            self.assertEqual(controller._tick_delay(), .8)

    def test_classic_dry_and_non_play_keep_original_dispatch_delay(self):
        for attribute, value in (('classic_strategy', True), ('dry', True), ('play', False)):
            controller = self.controller()
            setattr(controller, attribute, value)
            self.assertEqual(controller._tick_delay(), .8)
        controller = self.controller()
        controller.turn_engine = None
        self.assertEqual(controller._tick_delay(), .8)

    def test_menu_or_unknown_frame_with_stale_active_engine_keeps_original_delay(self):
        controller = self.controller()
        for state in (None, 'main_menu', 'deck_select', 'queueing', 'mulligan', 'victory', 'defeat'):
            controller.current_state = state
            self.assertEqual(controller._tick_delay(), .8, state)

    def weather_recheck(self):
        scanner = self.scanner()
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[100:650, 200:1000] = 200
        scanner._baseline = Mock(return_value=np.zeros_like(frame))
        scanner._hover_frame = Mock(return_value=frame)
        scanner._orange_hover_fees = Mock(return_value=[dict(x=420, y=333, w=16, h=24)])
        info = dict(name='丛林热【temp_jungle_fever_1】', type='order', cost=4,
                    weather_id='temp_jungle_fever_1')
        card = dict(info, x=528, orange=True, info=dict(info))
        scanner._classify = Mock(return_value=dict(info))
        return scanner, card, info

    def test_orange_recheck_rereads_effect_with_main_crop_and_ignores_identity_cache(self):
        scanner, card, info = self.weather_recheck()
        scanner.orange_cache = [(np.zeros((100, 80, 3)), dict(info))]
        with patch.object(hcf, 'read_candidate_cost', return_value=4) as read_cost:
            self.assertTrue(scanner.recheck_card(card)[0])
            self.assertTrue(scanner.recheck_card(card)[0])
        self.assertEqual(scanner._classify.call_count, 2)
        self.assertEqual(scanner._hover_frame.call_count, 2)
        self.assertEqual(scanner._classify.call_args.kwargs['box'], (408, 323, 240, 330))
        self.assertTrue(read_cost.call_args.kwargs['enlarged'])
        self.assertFalse(scanner._orange_identity_active)
        self.assertIsNone(scanner._scan_deadline)

    def test_orange_recheck_rejects_changed_unresolved_fee_before_identity(self):
        for cost in (None, 3, 5):
            scanner, card, _ = self.weather_recheck()
            with patch.object(hcf, 'read_candidate_cost', return_value=cost):
                self.assertFalse(scanner.recheck_card(card)[0])
            scanner._classify.assert_not_called()

    def test_orange_recheck_requires_current_name_cost_and_weather_effect(self):
        for changed in (dict(name=None), dict(name='旋风【cyclone】'), dict(cost=3),
                        dict(weather_id='temp_jungle_fever_2'), dict(weather_id=None)):
            scanner, card, info = self.weather_recheck()
            scanner._classify.return_value = dict(info, **changed)
            with patch.object(hcf, 'read_candidate_cost', return_value=4):
                self.assertFalse(scanner.recheck_card(card)[0], changed)
            scanner._classify.assert_called_once()

    def test_orange_recheck_shares_earlier_deadline_and_restores_on_all_paths(self):
        for previous, expected in ((None, 14), (12, 12), (30, 14)):
            scanner, card, info = self.weather_recheck()
            scanner._scan_deadline = previous
            observed = []
            def classify(*args, **kwargs):
                observed.append(scanner._scan_deadline)
                return dict(info)
            scanner._classify.side_effect = classify
            with patch.object(hs.time, 'monotonic', return_value=10), \
                    patch.object(hcf, 'read_candidate_cost', return_value=4):
                self.assertTrue(scanner.recheck_card(card)[0])
            self.assertEqual(observed, [expected])
            self.assertEqual(scanner._scan_deadline, previous)
        scanner, card, _ = self.weather_recheck()
        scanner._scan_deadline = 12
        scanner._classify.side_effect = hs.ScanDeadline()
        with patch.object(hcf, 'read_candidate_cost', return_value=4):
            self.assertFalse(scanner.recheck_card(card)[0])
        self.assertEqual(scanner._scan_deadline, 12)
        self.assertFalse(scanner._orange_identity_active)

    def test_orange_recheck_expired_capture_starts_no_extra_hover_or_ocr(self):
        scanner, card, _ = self.weather_recheck()
        scanner._baseline.side_effect = hs.ScanDeadline()
        self.assertFalse(scanner.recheck_card(card)[0])
        scanner._hover_frame.assert_not_called()
        scanner._classify.assert_not_called()
        self.assertIsNone(scanner._scan_deadline)

    def test_classic_and_nonorange_recheck_keep_legacy_route(self):
        for classic, orange in ((True, True), (False, False)):
            scanner, card, _ = self.weather_recheck()
            scanner.classic_strategy = classic
            card['orange'] = orange
            scanner._recheck_orange_card = Mock(side_effect=AssertionError('orange recheck route'))
            self.assertTrue(scanner.recheck_card(card)[0])
            scanner._recheck_orange_card.assert_not_called()
            self.assertEqual(scanner._classify.call_args.kwargs['box'], (200, 100, 800, 550))


if __name__ == '__main__':
    unittest.main(verbosity=2)
