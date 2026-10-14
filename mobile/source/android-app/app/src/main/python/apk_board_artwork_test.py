"""Negative evidence and current-capture boundaries; no input authority."""
from copy import deepcopy
import types
import unittest
from unittest import mock

import numpy as np
import apk_board_artwork as artwork


class ArtworkFilterTests(unittest.TestCase):
    def setUp(self):
        self.board = types.SimpleNamespace(BADGE_WIN=28, FRONT_BAND=(235, 315),
                                           SUPPORT_BAND=(415, 470), FIELD=(200, 40, 1120, 595))
        self.vision = types.SimpleNamespace(TYPES=("tank", "infantry"))
        self.card = {"x": 300, "y": 433, "w": 100, "h": 152, "type": "tank",
                     "stat_boxes": [[301, 551, 28, 28], [371, 551, 28, 28]]}
        self.badge = self.badge_at(348, 520)
        self.frame = np.zeros((720, 1280, 3), np.uint8)
        self.info = dict(zip(artwork.FIELDS, (1, 1000, 2, 1920, 1080)))

    @staticmethod
    def badge_at(x, y):
        return {"x": x, "y": y, "w": 28, "h": 28, "cx": x+14, "cy": y+14}

    def proof(self, badge=None, card=None):
        return artwork.artwork_evidence(badge or self.badge, card or self.card, self.board, self.vision)

    def test_complete_lower_artwork(self):
        self.assertTrue(self.proof()["allowed"])

    def test_every_artwork_boundary_and_stats_preserved(self):
        for x, y in ((307, 520), (365, 520), (348, 508), (348, 524), (300, 433), (301, 551), (1100, 520)):
            with self.subTest(x=x, y=y):
                self.assertFalse(self.proof(self.badge_at(x, y))["allowed"])

    def test_stat_type_box_evidence_required(self):
        for changes in ({"type": "unknown"}, {"stat_boxes": []},
                        {"stat_boxes": [[301, 551, 22, 28], [371, 551, 28, 28]]}):
            self.assertFalse(self.proof(card=dict(self.card, **changes))["allowed"])

    def adapter(self):
        return artwork.ArtworkFilter(self.board, self.vision,
                                     lambda frame, *args, **kwargs: deepcopy([self.badge]))

    def test_registered_decision_deepcopy_and_new_capture(self):
        adapter = self.adapter()
        good = {"excluded": [artwork.candidate_key(self.badge)], "proofs": [], "reason": "proof"}
        adapter.register(self.frame, self.info)
        with mock.patch.object(adapter, "_decide", return_value=good) as decide:
            self.assertEqual(adapter.candidates(self.frame), [])
            good["excluded"].clear()
            self.assertEqual(adapter.candidates(self.frame), [])
            self.assertEqual(decide.call_count, 1)
            adapter.register(self.frame, self.info)
            self.assertEqual(len(adapter.candidates(self.frame)), 1)
            self.assertEqual(decide.call_count, 2)

    def test_mutation_taints_registration_and_restoration_does_not_reuse(self):
        adapter = self.adapter()
        adapter.register(self.frame, self.info)
        with mock.patch.object(adapter, "_decide", return_value={"excluded": []}) as decide:
            adapter.candidates(self.frame)
            self.frame[0, 0] = 1
            adapter.candidates(self.frame)
            self.frame[0, 0] = 0
            adapter.candidates(self.frame)
            self.assertEqual(decide.call_count, 3)
            self.assertIsNone(adapter.initial)

    def test_all_metadata_changes_invalidate(self):
        for key in artwork.FIELDS:
            adapter = self.adapter()
            info = dict(self.info)
            adapter.register(self.frame, info)
            with mock.patch.object(adapter, "_decide", return_value={"excluded": []}) as decide:
                adapter.candidates(self.frame)
                info[key] += 1
                adapter.candidates(self.frame)
                self.assertEqual(decide.call_count, 2)

    def test_config_and_callback_changes_invalidate(self):
        for change in (lambda: setattr(self.board, "BADGE_WIN", 29),
                       lambda: setattr(self.vision, "TYPES", ("tank",)),
                       lambda: setattr(self.board, "choice_modal", lambda frame: (False, ""))):
            adapter = self.adapter()
            adapter.register(self.frame, dict(self.info))
            with mock.patch.object(adapter, "_decide", return_value={"excluded": []}) as decide:
                adapter.candidates(self.frame)
                change()
                adapter.candidates(self.frame)
                self.assertEqual(decide.call_count, 2)

    def test_own_callback_changes_invalidate(self):
        adapter = self.adapter()
        adapter.register(self.frame, self.info)
        with mock.patch.object(adapter, "_decide", return_value={"excluded": []}) as decide:
            adapter.candidates(self.frame)
            with mock.patch.object(artwork, "structural_row", return_value={"complete": False}):
                adapter.candidates(self.frame)
            self.assertEqual(decide.call_count, 2)

    def test_old_source_reproof_does_not_taint_current_capture(self):
        adapter = self.adapter()
        adapter.register(self.frame, self.info)
        with mock.patch.object(adapter, "_decide", return_value={"excluded": []}) as decide:
            adapter.candidates(self.frame)
            adapter.candidates(self.frame.copy())
            adapter.candidates(self.frame)
            self.assertEqual(decide.call_count, 2)

    def test_busy_and_provisional_paths_never_start_decision(self):
        adapter = self.adapter()
        self.board._apk_artwork_filter_busy = True
        with mock.patch.object(adapter, "_decide", side_effect=AssertionError("recursive proof")):
            self.assertEqual(len(adapter.candidates(self.frame)), 1)
            adapter._provisional = (self.frame, {artwork.candidate_key(self.badge)})
            self.assertEqual(adapter.candidates(self.frame), [])
            self.assertEqual(len(adapter.candidates(self.frame.copy())), 1)

    def test_proof_exception_restores_busy_and_provisional(self):
        adapter = self.adapter()
        self.board.board_transition_reason = mock.Mock(side_effect=RuntimeError("original failure"))
        with self.assertRaisesRegex(RuntimeError, "original failure"):
            adapter._decide(self.frame)
        self.assertFalse(self.board._apk_artwork_filter_busy)
        self.assertIsNone(adapter._provisional)

    def test_unexplained_second_candidate_revokes_all_exclusions(self):
        self.board.board_transition_reason = lambda frame: artwork.OUT_OF_ROW_PREFIX+"348,534)"
        self.board.choice_modal = lambda frame: (False, "")
        adapter = self.adapter()
        adapter.original = lambda frame: [self.badge, self.badge_at(1050, 520)]
        row = {"complete": True, "cards": [dict(self.card, row_kind="unit")]}
        with mock.patch.object(artwork, "structural_row", return_value=row):
            result = adapter._decide(self.frame)
        self.assertEqual(result["excluded"], [])

    def test_unknown_frontline_revokes_and_busy_is_restored(self):
        self.board.board_transition_reason = lambda frame: artwork.OUT_OF_ROW_PREFIX+"348,534)"
        self.board.choice_modal = lambda frame: (False, "")
        self.board.frontline_state = lambda frame: {"owner": "unknown"}
        adapter = self.adapter()
        row = {"complete": True, "cards": [dict(self.card, row_kind="unit")]}
        with mock.patch.object(artwork, "structural_row", return_value=row):
            self.assertEqual(adapter._decide(self.frame)["excluded"], [])
        self.assertFalse(self.board._apk_artwork_filter_busy)


if __name__ == "__main__":
    unittest.main()
