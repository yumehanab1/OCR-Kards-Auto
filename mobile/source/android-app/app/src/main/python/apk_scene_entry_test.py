"""Current-scene entry and action preflight; no device or real input."""
import types
import sys
import unittest
from unittest import mock

import numpy as np


class SceneEntryTests(unittest.TestCase):
    def setUp(self):
        import mobile_board as mb
        import mobile_attack as ma
        from turn_engine_mobile import MobileTurnEngine
        self.mb, self.ma, self.Engine = mb, ma, MobileTurnEngine
        self.frame = np.zeros((720, 1280, 3), np.uint8)

    def test_known_owner_enters_on_current_frame_without_whole_board_pair(self):
        engine = self.Engine.__new__(self.Engine)
        engine._board_stability = types.SimpleNamespace(observe=mock.Mock(
            side_effect=AssertionError("duplicate board confirmation")))
        with mock.patch.object(self.mb, "board_transition_reason", return_value=""), \
             mock.patch.object(self.mb, "frontline_state", return_value={"owner": "our"}), \
             mock.patch.object(self.mb, "hq_card", side_effect=AssertionError("irrelevant HQ")):
            self.assertEqual(engine._board_ready_real(self.frame), (True, "当前帧前线归属已确认"))
        engine._board_stability.observe.assert_not_called()

    def test_runtime_logs_the_existing_entry_decision_without_another_pass(self):
        from apk_battle_runtime import Runtime
        ready = mock.Mock(return_value=(True, "当前帧前线归属已确认"))
        info = dict(frame_id=12, captured_elapsed_ms=2000, foreground_generation=4,
                    source_width=1920, source_height=1080, state="in_game",
                    button="white", choice_modal=False, transition_reason="",
                    frontline={"owner": "our"})
        instance = types.SimpleNamespace(engine=types.SimpleNamespace(_board_ready_real=ready),
                                         last_info=info, event=mock.Mock(), now=lambda: 2100)
        self.assertEqual(Runtime.board_ready(instance, self.frame), (True, "当前帧前线归属已确认"))
        ready.assert_called_once_with(self.frame)
        event, value = instance.event.call_args.args
        self.assertEqual(event, "scene_entry")
        self.assertTrue(value["ready"])
        self.assertEqual(value["observed_elapsed_ms"], 2100)
        for key, expected in info.items():
            self.assertEqual(value[key], expected)

    def test_unknown_owner_and_actual_overlay_still_block_entry(self):
        engine = self.Engine.__new__(self.Engine)
        for transition, owner in (("", "unknown"), ("存在放大卡牌/展示层", "our")):
            with self.subTest(transition=transition, owner=owner), \
                 mock.patch.object(self.mb, "board_transition_reason", return_value=transition), \
                 mock.patch.object(self.mb, "frontline_state", return_value={"owner": owner}):
                self.assertFalse(engine._board_ready_real(self.frame)[0])

    def test_action_preflight_takes_one_new_frame_and_defers_actor_to_local_policy(self):
        old = np.ones_like(self.frame)
        with mock.patch.object(self.ma, "_grab", return_value=self.frame) as capture, \
             mock.patch.object(self.mb, "board_transition_reason", return_value=""), \
             mock.patch.object(self.mb, "choice_modal", return_value=(False, 0)), \
             mock.patch.object(self.ma, "_units_after", side_effect=AssertionError("unnecessary full-board pass")):
            authorize = mock.Mock(return_value=True)
            result, reason = self.ma._prepare(old, False, authorize)
            self.assertIs(result, self.frame)
            self.assertEqual(reason, "")
            capture.assert_called_once_with()
            authorize.assert_called_once_with(self.frame)

    def test_preflight_still_refuses_missing_frame_wrong_turn_overlay_and_choice(self):
        for missing, own, transition, choice in ((True, True, "", False),
                (False, False, "", False), (False, True, "存在放大卡牌/展示层", False),
                (False, True, "", True)):
            with self.subTest(missing=missing, own=own, transition=transition, choice=choice), \
                 mock.patch.object(self.ma, "_grab", return_value=None if missing else self.frame), \
                 mock.patch.object(self.mb, "board_transition_reason", return_value=transition), \
                 mock.patch.object(self.mb, "choice_modal", return_value=(choice, 0)):
                result, reason = self.ma._prepare(self.frame, False, lambda _: own)
                self.assertIsNone(result)
                self.assertTrue(reason)

    def test_end_button_needs_current_button_and_modal_check_without_front_or_hq(self):
        engine = self.Engine.__new__(self.Engine)
        engine._grab = lambda: self.frame
        engine._board_stability = types.SimpleNamespace(reset=mock.Mock())
        engine.log = lambda _: None
        engine._matched_end_button = lambda _: ("white", .99, [1110, 302, 110, 68])
        with mock.patch.object(self.mb, "board_transition_reason", return_value=""), \
             mock.patch.object(self.mb, "choice_modal", return_value=(False, 0)), \
             mock.patch.object(self.mb, "frontline_state", side_effect=AssertionError("irrelevant front")), \
             mock.patch.object(self.mb, "hq_card", side_effect=AssertionError("irrelevant HQ")), \
             mock.patch("mobile_hand.click_client") as click:
            self.assertTrue(engine._click_end_turn_real())
            click.assert_called_once_with(1165, 336)
        with mock.patch.object(self.mb, "board_transition_reason", return_value=""), \
             mock.patch.object(self.mb, "choice_modal", return_value=(True, 0)), \
             mock.patch("mobile_hand.click_client") as click:
            self.assertFalse(engine._click_end_turn_real())
            click.assert_not_called()


