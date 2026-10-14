"""Self-contained APK adapter contracts; saved real pixels have a separate audit."""
import sys
import types
import unittest
from unittest import mock

import cv2
import numpy as np

import apk_hq_adapter as adapter


class HqAdapterTests(unittest.TestCase):
    def setUp(self):
        self.core = types.SimpleNamespace(
            read_shield=mock.Mock(return_value=None), extract_glyphs=mock.Mock(return_value=[]),
            bank=mock.Mock(return_value={}), _match_digit=mock.Mock(side_effect=[(2, .95, .60, 7), (0, .96, .63, 8)]),
            _color_state=mock.Mock(return_value="white"), SAT_DIGIT=100, V_FLOOR=110, V_REL_DELTA=22,
            COLOR_RED_HUE=(165, 15), COLOR_GREEN_HUE=(35, 90), GLYPH_W_MIN=4, GLYPH_W_MAX=40,
            GLYPH_H_MIN=11, GLYPH_H_MAX=44, GLYPH_AREA_MIN=25, GLYPH_FILL_MIN=.25,
            CONFIDENT_SCORE=.85, AMBIGUOUS_MARGIN=.10, MATCH_MIN=.45, COLOR_WHITE_MAX_S=70)
        self.modules = mock.patch.dict(sys.modules, {"hq_hp": self.core})
        self.modules.start()
        self.original = mock.patch.object(adapter, "_ORIGINAL_READ_SHIELD", None)
        self.original.start()
        self.addCleanup(self.original.stop)
        self.addCleanup(self.modules.stop)

    @staticmethod
    def shield():
        hsv = np.full((59, 55, 3), (30, 110, 24), np.uint8)
        frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        cv2.rectangle(frame, (1, 1), (53, 57), (155, 155, 155), 2)
        cv2.putText(frame, "20", (8, 40), cv2.FONT_HERSHEY_SIMPLEX, .75, (165, 165, 165), 2)
        return frame

    def test_install_is_idempotent_and_preserves_original_read(self):
        original = self.core.read_shield
        expected = {"hp": 3, "score": .844, "why": "original_with_external_corroboration"}
        original.return_value = expected
        adapter.install()
        adapter.install()
        self.assertIs(adapter._ORIGINAL_READ_SHIELD, original)
        self.assertIs(self.core.read_shield(self.shield()), expected)
        self.core.extract_glyphs.assert_not_called()

    def test_saturated_background_recovers_two_separate_digits(self):
        got = adapter.inspect_shield(self.shield(), (500, 180, 55, 59))
        self.assertEqual(got["read"]["hp"], 20)
        self.assertEqual(got["read"]["shield_box"], (500, 180, 55, 59))
        self.assertEqual(got["read"]["n_glyphs"], 2)

    def test_existing_glyphs_never_receive_low_score_retry(self):
        self.core.extract_glyphs.return_value = [{}]
        self.assertEqual(adapter.inspect_shield(self.shield())["reason"], "original_extraction_available")
        self.core._match_digit.assert_not_called()

    def test_exact_known_verification_pad_is_removed(self):
        padded = cv2.copyMakeBorder(self.shield(), 5, 5, 5, 5, cv2.BORDER_CONSTANT, value=(180, 180, 180))
        got = adapter.inspect_shield(padded, (500, 180, 55, 59))
        self.assertEqual(got["read"]["hp"], 20)
        self.assertEqual(got["evidence"]["known_read_box_pad_removed"], 5)

    def test_low_confidence_either_digit_is_unknown(self):
        for scores in (((2, .84, .60, 7), (0, .96, .63, 8)),
                       ((2, .95, .60, 7), (0, .84, .63, 8)),
                       ((2, .95, .90, 7), (0, .96, .63, 8))):
            self.core._match_digit.side_effect = scores
            self.assertIsNone(adapter.inspect_shield(self.shield())["read"])

    def test_missing_digit_does_not_become_off_center_single_hp(self):
        frame = self.shield()
        frame[18:44, 25:47] = cv2.cvtColor(np.uint8([[[30, 110, 24]]]), cv2.COLOR_HSV2BGR)[0, 0]
        self.assertIsNone(adapter.inspect_shield(frame)["read"])

    def test_small_unit_type_icons_cannot_use_fallback(self):
        frame = cv2.resize(self.shield(), (32, 32))
        self.assertEqual(adapter.inspect_shield(frame)["reason"], "unsupported_shield_geometry")
        self.core._match_digit.assert_not_called()

    def test_invalid_or_plain_shields_are_unknown(self):
        for image in (None, np.zeros((59, 55), np.uint8), np.zeros((59, 55, 3), np.float32),
                      np.zeros((59, 55, 3), np.uint8), np.full((59, 55, 3), 155, np.uint8)):
            self.assertIsNone(adapter.inspect_shield(image)["read"])

    def test_digit_bank_override_is_preserved(self):
        bank = {2: [], 0: []}
        self.assertIsNotNone(adapter.inspect_shield(self.shield(), bank_=bank)["read"])
        self.assertTrue(all(call.args[1] is bank for call in self.core._match_digit.call_args_list))
        self.core.bank.assert_not_called()

    @staticmethod
    def bottom_margin_shield():
        hsv = np.full((43, 54, 3), (30, 110, 24), np.uint8)
        frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        cv2.rectangle(frame, (10, 15), (20, 40), (0, 0, 160), -1)
        cv2.rectangle(frame, (27, 15), (45, 40), (0, 0, 160), -1)
        return frame

    def test_even_close_shift_keeps_two_blank_source_rows(self):
        got = adapter.inspect_shield(self.bottom_margin_shield())
        self.assertEqual(got["read"]["hp"], 20)
        self.assertEqual(got["evidence"]["source_bottom_margin_recovered_glyphs"], [0, 1])

    def test_touching_crop_edge_is_not_a_complete_source_margin(self):
        frame = self.bottom_margin_shield()
        for crop in (frame[:-1], frame[:-2], frame[:-3]):
            self.assertIsNone(adapter.inspect_shield(crop)["read"])
        self.core._match_digit.assert_not_called()

    def test_raw_digit_pixels_in_bottom_margin_still_reject(self):
        frame = self.bottom_margin_shield()
        frame[-2:, 14:17] = (0, 0, 160)
        self.assertIsNone(adapter.inspect_shield(frame)["read"])
        self.core._match_digit.assert_not_called()

    def test_bottom_margin_recovery_does_not_relax_digit_scores(self):
        self.core._match_digit.side_effect = [(1, .849, .60, 7)]
        got = adapter.inspect_shield(self.bottom_margin_shield())
        self.assertIsNone(got["read"])
        self.assertEqual(got["reason"], "uncertain_digit")

    @staticmethod
    def green_fringe_shield(fringe_value=63):
        hsv = np.full((58, 55, 3), (30, 110, 43), np.uint8)
        hsv[15:39, 8:25] = (48, 140, 120)
        hsv[15:39, 28:45] = (48, 140, 120)
        hsv[39, 34:36] = (44, 113, fringe_value)
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    def fringe_matches(self, recovered=(3, .907, .699, 8), initial=(3, .818, .621, 8)):
        self.core._color_state.return_value = "green"
        self.core._match_digit.side_effect = [(2, .95, .53, 7), initial, recovered]

    def test_connected_green_source_fringe_recovers_same_winner(self):
        self.fringe_matches()
        frame = self.green_fringe_shield()
        before = frame.copy()
        got = adapter.inspect_shield(frame)
        self.assertEqual(got["read"]["hp"], 23)
        self.assertEqual(got["read"]["score"], .907)
        detail = got["evidence"]["digits"][1]
        self.assertEqual(detail["original_score"], .818)
        self.assertEqual(detail["fringe_attempt"]["source_values"], [63., 63.])
        self.assertEqual(self.core._match_digit.call_args_list[-1].args[0].shape, (25, 17, 3))
        np.testing.assert_array_equal(frame, before)

    def test_fringe_requires_two_near_threshold_pixels(self):
        self.fringe_matches()
        for value in (45, 60, 62):
            self.core._match_digit.reset_mock()
            self.fringe_matches()
            self.assertIsNone(adapter.inspect_shield(self.green_fringe_shield(value))["read"])
            self.assertEqual(self.core._match_digit.call_count, 2)

    def test_single_fringe_noise_pixel_is_not_recovery(self):
        self.fringe_matches()
        frame = self.green_fringe_shield()
        frame[39, 35] = frame[40, 35]
        self.assertIsNone(adapter.inspect_shield(frame)["read"])
        self.assertEqual(self.core._match_digit.call_count, 2)

    def test_detached_fringe_cannot_recover(self):
        self.fringe_matches()
        frame = self.green_fringe_shield()
        frame[38, 33:37] = frame[40, 33:37]
        self.assertIsNone(adapter.inspect_shield(frame)["read"])
        self.assertEqual(self.core._match_digit.call_count, 2)

    def test_second_faint_row_is_outside_one_row_recovery(self):
        self.fringe_matches()
        frame = self.green_fringe_shield()
        frame[40, 34:36] = frame[39, 34:36]
        self.assertIsNone(adapter.inspect_shield(frame)["read"])
        self.assertEqual(self.core._match_digit.call_count, 2)

    def test_fringe_pixels_must_still_be_green(self):
        self.fringe_matches()
        frame = self.green_fringe_shield()
        frame[39, 34:36] = cv2.cvtColor(np.uint8([[[20, 113, 63]]]), cv2.COLOR_HSV2BGR)[0, 0]
        self.assertIsNone(adapter.inspect_shield(frame)["read"])
        self.assertEqual(self.core._match_digit.call_count, 2)

    def test_red_or_mixed_glyphs_do_not_receive_green_retry(self):
        for colors in (("red",), ("white",), ("green", "red")):
            self.fringe_matches()
            self.core._match_digit.reset_mock()
            self.core._color_state.side_effect = lambda _g, seq=iter(colors * 4): next(seq)
            self.assertIsNone(adapter.inspect_shield(self.green_fringe_shield())["read"])
            self.assertEqual(self.core._match_digit.call_count, 2)
        self.core._color_state.side_effect = None

    def test_green_fringe_cannot_upgrade_a_different_winner(self):
        self.fringe_matches(recovered=(8, .97, .69, 3))
        got = adapter.inspect_shield(self.green_fringe_shield())
        self.assertIsNone(got["read"])
        self.assertEqual(got["evidence"]["digits"][1]["digit"], 3)

    def test_ambiguous_original_winner_cannot_receive_fringe_retry(self):
        self.fringe_matches(initial=(3, .818, .76, 8))
        self.assertIsNone(adapter.inspect_shield(self.green_fringe_shield())["read"])
        self.assertEqual(self.core._match_digit.call_count, 2)

    def test_recovered_crop_still_needs_full_score_and_margin(self):
        for recovered in ((3, .849, .60, 8), (3, .92, .83, 8), (3, float("nan"), .60, 8)):
            self.fringe_matches(recovered=recovered)
            self.assertIsNone(adapter.inspect_shield(self.green_fringe_shield())["read"])

    def test_green_fringe_cannot_repair_clipped_shield(self):
        for height in (38, 39, 40, 41, 42):
            self.fringe_matches()
            self.assertIsNone(adapter.inspect_shield(self.green_fringe_shield()[:height])["read"])

    def test_successful_green_digits_keep_original_scores_and_no_retry(self):
        self.fringe_matches(initial=(3, .91, .69, 8))
        got = adapter.inspect_shield(self.green_fringe_shield())
        self.assertEqual(got["read"]["hp"], 23)
        self.assertEqual(got["read"]["score"], .91)
        self.assertEqual(self.core._match_digit.call_count, 2)

    def test_fringe_retry_uses_supplied_original_bank(self):
        self.fringe_matches()
        bank = {2: [], 3: []}
        self.assertEqual(adapter.inspect_shield(self.green_fringe_shield(), bank_=bank)["read"]["hp"], 23)
        self.assertTrue(all(call.args[1] is bank for call in self.core._match_digit.call_args_list))
        self.core.bank.assert_not_called()

    def test_recovered_bottom_must_keep_pair_alignment(self):
        self.fringe_matches()
        hsv = cv2.cvtColor(self.green_fringe_shield(), cv2.COLOR_BGR2HSV)
        hsv[15:39, 8:25] = (30, 110, 43)
        hsv[13:37, 8:25] = (48, 140, 120)
        self.assertIsNone(adapter.inspect_shield(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))["read"])
        self.assertEqual(self.core._match_digit.call_count, 2)

    def test_recovered_height_must_keep_original_glyph_limit(self):
        self.fringe_matches()
        hsv = np.full((78, 55, 3), (30, 110, 43), np.uint8)
        hsv[12:56, 8:25] = (48, 140, 120)
        hsv[12:56, 28:45] = (48, 140, 120)
        hsv[56, 34:36] = (44, 113, 63)
        self.assertIsNone(adapter.inspect_shield(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))["read"])
        self.assertEqual(self.core._match_digit.call_count, 2)

    @staticmethod
    def red_singleton_shield(value=53):
        hsv = np.full((59, 54, 3), (30, 110, 30), np.uint8)
        hsv[15:40, 10:21] = (7, 180, 140)
        hsv[16:41, 28:45] = (7, 180, 140)
        hsv[15, 36] = (7, 173, value)
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    def red_matches(self, initial=(3, .826, .708, 8), recovered=(3, .891, .683, 8)):
        self.core._color_state.side_effect = None
        self.core._color_state.return_value = "red"
        self.core._match_digit.reset_mock()
        self.core._match_digit.side_effect = [(1, .944, .567, 7), initial, recovered]

    def test_single_near_threshold_red_top_pixel_restores_same_winner_crop(self):
        self.red_matches()
        frame = self.red_singleton_shield()
        before = frame.copy()
        got = adapter.inspect_shield(frame)
        self.assertEqual(got["read"]["hp"], 13)
        self.assertEqual(got["read"]["score"], .891)
        detail = got["evidence"]["digits"][1]
        self.assertEqual(detail["original_score"], .826)
        self.assertEqual(detail["top_singleton_attempt"]["threshold"], 52)
        self.assertEqual(detail["top_singleton_attempt"]["source_hsv"][2], 53)
        self.assertEqual(detail["top_singleton_attempt"]["original_box"], [29, 16, 17, 26])
        self.assertEqual(detail["top_singleton_attempt"]["recovered_box"], [29, 17, 17, 25])
        self.assertEqual(self.core._match_digit.call_args_list[-1].args[0].shape, (25, 17, 3))
        np.testing.assert_array_equal(frame, before)

    def test_red_top_pixel_brighter_than_one_threshold_step_is_not_removed(self):
        for value in (54, 60, 110, 140):
            self.red_matches()
            self.assertIsNone(adapter.inspect_shield(self.red_singleton_shield(value))["read"])
            self.assertEqual(self.core._match_digit.call_count, 2)

    def test_red_top_pixel_itself_must_be_saturated_red(self):
        for color in ((48, 173, 53), (30, 173, 53), (7, 40, 53), (0, 0, 111)):
            self.red_matches()
            frame = self.red_singleton_shield()
            frame[15, 36] = cv2.cvtColor(np.uint8([[color]]), cv2.COLOR_HSV2BGR)[0, 0]
            self.assertIsNone(adapter.inspect_shield(frame)["read"])
            self.assertEqual(self.core._match_digit.call_count, 2)

    def test_two_top_pixels_or_another_upper_row_do_not_receive_red_retry(self):
        for extra in ((15, 37), (14, 36)):
            self.red_matches()
            frame = self.red_singleton_shield()
            frame[extra] = frame[15, 36]
            self.assertIsNone(adapter.inspect_shield(frame)["read"])
            self.assertEqual(self.core._match_digit.call_count, 2)

    def test_red_top_pixel_requires_broad_bright_directly_connected_body(self):
        for mode in ("narrow", "dim", "only_diagonal", "mixed_color"):
            self.red_matches()
            hsv = cv2.cvtColor(self.red_singleton_shield(), cv2.COLOR_BGR2HSV)
            if mode == "narrow":
                hsv[16, 28:45] = (30, 110, 30)
                hsv[16, 36] = (7, 180, 140)
            elif mode == "dim":
                hsv[16, 28:45] = (7, 173, 54)
            elif mode == "only_diagonal":
                hsv[16, 36] = (30, 110, 30)
            else:
                hsv[16, 31] = (48, 180, 140)
            self.assertIsNone(adapter.inspect_shield(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))["read"])
            self.assertEqual(self.core._match_digit.call_count, 2)

    def test_red_top_singleton_at_left_or_right_component_edge_is_not_removed(self):
        for column in (28, 44):
            self.red_matches()
            frame = self.red_singleton_shield()
            frame[15, column] = frame[15, 36]
            frame[15, 36] = frame[14, 36]
            self.assertIsNone(adapter.inspect_shield(frame)["read"])
            self.assertEqual(self.core._match_digit.call_count, 2)

    def test_red_retry_needs_original_three_winner_and_margin(self):
        for initial in ((8, .826, .708, 3), (3, .826, .727, 8),
                        (3, float("nan"), .708, 8), (3, .826, float("nan"), 8)):
            self.red_matches(initial=initial)
            self.assertIsNone(adapter.inspect_shield(self.red_singleton_shield())["read"])
            self.assertEqual(self.core._match_digit.call_count, 2)

    def test_red_retry_still_needs_same_winner_full_score_and_margin(self):
        for recovered in ((8, .97, .6, 3), (3, .849, .6, 8), (3, .92, .821, 8),
                          (3, float("nan"), .6, 8), (3, float("inf"), .6, 8),
                          (3, .92, float("nan"), 8)):
            self.red_matches(recovered=recovered)
            self.assertIsNone(adapter.inspect_shield(self.red_singleton_shield())["read"])
            self.assertEqual(self.core._match_digit.call_count, 3)

    def test_successful_red_three_or_no_top_pixel_never_gets_extra_crop(self):
        for value in (52, 53):
            self.red_matches(initial=(3, .891, .683, 8))
            got = adapter.inspect_shield(self.red_singleton_shield(value))
            self.assertEqual(got["read"]["hp"], 13)
            self.assertEqual(got["read"]["score"], .891)
            self.assertEqual(self.core._match_digit.call_count, 2)
            self.assertNotIn("top_singleton_attempt", got["evidence"]["digits"][1])
        self.red_matches()
        self.assertIsNone(adapter.inspect_shield(self.red_singleton_shield(52))["read"])
        self.assertEqual(self.core._match_digit.call_count, 2)

    def test_red_retry_refuses_mixed_pair_or_single_digit(self):
        self.red_matches()
        self.core._color_state.side_effect = lambda gs: "white" if gs[0]["x"] < 25 else "red"
        self.assertIsNone(adapter.inspect_shield(self.red_singleton_shield())["read"])
        self.assertEqual(self.core._match_digit.call_count, 2)
        self.red_matches()
        frame = self.red_singleton_shield()
        frame[15:40, 10:21] = frame[10, 10]
        self.assertIsNone(adapter.inspect_shield(frame)["read"])
        self.core._match_digit.assert_not_called()

    def test_red_retry_preserves_pair_alignment(self):
        self.red_matches()
        hsv = cv2.cvtColor(self.red_singleton_shield(), cv2.COLOR_BGR2HSV)
        hsv[15:40, 10:21] = (30, 110, 30)
        hsv[13:40, 10:21] = (7, 180, 140)
        self.assertIsNone(adapter.inspect_shield(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))["read"])
        self.assertEqual(self.core._match_digit.call_count, 2)

    def test_red_retry_uses_original_bank_and_keeps_successful_core_result(self):
        self.red_matches()
        bank = {1: [], 3: []}
        self.assertEqual(adapter.inspect_shield(self.red_singleton_shield(), bank_=bank)["read"]["hp"], 13)
        self.assertTrue(all(c.args[1] is bank for c in self.core._match_digit.call_args_list))
        self.core.bank.assert_not_called()
        self.core.read_shield.return_value = {"hp": 13, "score": .826, "why": "original"}
        self.core._match_digit.reset_mock()
        self.assertIs(adapter.read_shield(self.red_singleton_shield()), self.core.read_shield.return_value)
        self.core._match_digit.assert_not_called()

    def olive_fragment_shield(self):
        hsv = np.full((58, 54, 3), (30, 110, 24), np.uint8)
        hsv[15:39, 8:25] = (48, 140, 120)
        hsv[15:39, 28:45] = (48, 140, 120)
        hsv[40:58, 9:43] = (25, 90, 24)
        hsv[43:55, 12:38] = (25, 110, 24)
        frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        self.core.extract_glyphs.return_value = [{"img": frame[44:56, 13:39],
                                                "x": 13, "y": 44, "w": 26, "h": 12}]
        self.core._match_digit.side_effect = [(2, .04, -.13, 3), (2, .95, .6, 7), (3, .96, .63, 8)]
        self.core._color_state.return_value = "green"
        return frame

    def test_one_non_digit_olive_bottom_fragment_does_not_block_color_extraction(self):
        got = adapter.inspect_shield(self.olive_fragment_shield())
        self.assertEqual(got["read"]["hp"], 23)
        self.assertIn("discarded_original_fragment", got["evidence"])

    def test_olive_shape_with_credible_digit_match_is_not_retried(self):
        frame = self.olive_fragment_shield()
        for score in (.45, .818, .95):
            self.core._match_digit.side_effect = [(3, score, .1, 8)]
            got = adapter.inspect_shield(frame)
            self.assertIsNone(got["read"])
            self.assertEqual(got["reason"], "original_extraction_available")

    def test_any_white_red_green_or_bright_pixel_in_original_fragment_blocks_retry(self):
        for color in ((0, 0, 150), (0, 180, 90), (48, 140, 90), (25, 110, 120)):
            frame = self.olive_fragment_shield()
            frame[48, 20] = cv2.cvtColor(np.uint8([[color]]), cv2.COLOR_HSV2BGR)[0, 0]
            self.core._match_digit.reset_mock()
            got = adapter.inspect_shield(frame)
            self.assertIsNone(got["read"])
            self.assertEqual(got["reason"], "original_extraction_available")
            self.core._match_digit.assert_not_called()

    def test_two_original_fragments_are_not_reinterpreted_as_background(self):
        frame = self.olive_fragment_shield()
        self.core.extract_glyphs.return_value *= 2
        self.core._match_digit.reset_mock()
        self.assertEqual(adapter.inspect_shield(frame)["reason"], "original_extraction_available")
        self.core._match_digit.assert_not_called()

    def test_olive_bottom_fragment_recovery_still_needs_final_digit_score(self):
        frame = self.olive_fragment_shield()
        self.core._match_digit.side_effect = [(2, .04, -.13, 3), (2, .95, .6, 7), (3, .849, .63, 8)]
        self.assertIsNone(adapter.inspect_shield(frame)["read"])

    def test_olive_fragment_bank_override_is_used_for_all_matching(self):
        frame = self.olive_fragment_shield()
        bank = {2: [], 3: []}
        self.assertEqual(adapter.inspect_shield(frame, bank_=bank)["read"]["hp"], 23)
        self.assertTrue(all(call.args[1] is bank for call in self.core._match_digit.call_args_list))
        self.core.bank.assert_not_called()


if __name__ == "__main__":
    unittest.main()
