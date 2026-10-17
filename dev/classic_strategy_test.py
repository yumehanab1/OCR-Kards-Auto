"""Traditional strategy routing, stopping rules and hover retries. No input."""
from pathlib import Path
from unittest.mock import Mock, patch
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import hand_cost_filter as hcf
import hand_scanner_v2 as hs
import main_loop
import turn_engine as te
import weather_cards


class ClassicStrategy(unittest.TestCase):
    def engine(self, classic=True, budget=5):
        engine = te.TurnEngine(0, {}, log=Mock(), classic_strategy=classic)
        engine.kredits_left = budget
        engine._dump_frame = Mock()
        engine._layout_text = Mock(return_value='test layout')
        engine._memory_text = Mock(return_value='')
        engine._memory_note_scan = Mock()
        engine.scanner.measure_edges = Mock(return_value=(400, 900))
        engine.scanner.scan_orange = Mock(side_effect=AssertionError('orange scan used'))
        engine.scanner.scan = Mock(return_value=[])
        engine.scanner.scan_fast = Mock(return_value=[])
        return engine

    def test_independent_profiles_override_orange_environment(self):
        with patch.object(hcf, 'ENABLED', True):
            classic, current = self.engine(), self.engine(False)
            self.assertFalse(classic._orange_enabled())
            self.assertTrue(current._orange_enabled())
            self.assertTrue(classic.scanner.classic_strategy)
            self.assertFalse(current.scanner.classic_strategy)

    def test_layout_route_never_calls_orange_templates_or_combo(self):
        engine = self.engine(budget=1)
        card = dict(x=500, name='第 506 空降步兵团', type='infantry', cost=1, panel='before')
        engine.scanner.find_playable = Mock(return_value=([card], 1))
        with patch.object(hcf, 'candidates', side_effect=AssertionError('orange candidates')), \
                patch.object(hcf, 'read_candidate_cost', side_effect=AssertionError('orange fee')), \
                patch.object(hcf, 'best_combo', side_effect=AssertionError('cost planner')):
            found = engine._lazy_find_playable()
        self.assertEqual(found['_before'], 'before')
        engine.scanner.find_playable.assert_called_once()
        self.assertEqual(engine.scanner.find_playable.call_args.args[0], [1])
        engine.scanner.scan_orange.assert_not_called()
        engine._memory_note_scan.assert_called_once()

    def test_unknown_budget_and_missing_layout_fall_back_only_once(self):
        for budget, fast in ((None, False), (5, True)):
            engine = self.engine(budget=budget)
            engine.use_fast = fast
            engine.scanner.measure_edges.return_value = (None, None)
            engine._lazy_find_playable()
            engine._lazy_find_playable()
            chosen = engine.scanner.scan_fast if fast else engine.scanner.scan
            chosen.assert_called_once()
            engine.scanner.scan_orange.assert_not_called()

    def test_zero_budget_still_has_no_blind_scan(self):
        engine = self.engine(budget=0)
        self.assertIsNone(engine._lazy_find_playable())
        self.assertEqual(engine._scan(), [])
        engine.scanner.measure_edges.assert_not_called()
        engine.scanner.scan.assert_not_called()
        engine.scanner.scan_orange.assert_not_called()

    def test_direct_orange_entry_is_also_disabled(self):
        scanner = hs.HandScannerV2.__new__(hs.HandScannerV2)
        scanner.classic_strategy = True
        scanner._baseline = Mock(side_effect=AssertionError('capture attempted'))
        self.assertIsNone(scanner.scan_orange(5, first_only=True))
        scanner._baseline.assert_not_called()
        self.assertEqual(scanner.last_orange['disabled'], 'classic_strategy')

    def test_last_one_kredit_is_scanned_in_play_phase(self):
        engine = self.engine(budget=1)
        engine.phase = 'play'
        engine._enter_screen_selection = Mock()
        engine._end_turn_visible = Mock(return_value=True)
        engine._support_line_full = Mock(return_value=False)
        engine._hand_count = Mock(return_value=5)
        engine._kredits_measured = Mock(return_value=True)
        engine._lazy_find_playable = Mock()
        with patch.object(te, 'capture_client_bgr', return_value=np.zeros((720,1280,3),np.uint8)):
            engine.think()
        engine._lazy_find_playable.assert_called_once()

    def test_big_hand_stops_after_three_successful_plays(self):
        engine = self.engine()
        engine._hand_count = Mock(return_value=5)
        for count, capped in ((0, False), (1, False), (2, False), (3, True)):
            engine.deployed_this_turn = count
            engine.deploy_refused = 10
            self.assertEqual(engine._deploy_capped(), capped)
        engine._hand_count.return_value = None
        self.assertFalse(engine._deploy_capped())

    def test_classic_skips_repeat_hover_but_keeps_weather_resolution(self):
        for classic in (True, False):
            scanner = hs.HandScannerV2.__new__(hs.HandScannerV2)
            scanner.classic_strategy = classic
            scanner.y = 630
            scanner._last_client = (500, 630)
            scanner._check_scan_deadline = Mock()
            scanner._classify_name = Mock(side_effect=lambda *a, **kw: dict(name=None,cost=None))
            scanner._baseline = Mock()
            scanner._hover_frame = Mock(return_value=np.zeros((720,1280,3),np.uint8))
            scanner.user_took_over = Mock(return_value=False)
            frame = np.zeros((720,1280,3),np.uint8)
            with patch.object(hs, 'diff_bbox', return_value=(400,200,200,300)), \
                    patch.object(weather_cards, 'identify', side_effect=lambda info,*args:info) as identify:
                scanner._classify(frame, frame=frame)
            self.assertEqual(scanner._classify_name.call_count, 1 if classic else 2)
            self.assertEqual(scanner._hover_frame.call_count, 0 if classic else 1)
            identify.assert_called_once()

    def test_controller_passes_profile_to_engine_without_mutating_global_filter(self):
        controller = main_loop.Controller('kards', False, 0, False, play=True, classic_strategy=True)
        with patch.object(main_loop, 'TurnEngine') as factory, patch.object(main_loop, 'log'):
            controller.handle_in_game()  # no hwnd, returns before any capture
        self.assertTrue(factory.call_args.kwargs['classic_strategy'])
        self.assertTrue(controller.classic_strategy)


if __name__ == '__main__':
    unittest.main(verbosity=2)
