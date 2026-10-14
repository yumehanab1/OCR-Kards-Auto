"""No-image, no-device regressions for end-turn evidence accounting."""
import unittest

from apk_end_turn_ledger import EndTurnLedger


class EndTurnLedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledger = EndTurnLedger()
        self.source = {"frame_id": 1, "captured_elapsed_ms": 1000, "foreground_generation": 5,
                       "source_width": 1920, "source_height": 1080, "hud_layout": "compact"}
        self.assertEqual(self.ledger.register(0, 1, self.source, 2000, 3), [])

    def frame(self, fid, captured, **overrides):
        result = dict(self.source, frame_id=fid, captured_elapsed_ms=captured, state=None,
                      button=None, button_present=False,
                      opponent_turn_label={"present": True, "score": .99, "box": [1130, 447, 124, 33]},
                      transition_reason="", choice_modal=False,
                      frontline={"owner": "empty"}, our_hq={"cx": 640}, enemy_hq={"cx": 640})
        result.update(overrides)
        return result

    def observe(self, fid, captured, motion=0, turn=3, **overrides):
        return self.ledger.observe(self.frame(fid, captured, **overrides), captured, turn, motion)

    def test_two_independent_stable_opponent_frames_confirm(self):
        self.assertEqual(self.observe(2, 2500), [])
        outcome = self.observe(3, 3600)[0]
        self.assertEqual(outcome["status"], "confirmed")
        self.assertEqual(outcome["reason"], "observed_opponent_turn")
        self.assertEqual(outcome["evidence_frame_ids"], [2, 3])
        self.assertIsNone(self.ledger.pending)

    def test_actual_label_output_connects_to_ledger_xywh_contract(self):
        import apk_enemy_turn
        from apk_enemy_turn_test import OpponentTurnLabelTests
        pixels = OpponentTurnLabelTests().sample()
        label = apk_enemy_turn.inspect_opponent_turn(pixels)
        self.assertTrue(label["present"])
        self.assertEqual(label["box"], [1130, 447, 124, 34])
        self.assertEqual(self.observe(2, 2500, opponent_turn_label=label), [])
        outcome = self.observe(3, 3600, motion=.08, hud_layout="unknown", opponent_turn_label=label)[0]
        self.assertEqual(outcome["status"], "confirmed")

    def test_geometry_without_any_hp_confirms_positive_turn_label(self):
        cards = {"our_hq": {"cx": 600, "hp": None, "geometry_verified": True},
                 "enemy_hq": {"cx": 600, "hp": None, "geometry_verified": True}}
        self.assertEqual(self.observe(2, 2500, **cards), [])
        outcome = self.observe(3, 3600, **cards)[0]
        self.assertEqual(outcome["status"], "confirmed")

    def test_one_disappearance_and_color_change_do_not_confirm(self):
        self.observe(2, 2500)
        self.assertEqual(self.observe(3, 3600, button="white", state="in_game"), [])
        self.assertEqual(self.observe(4, 4700, button="orange", state="in_game"), [])
        self.assertIsNotNone(self.ledger.pending)

    def test_engine_counter_without_observed_absence_does_not_confirm(self):
        self.assertEqual(self.observe(2, 2500, turn=4, button="white", state="in_game"), [])
        self.assertEqual(self.observe(3, 3600, turn=4, button="white", state="in_game"), [])

    def test_moving_absence_pair_then_engine_counter_cannot_confirm(self):
        self.observe(2, 2500, motion=.03, opponent_turn_label=None)
        self.assertEqual(self.observe(3, 3100, motion=.03, opponent_turn_label=None), [])
        self.assertEqual(self.observe(4, 3700, turn=4, button="white", state="in_game"), [])
        self.assertEqual(self.observe(5, 4800, turn=4, button="white", state="in_game"), [])
        self.assertIsNotNone(self.ledger.pending)

    def test_short_span_is_not_enough(self):
        self.observe(2, 2500)
        self.assertEqual(self.observe(3, 2900), [])
        self.assertEqual(self.observe(4, 3300), [])
        self.assertEqual(self.observe(5, 3700)[0]["status"], "confirmed")

    def test_duplicate_id_breaks_pair(self):
        self.observe(2, 2500)
        self.assertEqual(self.observe(2, 3600), [])
        self.assertEqual(self.observe(3, 4200), [])
        self.assertEqual(self.observe(4, 5300)[0]["status"], "confirmed")

    def test_duplicate_timestamp_breaks_pair(self):
        self.observe(2, 2500)
        self.assertEqual(self.observe(3, 2500), [])
        self.assertEqual(self.observe(4, 3600), [])

    def test_pre_input_frame_does_not_count(self):
        self.assertEqual(self.observe(2, 1900), [])
        self.assertEqual(self.observe(3, 2500), [])

    def test_stale_frame_breaks_pair(self):
        self.observe(2, 2500)
        self.assertEqual(self.ledger.observe(self.frame(3, 3600), 7000, 3, 0), [])
        self.assertEqual(self.observe(4, 7600), [])

    def test_opponent_board_motion_does_not_invalidate_positive_turn_label(self):
        self.observe(2, 2500)
        outcome = self.observe(3, 3600, motion=.08)[0]
        self.assertEqual(outcome["status"], "confirmed")
        self.assertEqual(outcome["evidence_frame_ids"], [2, 3])

    def test_board_hq_hud_and_generic_transition_do_not_gate_turn_label(self):
        for override in ({"our_hq": None}, {"enemy_hq": None}, {"frontline": None},
                         {"frontline": {"owner": "unknown"}}, {"hud_layout": "standard"},
                         {"hud_layout": None}, {"transition_reason": "存在放大卡牌/展示层"},
                         {"transition_reason": "费用徽章不在已确认战场行(555,505)"},
                         {"our_hq": None, "enemy_hq": None, "frontline": {"owner": "unknown"},
                          "hud_layout": None, "transition_reason": "animation"}):
            with self.subTest(override=override):
                self.setUp()
                self.assertEqual(self.observe(2, 2500, **override), [])
                outcome = self.observe(3, 3600, **override)[0]
                self.assertEqual(outcome["status"], "confirmed")
                self.assertEqual(outcome["evidence_frame_ids"], [2, 3])

    def test_actual_modal_or_nonbattle_state_breaks_pair(self):
        for override in ({"choice_modal": True}, {"state": "victory"}, {"state": "home"}):
            with self.subTest(override=override):
                self.setUp()
                self.observe(2, 2500)
                self.assertEqual(self.observe(3, 3600, **override), [])
                self.assertEqual(self.observe(4, 4700), [])

    def test_incomplete_board_cannot_replace_label_or_explicit_button_absence(self):
        for override in ({"opponent_turn_label": None}, {"button_present": True},
                         {"button_present": None}, {"button": "white"}):
            with self.subTest(override=override):
                self.setUp()
                diagnostics = {"our_hq": None, "enemy_hq": None, "frontline": None,
                               "hud_layout": None, "transition_reason": "animation"}
                diagnostics.update(override)
                self.assertEqual(self.observe(2, 2500, **diagnostics), [])
                self.assertEqual(self.observe(3, 3600, **diagnostics), [])
                self.assertIsNotNone(self.ledger.pending)

    def test_unknown_post_hud_with_positive_label_and_board_can_confirm(self):
        self.observe(2, 2500)
        outcome = self.observe(3, 3600, hud_layout="unknown")[0]
        self.assertEqual(outcome["status"], "confirmed")
        self.assertEqual(outcome["evidence_frame_ids"], [2, 3])

    def test_button_absence_without_positive_label_cannot_confirm(self):
        for label in (None, {}, {"present": False}, {"present": 1}):
            with self.subTest(label=label):
                self.setUp()
                self.observe(2, 2500, opponent_turn_label=label)
                self.assertEqual(self.observe(3, 3600, opponent_turn_label=label), [])
                self.assertEqual(self.observe(4, 4700, turn=4, button="white"), [])
                self.assertEqual(self.observe(5, 5800, turn=4, button="white"), [])

    def test_own_button_shape_with_unknown_color_is_not_absence(self):
        for presence in (True, None, 0, "false"):
            with self.subTest(presence=presence):
                self.setUp()
                self.observe(2, 2500)
                self.assertEqual(self.observe(3, 3600, button_present=presence), [])
                self.assertEqual(self.observe(4, 4700), [])

    def test_near_duplicate_label_movement_breaks_pair_before_gap_filter(self):
        self.observe(2, 2500)
        moved = {"present": True, "score": .99, "box": [1135, 447, 124, 33]}
        self.assertEqual(self.observe(3, 2800, opponent_turn_label=moved), [])
        self.assertEqual(self.observe(4, 3600), [])
        outcome = self.observe(5, 4700)[0]
        self.assertEqual(outcome["evidence_frame_ids"], [4, 5])

    def test_near_duplicate_missing_label_breaks_pair(self):
        self.observe(2, 2500)
        self.assertEqual(self.observe(3, 2800, opponent_turn_label=None), [])
        self.assertEqual(self.observe(4, 3600), [])

    def test_missing_or_invalid_label_geometry_breaks_pair(self):
        for box in (None, [1130, 447, 124], [1130, 447, 0, 33],
                    [float("nan"), 447, 124, 33], [1250, 447, 124, 33]):
            with self.subTest(box=box):
                self.setUp()
                self.observe(2, 2500)
                label = {"present": True, "score": .99, "box": box}
                self.assertEqual(self.observe(3, 2800, opponent_turn_label=label), [])
                self.assertEqual(self.observe(4, 3600), [])

    def test_position_tolerance_is_relative_to_first_evidence_not_last(self):
        self.observe(2, 2500)
        self.assertEqual(self.observe(3, 2900, opponent_turn_label={
            "present": True, "box": [1132, 447, 124, 33]}), [])
        self.assertEqual(self.observe(4, 3600, opponent_turn_label={
            "present": True, "box": [1134, 447, 124, 33]}), [])

    def test_small_label_jitter_can_confirm(self):
        self.observe(2, 2500)
        outcome = self.observe(3, 3600, opponent_turn_label={
            "present": True, "box": [1132, 446, 124, 33]})[0]
        self.assertEqual(outcome["status"], "confirmed")

    def test_unknown_hud_without_positive_label_breaks_pair(self):
        self.observe(2, 2500)
        self.assertEqual(self.observe(3, 3600, hud_layout="unknown", opponent_turn_label=None), [])
        self.assertEqual(self.observe(4, 4700), [])

    def test_foreground_generation_change_closes_unconfirmed(self):
        outcome = self.observe(2, 2500, foreground_generation=6)[0]
        self.assertEqual(outcome["status"], "unconfirmed")
        self.assertEqual(outcome["reason"], "turn_transition_source_changed")

    def test_source_hud_is_diagnostic_and_does_not_block_positive_label(self):
        for layout in ("unknown", None, ""):
            with self.subTest(layout=layout):
                ledger = EndTurnLedger()
                self.assertEqual(ledger.register(0, 1, dict(self.source, hud_layout=layout), 2000, 3), [])
                self.assertEqual(ledger.observe(self.frame(2, 2500), 2500, 3), [])
                outcome = ledger.observe(self.frame(3, 3600), 3600, 3)[0]
                self.assertEqual(outcome["status"], "confirmed")
                self.assertEqual(outcome["source_hud_layout"], layout)
                self.assertEqual(outcome["evidence_frame_ids"], [2, 3])

    def test_source_dimensions_change_closes_unconfirmed(self):
        for dimensions in ({"source_width": 1080}, {"source_height": 1920}):
            with self.subTest(dimensions=dimensions):
                self.setUp()
                outcome = self.observe(2, 2500, **dimensions)[0]
                self.assertEqual(outcome["status"], "unconfirmed")
                self.assertEqual(outcome["reason"], "turn_transition_source_changed")

    def test_exact_one_second_pair_can_confirm(self):
        self.assertEqual(self.observe(2, 2500), [])
        outcome = self.observe(3, 3500)[0]
        self.assertEqual(outcome["evidence_frame_ids"], [2, 3])

    def test_near_duplicate_frame_does_not_count_as_second_sample(self):
        self.assertEqual(self.observe(2, 2500), [])
        self.assertEqual(self.observe(3, 2800), [])
        outcome = self.observe(4, 3500)[0]
        self.assertEqual(outcome["evidence_frame_ids"], [2, 4])

    def test_near_duplicate_modal_and_present_button_break_pair(self):
        for override in ({"choice_modal": True}, {"button_present": True}):
            with self.subTest(override=override):
                self.setUp()
                self.observe(2, 2500)
                self.assertEqual(self.observe(3, 2800, **override), [])
                self.assertEqual(self.observe(4, 3600), [])
                outcome = self.observe(5, 4700)[0]
                self.assertEqual(outcome["evidence_frame_ids"], [4, 5])

    def test_long_observation_gap_restarts_candidate(self):
        self.observe(2, 2500)
        self.assertEqual(self.observe(3, 7601), [])
        outcome = self.observe(4, 8701)[0]
        self.assertEqual(outcome["evidence_frame_ids"], [3, 4])

    def test_enemy_label_without_registered_end_tap_has_no_outcome(self):
        ledger = EndTurnLedger()
        self.assertEqual(ledger.observe(self.frame(2, 2500), 2500, 3), [])
        self.assertEqual(ledger.observe(self.frame(3, 3600), 3600, 3), [])
        self.assertEqual(ledger.entries, [])

    def test_timeout_is_unconfirmed_not_enemy_turn(self):
        outcome = self.observe(2, 32000)[0]
        self.assertEqual(outcome["status"], "unconfirmed")
        self.assertEqual(outcome["reason"], "turn_transition_timeout")

    def test_cancel_finalizes_once_and_cannot_later_confirm(self):
        self.observe(2, 2500)
        outcome = self.ledger.finalize(3000, "cancelled")[0]
        self.assertEqual(outcome["status"], "unconfirmed")
        self.assertEqual(self.ledger.finalize(3100, "cancelled"), [])
        self.assertEqual(self.observe(3, 3600), [])

    def test_second_tap_cannot_take_credit_for_first(self):
        outcome = self.ledger.register(1, 2, self.frame(2, 2500), 3000, 3)[0]
        self.assertEqual(outcome["input_index"], 1)
        self.assertEqual(outcome["status"], "unconfirmed")
        self.assertEqual(self.observe(3, 3600), [])
        confirmed = self.observe(4, 4700)[0]
        self.assertEqual(confirmed["input_index"], 2)
        self.assertEqual(confirmed["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
