"""Current-capture and raw/provisional HQ proof boundaries; no input authority."""
from copy import deepcopy
import types
import unittest
from unittest import mock
import numpy as np
import apk_hq_row_split as split

class HqRowSplitterTests(unittest.TestCase):
    def setUp(self):
        self.raw = mock.Mock(return_value=[])
        self.original = mock.Mock(return_value=[])
        self.bright = mock.Mock(return_value=[])
        self.board = types.SimpleNamespace(FIELD=(200, 40, 1120, 595), FRONT_BAND=(235, 315),
            SUPPORT_BAND=(415, 470), CARD_BRIGHT_V=135, hq_hp=types.SimpleNamespace(),
            _support_row_bright_cards=self.original, bright_cards=self.bright, _badge_candidates=self.raw,
            board_transition_reason=lambda frame: "", choice_modal=lambda frame: (False, None))
        self.vision = types.SimpleNamespace(TYPES=("tank",))
        self.frame = np.zeros((720, 1280, 3), np.uint8)
        self.info = dict(zip(split.FIELDS, (1, 1000, 2, 1920, 1080)))
        self.card = {"x": 653, "y": 433, "w": 127, "h": 150, "cx": 716, "cy": 508}
        self.good = {"allowed": True, "candidate": self.card, "proofs": [], "reason": "fixture"}
        self.adapter = split.install(self.board, self.vision)

    def test_repeat_install_retains_original_callbacks(self):
        for _ in range(3):
            adapter = split.install(self.board, self.vision)
            self.assertIs(adapter.original_row, self.original)
            self.assertIs(adapter.raw_badges, self.raw)
            self.assertIs(adapter.original_bright, self.bright)
        self.assertIs(self.board._apk_original_support_row_bright_cards, self.original)

    def test_exact_registered_capture_deepcopy_and_fresh_registration(self):
        self.adapter.register(self.frame, self.info)
        with mock.patch.object(self.adapter, "_decide", return_value=self.good) as decide:
            first = self.adapter.row(self.frame, "our"); first[0]["x"] = 0
            self.assertEqual(self.adapter.row(self.frame, "our")[0]["x"], 653)
            self.assertEqual(decide.call_count, 1)
            self.adapter.register(self.frame, self.info)
            self.adapter.row(self.frame, "our")
            self.assertEqual(decide.call_count, 2)

    def test_foreign_same_pixels_not_reused(self):
        self.adapter.register(self.frame, self.info)
        with mock.patch.object(self.adapter, "_decide", return_value=self.good) as decide:
            self.adapter.row(self.frame, "our"); self.adapter.row(self.frame.copy(), "our")
            self.assertEqual(decide.call_count, 2)

    def test_pixel_mutation_taints_registration_even_after_restoration(self):
        self.adapter.register(self.frame, self.info)
        with mock.patch.object(self.adapter, "_decide", return_value=self.good) as decide:
            self.adapter.row(self.frame, "our"); self.frame[0, 0] = 1
            self.adapter.row(self.frame, "our"); self.frame[0, 0] = 0
            self.adapter.row(self.frame, "our")
            self.assertEqual(decide.call_count, 3); self.assertIsNone(self.adapter.initial)

    def test_all_capture_metadata_changes_taint(self):
        for key in split.FIELDS:
            with self.subTest(key=key):
                self.info = dict(zip(split.FIELDS, (1, 1000, 2, 1920, 1080)))
                self.adapter.register(self.frame, self.info)
                with mock.patch.object(self.adapter, "_decide", return_value=self.good) as decide:
                    self.adapter.row(self.frame, "our"); self.info[key] += 1
                    self.adapter.row(self.frame, "our")
                    self.assertEqual(decide.call_count, 2); self.assertIsNone(self.adapter.initial)

    def test_recognition_config_or_callback_taints(self):
        for change in (lambda: setattr(self.board, "CARD_BRIGHT_V", 136),
                       lambda: setattr(self.board, "choice_modal", lambda f: (True, None))):
            self.adapter.register(self.frame, self.info)
            with mock.patch.object(self.adapter, "_decide", return_value=self.good) as decide:
                self.adapter.row(self.frame, "our"); change(); self.adapter.row(self.frame, "our")
                self.assertEqual(decide.call_count, 2); self.assertIsNone(self.adapter.initial)

    def test_raw_digit_module_constant_and_callback_taint(self):
        self.board.us = types.SimpleNamespace(ANCHOR_HUE=(6, 28), analyze_digit=lambda frame: None)
        for change in (lambda: setattr(self.board.us, "ANCHOR_HUE", (7, 28)),
                       lambda: setattr(self.board.us, "analyze_digit", lambda f: 1)):
            self.adapter.register(self.frame, self.info)
            with mock.patch.object(self.adapter, "_decide", return_value=self.good) as decide:
                self.adapter.row(self.frame, "our"); change(); self.adapter.row(self.frame, "our")
                self.assertEqual(decide.call_count, 2); self.assertIsNone(self.adapter.initial)

    def test_existing_evidence_nondefault_side_and_field_unchanged(self):
        with mock.patch.object(self.adapter, "_decide") as decide:
            self.assertEqual(self.adapter.row(self.frame, "enemy"), [])
            self.assertEqual(self.adapter.row(self.frame, "our", (250, 425, 900, 590)), [])
            self.original.return_value = [self.card]
            self.assertEqual(self.adapter.row(self.frame, "our"), [self.card])
            decide.assert_not_called()

    def test_raw_and_provisional_busy_callbacks_are_bounded(self):
        self.board._apk_artwork_filter_busy = True
        with mock.patch.object(self.adapter, "_decide") as decide:
            self.assertEqual(self.adapter.row(self.frame, "our"), []); decide.assert_not_called()
        self.board._apk_artwork_filter_busy = False; self.board._apk_hq_row_split_busy = True
        self.assertEqual(self.adapter.row(self.frame, "our"), [])
        self.adapter._provisional = (self.frame, self.card)
        self.assertEqual(self.adapter.row(self.frame, "our"), [self.card])
        self.assertEqual(self.adapter.row(self.frame.copy(), "our"), [])

    def proof(self, **changes):
        return dict(candidate=self.card, proofs=[{}], reason="fixture", **changes)

    def test_independent_raw_out_of_row_blocks_before_any_split(self):
        self.raw.return_value = [{"cy": 534}]
        with mock.patch.object(split, "split_proofs") as helper:
            self.assertFalse(self.adapter._decide(self.frame)["allowed"]); helper.assert_not_called()
        self.assertFalse(self.board._apk_hq_row_split_busy); self.assertFalse(self.board._apk_artwork_filter_busy)

    def test_original_transition_and_choice_preserved(self):
        for transition, choice in (("overlay", False), ("", True)):
            self.board.board_transition_reason = lambda f: transition
            self.board.choice_modal = lambda f: (choice, None)
            with mock.patch.object(split, "split_proofs") as helper:
                self.assertFalse(self.adapter._decide(self.frame)["allowed"]); helper.assert_not_called()

    def test_original_frontline_reads_only_same_frame_provisional(self):
        seen = []
        def front(frame):
            seen.append((self.board._apk_hq_row_split_busy, self.board._apk_artwork_filter_busy))
            self.assertEqual(self.board._support_row_bright_cards(frame, "our"), [self.card])
            self.assertEqual(self.board._support_row_bright_cards(frame.copy(), "our"), [])
            return {"owner": "enemy"}
        self.board.frontline_state = front
        with mock.patch.object(split, "split_proofs", return_value=self.proof()):
            self.assertTrue(self.adapter._decide(self.frame)["allowed"])
        self.assertEqual(seen, [(True, True)])
        self.assertFalse(self.board._apk_hq_row_split_busy); self.assertFalse(self.board._apk_artwork_filter_busy)
        self.assertIsNone(self.adapter._provisional)

    def test_unknown_frontline_is_not_forced_empty(self):
        self.board.frontline_state = lambda frame: {"owner": "unknown", "reason": "fixture"}
        with mock.patch.object(split, "split_proofs", return_value=self.proof()):
            decision = self.adapter._decide(self.frame)
            self.assertFalse(decision["allowed"]); self.assertEqual(decision["frontline"]["owner"], "unknown")

    def test_proof_exception_restores_flags_and_falls_back_original(self):
        self.adapter.register(self.frame, self.info)
        with mock.patch.object(split, "split_proofs", side_effect=ValueError("fixture")):
            self.assertEqual(self.adapter.row(self.frame, "our"), [])
        self.assertFalse(self.board._apk_hq_row_split_busy); self.assertFalse(self.board._apk_artwork_filter_busy)
        self.assertIsNone(self.adapter._provisional); self.assertIsNone(self.adapter.initial)

    def test_frontline_exception_restores_provisional_and_original_flags(self):
        self.board.frontline_state = mock.Mock(side_effect=RuntimeError("fixture"))
        with mock.patch.object(split, "split_proofs", return_value=self.proof()):
            self.assertEqual(self.adapter.row(self.frame, "our"), [])
        self.assertFalse(self.board._apk_hq_row_split_busy); self.assertFalse(self.board._apk_artwork_filter_busy)
        self.assertIsNone(self.adapter._provisional)

    def test_uncertain_source_metadata_never_reuses(self):
        for key in split.FIELDS:
            info = dict(self.info); info[key] = None; self.adapter.register(self.frame, info)
            with mock.patch.object(self.adapter, "_decide", return_value=self.good) as decide:
                self.adapter.row(self.frame, "our"); self.adapter.row(self.frame, "our")
                self.assertEqual(decide.call_count, 2)

def self_check():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HqRowSplitterTests)
    result = unittest.TestResult(); suite.run(result)
    return {"passed": result.wasSuccessful(), "tests_run": result.testsRun,
            "failures": len(result.failures), "errors": len(result.errors), "device_inputs": 0,
            "details": [text for _, text in result.failures+result.errors]}

if __name__ == "__main__":
    unittest.main()