class TargetRemovalFragmentTests(unittest.TestCase):
    def setUp(self):
        import mobile_board as mb
        import mobile_attack as ma
        self.mb, self.ma = mb, ma
        self.target = dict(x=600, y=100, w=100, h=152, cx=650, cy=176, stat_boxes=[])
        self.before = np.zeros((720, 1280, 3), np.uint8)
        self.before[100:252, 600:700] = np.random.default_rng(47).integers(
            50, 230, size=(152, 100, 3), dtype=np.uint8)

    def outcome(self, after):
        with mock.patch.object(self.mb, "frontline_state", return_value={"owner": "our"}), \
             mock.patch.object(self.mb, "enemy_support_cards", return_value=[]):
            return self.ma._target_outcome(self.before, after, self.target, [self.target], "our")

    def test_type_occlusion_and_list_loss_are_not_target_removal(self):
        after = self.before.copy()
        after[165:252, 600:700] = (0, 0, 180)
        result = self.outcome(after)
        self.assertGreater(result["target_changed"], .20)
        self.assertEqual(result["targets_after"], 0)
        self.assertTrue(result["target_art_fragment_preserved"])
        self.assertFalse(result["target_removed"])
        self.assertFalse(result["target_stats_changed"])

    def test_actual_artwork_loss_still_allows_target_removal(self):
        result = self.outcome(np.zeros_like(self.before))
        self.assertFalse(result["target_art_fragment_preserved"])
        self.assertTrue(result["target_removed"])

    def test_uniform_fragment_leaves_list_loss_unconfirmed(self):
        self.before[132:160, 612:688] = 0
        result = self.outcome(np.zeros_like(self.before))
        self.assertIsNone(result["target_art_fragment_score"])
        self.assertFalse(result["target_art_fragment_preserved"])
        self.assertFalse(result["target_removed"])

    def test_occluded_type_with_uniform_upper_fragment_is_still_not_removal(self):
        self.before[132:160, 612:688] = 0
        after = self.before.copy()
        after[165:252, 600:700] = (0, 0, 180)
        result = self.outcome(after)
        self.assertGreater(result["target_changed"], .20)
        self.assertFalse(result["target_removed"])

    def test_positive_frontline_clear_does_not_depend_on_artwork_texture(self):
        self.before[132:160, 612:688] = 0
        with mock.patch.object(self.mb, "frontline_state", return_value={"owner": "empty"}), \
             mock.patch.object(self.mb, "enemy_front_cards", return_value=[]):
            result = self.ma._target_outcome(self.before, np.zeros_like(self.before), self.target,
                                            [self.target], "enemy")
        self.assertTrue(result["target_removed"])


class SingleTypeSupportTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((720, 1280, 3), np.uint8)
        self.box = (698, 552, 28, 28)
        self.raw = dict(x=692, y=432, w=100, h=152, cx=742, cy=508,
                        stat_boxes=[self.box], n_stats=1)
        self.typed = dict(self.raw, x=662, cx=712, type="tank")
        self.hq = dict(x=512, y=436, w=112, h=150, cx=568, cy=511)
        self.board = types.SimpleNamespace(
            board_transition_reason=lambda _: "", frontline_state=lambda _: {"owner": "our"},
            _support_row_bright_cards=lambda *args: [self.hq],
            hq_hp=types.SimpleNamespace(find_shield=lambda *args: (np.ones((20, 20, 3), np.uint8), (530, 530, 20, 20))),
            _hq_shield_geometry=lambda *args: True,
            cards_from_stats=lambda *args, **kwargs: [self.raw],
            cards_from_types=lambda *args, **kwargs: [self.typed],
            _type_stat_plate=lambda *args: True,
            unit_combat_type=lambda frame, unit: "tank" if unit["card"]["cx"] == 712 else "unknown")

    def observe(self):
        import apk_simple_deploy as deploy
        with mock.patch.dict(sys.modules, {"mobile_board": self.board}):
            return deploy.support_observation(self.frame)

    def test_single_type_repairs_raw_footprint_and_counts_known_unit(self):
        result = self.observe()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["reason"], "complete_support_row")
        units = [c for c in result["cards"] if c["row_kind"] == "unit"]
        self.assertEqual((units[0]["cx"], units[0]["n_stats"]), (712, 1))
        self.assertEqual(self.raw["cx"], 742)

    def test_missing_or_ambiguous_type_never_becomes_empty_support(self):
        for candidates in ([], [self.typed, dict(self.typed, cx=708)]):
            with self.subTest(candidates=len(candidates)):
                self.board.cards_from_types = lambda *args, **kwargs: candidates
                self.assertIsNone(self.observe()["count"])
        self.board._type_stat_plate = lambda *args: False
        self.assertIsNone(self.observe()["count"])

    def test_unclassified_raw_occupied_candidate_cannot_be_filtered_out(self):
        unknown_box = (850, 552, 28, 28)
        unknown = dict(self.raw, stat_boxes=[unknown_box], x=844, cx=894)
        self.board.cards_from_stats = lambda *args, **kwargs: [self.raw, unknown]
        self.board._type_stat_plate = lambda frame, box: tuple(box) == self.box
        self.assertIsNone(self.observe()["count"])
