"""Offline attack/move dispatch regressions; no game, capture or real input.

Run with the portable Python from the PC repository root. Every native input,
capture and coordinate-conversion seam is patched before exercising the code.
"""
from __future__ import annotations

import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import numpy as np
import actions
import attack

FRAME = np.zeros((720, 1280, 3), dtype=np.uint8)
BEFORE = {"rows": [{"side": "our", "cy": 520}],
          "our_support": [{"cx": 440, "cy": 520}],
          "frontline": [], "enemy_support": [{"cx": 640, "cy": 180}]}
AFTER = {"rows": BEFORE["rows"], "our_support": [],
         "frontline": [{"cx": 440, "cy": 350}], "enemy_support": []}
ACTOR = {"key": (380, 450), "src": (440, 520), "type": "fighter",
         "badge": {"x": 380, "y": 450}}
SKIPPED = {"needs_front": 0, "unknown_type": 0, "no_front_owner": 0}


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(attack, "park_cursor", return_value=True))
        self.stack.enter_context(patch.object(attack, "capture_client_bgr", return_value=FRAME))
        self.coords = self.stack.enter_context(patch.object(
            attack, "client_to_screen", side_effect=lambda h, x, y: (x + 10, y + 20)))
        self.drag = self.stack.enter_context(patch.object(attack, "move_drag", return_value=True))
        self.sleep = self.stack.enter_context(patch.object(attack.time, "sleep"))
        # Fail loudly instead of allowing any accidental native mouse delivery.
        for name in ("set_cursor", "click", "move_drag"):
            self.stack.enter_context(patch.object(actions, name, side_effect=AssertionError("real input forbidden")))

    def make_attacker(self, kind=attack.TARGET_ENEMY_HQ, hp=20):
        obj = attack.Attacker(123, log=Mock(), max_attacks=3)
        obj._park = Mock()
        obj._frame = Mock(return_value=FRAME)
        obj._frontline_owner = Mock(return_value={"owner": "enemy"})
        obj._guard_info = Mock(return_value={})
        obj._dump_badges = Mock()
        obj._dump_after = Mock()
        obj._our_attackers = Mock(side_effect=lambda *a, **k: (
            [] if ACTOR["key"] in obj.tried else [dict(ACTOR)], dict(SKIPPED), "fake badge"))
        obj._pick_target = Mock(return_value={"kind": kind, "hp": hp,
                                              "cx": 640, "cy": 180, "label": "fake enemy"})
        obj._relocate_target = Mock(return_value=(640, 180))
        self.field = self.stack.enter_context(patch.object(
            attack.board, "read_field", side_effect=[BEFORE] + [AFTER] * 20))
        self.hp = self.stack.enter_context(patch.object(attack.board, "read_hq_hp", return_value=17))
        return obj

    def make_mover(self):
        obj = attack.FrontMover(123, log=Mock(), max_moves=3)
        obj._park = Mock()
        obj._frame = Mock(return_value=FRAME)
        obj._frontline_owner = Mock(return_value={"owner": "our"})
        obj._pick_advancer = Mock(side_effect=lambda *a, **k: (
            None if ACTOR["key"] in obj.tried else dict(ACTOR, type="infantry")))
        self.field = self.stack.enter_context(patch.object(
            attack.board, "read_field", side_effect=[BEFORE] + [AFTER] * 20))
        self.stack.enter_context(patch.object(attack.board, "front_row", return_value=None))
        self.stack.enter_context(patch.object(attack.board, "front_line_cy", return_value=350))
        self.stack.enter_context(patch.object(attack.deploy_mod, "slot_candidates", return_value=[(440, 350)]))
        return obj

    def test_move_helper_propagates_false_and_does_not_wait(self):
        self.drag.return_value = False
        ok, detail = attack.move_unit_to_front(123, (440, 520), (440, 350), log=Mock())
        self.assertIs(ok, False)
        self.assertIn("reason", detail)
        self.sleep.assert_not_called()

    def test_move_helper_catches_coordinate_error(self):
        self.coords.side_effect = OSError("stale hwnd")
        ok, detail = attack.move_unit_to_front(123, (440, 520), log=Mock())
        self.assertIs(ok, False)
        self.assertIn("stale hwnd", detail["reason"])
        self.drag.assert_not_called()

    def test_move_helper_catches_drag_exception(self):
        self.drag.side_effect = OSError("blocked drag")
        ok, detail = attack.move_unit_to_front(123, (440, 520), log=Mock())
        self.assertIs(ok, False)
        self.assertIn("blocked drag", detail["reason"])
        self.sleep.assert_not_called()

    def test_move_helper_success_only_confirms_delivery(self):
        ok, detail = attack.move_unit_to_front(123, (440, 520), (440, 350), log=Mock())
        self.assertIs(ok, True)
        self.assertEqual(detail["dst"], (440, 350))
        self.drag.assert_called_once_with(450, 540, 450, 370)

    def test_failed_attack_ignores_apparent_hq_damage(self):
        obj = self.make_attacker()
        self.drag.return_value = False
        self.assertEqual(obj.run_turn(), (1, 0))
        self.assertEqual(obj.input_failed, 1)
        self.assertEqual(obj.input_failed_all, 1)
        self.assertFalse(obj.hq_blocked)
        self.assertEqual(obj.hq_blocked_all, 0)
        self.hp.assert_not_called()
        self.assertEqual(self.field.call_count, 1)
        obj._dump_after.assert_not_called()
        self.sleep.assert_not_called()
        self.assertTrue(any("输入失败" in str(c) for c in obj.log.call_args_list))
        obj.run_turn()
        self.assertEqual(self.drag.call_count, 1, "no retry before turn reset")

    def test_failed_attack_ignores_apparent_unit_death(self):
        obj = self.make_attacker(attack.TARGET_ENEMY_SUPPORT, hp=None)
        self.drag.return_value = False
        self.assertEqual(obj.run_turn(), (1, 0))
        self.assertEqual(obj._frame.call_count, 1)
        self.assertEqual(self.field.call_count, 1)

    def test_coordinate_failure_does_not_become_hq_miss(self):
        obj = self.make_attacker()
        self.coords.side_effect = OSError("stale hwnd")
        self.assertEqual(obj.run_turn(), (1, 0))
        self.assertEqual(obj.input_failed, 1)
        self.assertFalse(obj.hq_blocked)
        self.hp.assert_not_called()
        self.drag.assert_not_called()

    def test_attack_exception_is_bounded(self):
        obj = self.make_attacker()
        self.drag.side_effect = OSError("interrupted gesture")
        self.assertEqual(obj.run_turn(), (1, 0))
        self.assertEqual(obj.input_failed, 1)
        self.assertEqual(self.drag.call_count, 1)
        self.assertEqual(obj._frame.call_count, 1)

    def test_successful_attack_still_requires_and_uses_posterior(self):
        obj = self.make_attacker()
        self.assertEqual(obj.run_turn(), (1, 1))
        self.assertEqual(obj.input_failed, 0)
        self.assertGreaterEqual(self.hp.call_count, 1)

    def test_failed_move_ignores_apparent_board_movement(self):
        obj = self.make_mover()
        helper = self.stack.enter_context(patch.object(
            attack, "move_unit_to_front", return_value=(False, {"reason": "input blocked"})))
        self.assertEqual(obj.run_turn(), (0, 0))
        self.assertEqual(obj.input_failed, 1)
        self.assertEqual(obj.input_failed_all, 1)
        self.assertEqual(obj.moved_all, 0)
        self.assertEqual(obj.refused_all, 0, "input failure is not game refusal")
        self.assertEqual(self.field.call_count, 1)
        self.assertEqual(obj._frame.call_count, 1)
        self.sleep.assert_not_called()
        obj.run_turn()
        helper.assert_called_once()

    def test_move_exception_does_not_increment_success_or_refusal(self):
        obj = self.make_mover()
        self.stack.enter_context(patch.object(
            attack, "move_unit_to_front", side_effect=OSError("broken helper")))
        self.assertEqual(obj.run_turn(), (0, 0))
        self.assertEqual(obj.input_failed, 1)
        self.assertEqual(self.field.call_count, 1)

    def test_successful_move_still_requires_board_delta(self):
        obj = self.make_mover()
        self.stack.enter_context(patch.object(
            attack, "move_unit_to_front", return_value=(True, {})))
        self.assertEqual(obj.run_turn(), (1, 0))
        self.assertEqual(obj.input_failed, 0)
        self.assertEqual(obj.moved_all, 1)

    def test_completed_move_without_delta_is_game_refusal(self):
        obj = self.make_mover()
        self.field.side_effect = None
        self.field.return_value = BEFORE
        self.stack.enter_context(patch.object(
            attack, "move_unit_to_front", return_value=(True, {})))
        self.assertEqual(obj.run_turn(), (0, 1))
        self.assertEqual(obj.input_failed, 0)
        self.assertEqual(obj.refused_all, 1)

    def test_reset_clears_turn_failures_but_preserves_totals(self):
        for cls in (attack.Attacker, attack.FrontMover):
            obj = cls(123, log=Mock())
            obj.input_failed = 1
            obj.input_failed_all = 2
            obj.tried.add(ACTOR["key"])
            obj.reset_turn()
            self.assertEqual(obj.input_failed, 0)
            self.assertEqual(obj.input_failed_all, 2)
            self.assertFalse(obj.tried)

    def engine_for(self, phase, actor):
        import turn_engine
        engine = turn_engine.TurnEngine.__new__(turn_engine.TurnEngine)
        engine.hwnd = 123
        engine.log = Mock()
        engine.phase = phase
        engine._enter_screen_selection = Mock(return_value=False)
        engine._end_turn_visible = Mock(return_value=True)
        engine._action_hard_stop = Mock(return_value=False)
        engine.attacked_this_turn = 2
        engine.moved_this_turn = 3
        engine.kredits_left = 5
        engine._resync_kredits_after_actions = Mock()
        engine._field = Mock(return_value=BEFORE)
        if phase == "attack":
            engine.attacker = actor
        else:
            engine.front_mover = actor
            engine.attacker = Mock(attempts=0)
        self.stack.enter_context(patch.object(turn_engine, "capture_client_bgr", return_value=FRAME))
        return engine

    def test_engine_failed_attack_does_not_credit_success(self):
        actor = self.make_attacker()
        self.drag.return_value = False
        engine = self.engine_for("attack", actor)
        self.assertEqual(engine.think(), "attacked")
        self.assertEqual(engine.attacked_this_turn, 2)
        self.assertEqual(engine.kredits_left, 5)
        self.assertEqual(engine.phase, "move_front")
        self.assertTrue(any("输入失败 1 次" in str(c) for c in engine.log.call_args_list))

    def test_engine_failed_move_does_not_credit_success(self):
        actor = self.make_mover()
        self.stack.enter_context(patch.object(
            attack, "move_unit_to_front", return_value=(False, {"reason": "blocked"})))
        engine = self.engine_for("move_front", actor)
        self.assertEqual(engine.think(), "moved_front")
        self.assertEqual(engine.moved_this_turn, 3)
        self.assertEqual(engine.kredits_left, 5)
        self.assertEqual(engine.phase, "play")
        engine._resync_kredits_after_actions.assert_called_once()
        self.assertTrue(any("输入失败 1 次" in str(c) for c in engine.log.call_args_list))


if __name__ == "__main__":
    unittest.main(verbosity=2)
