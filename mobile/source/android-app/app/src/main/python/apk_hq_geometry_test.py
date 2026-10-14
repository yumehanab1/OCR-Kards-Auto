"""HQ geometry contracts, with no core imports or device dependencies."""
import importlib
import io
import sys
import types
import unittest
from unittest import mock
from pathlib import Path

import cv2
import numpy as np

import apk_hq_geometry as adapter


class HqGeometryTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((720, 1280, 3), np.uint8)
        self.card = {"x": 500, "y": 100, "w": 112, "h": 150, "cx": 556, "cy": 175}
        self.box = (530, 190, 55, 59)
        self.shield = np.zeros((59, 55, 3), np.uint8)
        self.original = mock.Mock(return_value=None)
        self.board = types.SimpleNamespace(
            FIELD=(200, 40, 1120, 560), hq_card=self.original,
            HQ_SCAN_BANDS={"enemy": (70, 260), "our": (425, 590)},
            HQ_CENTER_BANDS={"enemy": (140, 220), "our": (460, 530)},
            CARD_BRIGHT_V=135, CARD_W_RANGE=(75, 150), CARD_H_RANGE=(105, 230),
            _support_row_bright_cards=mock.Mock(return_value=[self.card]),
            _hq_shield_geometry=mock.Mock(return_value=True))
        self.hp = types.SimpleNamespace(SHIELD_DARK_V=120,
                                       find_shield=mock.Mock(return_value=(self.shield, self.box)))
        modules = mock.patch.dict(sys.modules, {"mobile_board": self.board, "hq_hp": self.hp})
        modules.start()
        self.addCleanup(modules.stop)

    def optional_read(self, **changes):
        return dict(self.card, shield=self.box, hp=13, hp_state="red", hp_score=.91, **changes)

    def test_unique_structure_with_unknown_hp_is_located(self):
        got = adapter.hq_card(self.frame, include_hp=True)
        self.assertEqual(got, dict(self.card, shield=self.box, hp=None, geometry_verified=True))
        self.assertEqual(self.card, {"x": 500, "y": 100, "w": 112, "h": 150, "cx": 556, "cy": 175})
        self.assertFalse(self.frame.any())

    def test_original_successful_hp_is_optional_and_metadata_preserved(self):
        read = self.optional_read(hp_corroboration={"reason": "original"})
        self.original.return_value = read
        got = adapter.hq_card(self.frame, include_hp=True)
        self.assertEqual((got["hp"], got["hp_state"], got["hp_score"]), (13, "red", .91))
        self.assertTrue(got["geometry_verified"])
        got["hp_corroboration"]["reason"] = "changed"
        self.assertEqual(read["hp_corroboration"]["reason"], "original")

    def test_geometry_only_does_not_call_ocr(self):
        self.original.side_effect = AssertionError("OCR must not be needed")
        self.assertIsNone(adapter.hq_card(self.frame, include_hp=False)["hp"])
        self.original.assert_not_called()

    def test_multiple_structures_cannot_be_resolved_by_one_readable_hp(self):
        self.board._support_row_bright_cards.return_value = [self.card, dict(self.card, x=700, cx=756)]
        self.original.return_value = self.optional_read()
        self.assertIsNone(adapter.hq_card(self.frame))
        self.original.assert_not_called()

    def test_duplicate_structure_is_ambiguous(self):
        self.board._support_row_bright_cards.return_value = [self.card, dict(self.card)]
        self.assertIsNone(adapter.hq_card(self.frame))
        self.original.assert_not_called()

    def test_no_cards_or_no_shields_is_unknown(self):
        self.board._support_row_bright_cards.return_value = []
        self.assertIsNone(adapter.hq_card(self.frame))
        self.board._support_row_bright_cards.return_value = [self.card]
        self.hp.find_shield.return_value = (None, None)
        self.assertIsNone(adapter.hq_card(self.frame))
        self.original.assert_not_called()

    def test_small_or_displaced_shield_cannot_use_hp_to_pass(self):
        self.board._hq_shield_geometry.return_value = False
        self.original.return_value = self.optional_read()
        self.assertIsNone(adapter.hq_card(self.frame))
        self.original.assert_not_called()

    def test_structural_read_error_does_not_hide_a_rival_candidate(self):
        self.board._support_row_bright_cards.return_value = [self.card, dict(self.card, x=700, cx=756)]
        self.hp.find_shield.side_effect = [(self.shield, self.box), ValueError("failed rival")]
        self.assertIsNone(adapter.hq_card(self.frame))
        self.original.assert_not_called()

    def test_invalid_frame_or_side_never_reaches_helpers(self):
        for frame in (None, object(), np.zeros((720, 1280), np.uint8),
                      np.zeros((721, 1280, 3), np.uint8), np.zeros((720, 1280, 4), np.uint8),
                      np.zeros((720, 1280, 3), np.float32)):
            with self.subTest(shape=getattr(frame, "shape", None)):
                self.assertIsNone(adapter.hq_card(frame))
        self.assertIsNone(adapter.hq_card(self.frame, "front"))
        self.board._support_row_bright_cards.assert_not_called()

    def test_explicit_side_and_field_are_preserved(self):
        field = (250, 50, 1100, 580)
        adapter.hq_card(self.frame, "our", field)
        args = self.board._support_row_bright_cards.call_args.args
        self.assertIs(args[0], self.frame)
        self.assertEqual(args[1:], ("our", field))
        self.assertEqual(self.original.call_args.args[1:], ("our", field))

    def test_malformed_field_is_unknown(self):
        for field in ((1, 2, 3), (200.0, 40, 1120, 560), (-1, 40, 1120, 560),
                      (200, 40, 1281, 560), (200, 560, 1120, 40), (False, 0, 1280, 720)):
            self.assertIsNone(adapter.hq_card(self.frame, field=field))
        self.board._support_row_bright_cards.assert_not_called()

    def test_optional_reader_exception_cannot_remove_location(self):
        self.original.side_effect = RuntimeError("unreadable numeral")
        self.assertTrue(adapter.hq_card(self.frame)["geometry_verified"])

    def test_optional_read_from_different_card_or_shield_is_ignored(self):
        for changes in ({"x": 501, "cx": 557}, {"y": 101, "cy": 176},
                        {"w": 114, "cx": 557}, {"shield": (531, 190, 55, 59)}):
            self.original.return_value = dict(self.optional_read(), **changes)
            self.assertIsNone(adapter.hq_card(self.frame)["hp"])

    def test_unknown_or_invalid_optional_hp_is_not_fabricated(self):
        for hp in (None, True, -1, 100, 13.0, float("nan"), "13"):
            self.original.return_value = dict(self.optional_read(), hp=hp)
            self.assertIsNone(adapter.hq_card(self.frame)["hp"])

    def test_optional_metadata_cannot_replace_geometry(self):
        self.original.return_value = dict(self.optional_read(), geometry_verified=False, unrelated="value")
        got = adapter.hq_card(self.frame)
        self.assertTrue(got["geometry_verified"])
        self.assertNotIn("unrelated", got)

    def test_candidate_stale_hp_fields_are_not_reused(self):
        self.card.update(hp=99, hp_score=1.0, hp_state="white", hp_corroboration={})
        got = adapter.hq_card(self.frame)
        self.assertIsNone(got["hp"])
        self.assertNotIn("hp_score", got)
        self.assertNotIn("hp_state", got)
        self.assertNotIn("hp_corroboration", got)

    def test_invalid_card_or_shield_geometry_is_unknown(self):
        self.board._support_row_bright_cards.return_value = [dict(self.card, cx=0)]
        self.assertIsNone(adapter.hq_card(self.frame))
        self.board._support_row_bright_cards.return_value = [self.card]
        for box, shield in (((530, 190, 0, 59), self.shield),
                            ((-1, 190, 55, 59), self.shield),
                            (self.box, np.zeros((58, 55, 3), np.uint8)),
                            (self.box, np.zeros((59, 55, 3), np.float32))):
            self.hp.find_shield.return_value = shield, box
            self.assertIsNone(adapter.hq_card(self.frame))

    def test_install_twice_retains_original_without_recursion(self):
        self.original.return_value = self.optional_read()
        adapter.install()
        adapter.install()
        self.assertIs(getattr(self.board, adapter._ORIGINAL_ATTRIBUTE), self.original)
        self.assertIs(self.board.hq_card, adapter.geometry_only_hq_card)
        self.assertIsNone(self.board.hq_card(self.frame)["hp"])
        self.original.assert_not_called()
        self.assertEqual(adapter.hq_card(self.frame, include_hp=True)["hp"], 13)
        self.assertEqual(self.original.call_count, 1)

    def test_install_after_adapter_reload_retains_board_original(self):
        self.original.return_value = self.optional_read()
        adapter.install()
        old_wrapper = self.board.hq_card
        importlib.reload(adapter)
        adapter.install()
        self.assertIsNot(self.board.hq_card, old_wrapper)
        self.assertIs(getattr(self.board, adapter._ORIGINAL_ATTRIBUTE), self.original)
        self.assertIsNone(self.board.hq_card(self.frame)["hp"])
        self.original.assert_not_called()
        self.assertEqual(adapter.hq_card(self.frame, include_hp=True)["hp"], 13)
        self.assertEqual(self.original.call_count, 1)

    def test_installed_runtime_entry_never_runs_optional_reader(self):
        self.original.side_effect = AssertionError("runtime must not call HP reader")
        adapter.install()
        field = (250, 50, 1100, 580)
        got = self.board.hq_card(self.frame, "our", field)
        self.assertTrue(got["geometry_verified"])
        self.assertIsNone(got["hp"])
        self.assertEqual(self.board._support_row_bright_cards.call_args.args[1:], ("our", field))
        self.original.assert_not_called()

    def test_lost_original_with_wrapper_is_rejected_not_recaptured(self):
        self.board.hq_card = adapter.geometry_only_hq_card
        with self.assertRaises(RuntimeError):
            adapter.install()

    def _real_row(self, name):
        # Actual saved pixels and coordinates, with all other rows blank. The
        # cold self_check does not import/load a core or open any device.
        path = Path(__file__).resolve().parent / "hq-fixtures" / name
        crop = cv2.imread(str(path))
        self.assertIsNotNone(crop, "reviewed HQ fixture must be packaged")
        self.assertEqual(crop.shape, (190, 920, 3))
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[70:260, 200:1120] = crop
        return frame

    def _real_shield_lookup(self, frame):
        # This cold contract's independent observed shield box is fixed. The
        # separate archive replay uses the actual frozen find_shield helper.
        self.board._support_row_bright_cards.return_value = []
        self.board._hq_shield_geometry.side_effect = lambda card, box: (
            .42 <= box[2]/card["w"] <= .62 and .30 <= box[3]/card["h"] <= .50 and
            .40 <= (box[0]+box[2]/2-card["x"])/card["w"] <= .60 and
            .65 <= (box[1]+box[3]/2-card["y"])/card["h"] <= .90)
        box = (612, 181, 54, 58)
        self.hp.find_shield.side_effect = lambda image, card: (image[181:239, 612:666], box)

    def test_dim_real_enemy_hq_excludes_only_verified_dark_shield(self):
        for name in ("cloth-00085-row.png", "cloth-independent-00113-row.png"):
            frame = self._real_row(name)
            before = frame.copy()
            self._real_shield_lookup(frame)
            got = adapter.hq_card(frame, include_hp=False)
            self.assertIsNotNone(got, name)
            self.assertEqual(got["shield"], (612, 181, 54, 58))
            self.assertTrue(got["geometry_verified"])
            self.assertIsNone(got["hp"])
            self.assertTrue(np.array_equal(frame, before))
            self.original.assert_not_called()

    def test_dim_real_hq_without_large_shield_is_unknown(self):
        frame = self._real_row("cloth-independent-00113-row.png")
        self._real_shield_lookup(frame)
        self.hp.find_shield.side_effect = None
        self.hp.find_shield.return_value = None, None
        self.assertIsNone(adapter.hq_card(frame, include_hp=False))

    def test_dim_real_hq_rectangle_or_displaced_shield_is_unknown(self):
        frame = self._real_row("cloth-independent-00113-row.png")
        self._real_shield_lookup(frame)
        frame[181:239, 612:666] = 20
        self.assertIsNone(adapter.hq_card(frame, include_hp=False))
        frame = self._real_row("cloth-independent-00113-row.png")
        self.hp.find_shield.side_effect = lambda image, card: (image[181:239, 612:666], (580,181,54,58))
        self.assertIsNone(adapter.hq_card(frame, include_hp=False))

    def test_dim_real_hq_cannot_recover_outside_support_or_explicit_field(self):
        frame = self._real_row("cloth-independent-00113-row.png")
        self._real_shield_lookup(frame)
        self.assertIsNone(adapter.hq_card(frame, "our", include_hp=False))
        self.assertIsNone(adapter.hq_card(frame, field=(720,40,1120,560), include_hp=False))

    def test_real_dim_hq_duplicate_remains_ambiguous(self):
        frame = self._real_row("cloth-independent-00113-row.png")
        self._real_shield_lookup(frame)
        frame[90:250, 286:406] = frame[90:250,586:706]
        def lookup(image, card):
            offset = -300 if card["x"] < 500 else 0
            box = (612+offset,181,54,58)
            return image[181:239,612+offset:666+offset], box
        self.hp.find_shield.side_effect = lookup
        self.assertIsNone(adapter.hq_card(frame, include_hp=False))
        self.original.assert_not_called()

    def _body_row(self, name="cloth-body-00153-row.png", shift=0):
        path = Path(__file__).resolve().parent / "hq-fixtures" / name
        crop = cv2.imread(str(path))
        self.assertIsNotNone(crop, "current-frame body fixture must be packaged")
        self.assertEqual(crop.shape, (165, 920, 3))
        frame = np.zeros((720, 1280, 3), np.uint8)
        # Translation is a synthetic test scene made from unchanged real pixels.
        if shift >= 0:
            frame[425:590, 200+shift:1120] = crop[:, :920-shift]
        else:
            frame[425:590, 200:1120+shift] = crop[:, -shift:]
        top = 430 if "00331" in name else 427
        card = dict(x=570+shift, y=top, w=130, h=560-top,
                    cx=635+shift, cy=top+(560-top)//2)
        box = (615+shift, 517, 54, 45)
        self.board._support_row_bright_cards.return_value = [card]
        self.board._hq_shield_geometry.side_effect = lambda candidate, shield: (
            .42 <= shield[2]/candidate["w"] <= .62 and
            .30 <= shield[3]/candidate["h"] <= .50 and
            .40 <= (shield[0]+shield[2]/2-candidate["x"])/candidate["w"] <= .60 and
            .65 <= (shield[1]+shield[3]/2-candidate["y"])/candidate["h"] <= .90)
        self.hp.find_shield.side_effect = lambda image, candidate: (image[517:562,615+shift:669+shift], box)
        return frame, card, box

    def test_real_our_body_uses_two_current_borders_and_clipped_shield(self):
        for name in ("cloth-body-00153-row.png", "cloth-body-independent-00331-row.png"):
            frame, card, box = self._body_row(name)
            before = frame.copy()
            self.assertFalse(self.board._hq_shield_geometry(card, box))
            got = adapter.hq_card(frame, "our", include_hp=False)
            self.assertIsNotNone(got, name)
            self.assertEqual((got["x"], got["w"]), (587, 109))
            self.assertEqual(got["shield"], box)
            self.assertTrue(self.board._hq_shield_geometry(got, box))
            self.assertIsNone(got["hp"])
            self.assertTrue(np.array_equal(frame, before))
            self.original.assert_not_called()

    def test_real_body_translates_without_cached_or_fixed_x(self):
        for shift in (-144, 144):
            frame, card, box = self._body_row(shift=shift)
            got = adapter.hq_card(frame, "our", include_hp=False)
            self.assertIsNotNone(got, shift)
            self.assertEqual((got["x"], got["w"]), (587+shift, 109))
            self.assertEqual(got["shield"], box)

    def test_real_body_requires_both_unique_continuous_borders(self):
        for change in ("missing_left", "missing_right", "interior_rival", "broken_left"):
            frame, card, box = self._body_row()
            if change == "missing_left":
                frame[440:510, 565:607] = frame[440:510, 607:608]
            elif change == "missing_right":
                frame[440:510, 681:706] = frame[440:510, 680:681]
            elif change == "interior_rival":
                frame[440:510, 630:635] = 250
            else:
                frame[445:465, 565:607] = frame[445:465, 607:608]
            self.assertIsNone(adapter.hq_card(frame, "our", include_hp=False), change)

    def test_real_body_requires_same_shield_after_refinement(self):
        frame, card, box = self._body_row()
        def read(image, candidate):
            observed = box if candidate["w"] == 130 else (616,517,54,45)
            return image[517:562,615:669], observed
        self.hp.find_shield.side_effect = read
        self.assertIsNone(adapter.hq_card(frame, "our", include_hp=False))

    def test_real_body_cannot_change_other_geometry_or_explicit_scope(self):
        for box in ((615,517,33,33), (615,480,54,45), (590,517,54,45), (615,517,54,15)):
            frame, card, _ = self._body_row()
            bx,by,bw,bh = box
            self.hp.find_shield.side_effect = lambda image, candidate: (image[by:by+bh,bx:bx+bw], box)
            self.assertIsNone(adapter.hq_card(frame, "our", include_hp=False), box)
        frame, card, box = self._body_row()
        self.assertIsNone(adapter.hq_card(frame, "enemy", include_hp=False))
        self.assertIsNone(adapter.hq_card(frame, "our", field=(600,425,1120,560), include_hp=False))

    def test_real_body_refinement_rechecks_mutated_pixels(self):
        frame, card, box = self._body_row()
        self.assertIsNotNone(adapter.hq_card(frame, "our", include_hp=False))
        frame[440:510, 565:607] = frame[440:510, 607:608]
        self.assertIsNone(adapter.hq_card(frame, "our", include_hp=False))

    def test_two_real_body_structures_remain_ambiguous(self):
        frame, card, box = self._body_row()
        frame[425:590, 272:422] = frame[425:590, 560:710]
        other = dict(card, x=card["x"]-288, cx=card["cx"]-288)
        self.board._support_row_bright_cards.return_value = [card, other]
        def read(image, candidate):
            offset = -288 if candidate["x"] < 500 else 0
            observed = (615+offset,517,54,45)
            return image[517:562,615+offset:669+offset], observed
        self.hp.find_shield.side_effect = read
        self.assertIsNone(adapter.hq_card(frame, "our", include_hp=False))
        self.original.assert_not_called()


def run_tests():
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HqGeometryTests)
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return {"passed": result.wasSuccessful(), "tests_run": result.testsRun,
            "failures": len(result.failures), "errors": len(result.errors), "output": stream.getvalue()}


if __name__ == "__main__":
    unittest.main()
