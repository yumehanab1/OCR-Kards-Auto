"""Saved plate pixels, availability boundaries and geometry; no real input."""
import base64
import unittest
from unittest import mock
from types import SimpleNamespace

import cv2
import numpy as np

import apk_hand_availability as availability
from apk_hand_cost_templates import SAMPLES


# Unmodified 23x23 primary/operation plate from live17 frame 4, (502,620).
# The core identified this CR.42 as unit/orange; numeric cost OCR was unknown.
ORANGE_PLATE_PNG = "iVBORw0KGgoAAAANSUhEUgAAABcAAAAXCAIAAABvSEP3AAAEVElEQVQ4EW3B/W+VhRnH4c/9vJ6n7xw7W6DKBkVqpQhFeSmYEBxsMIeIMTEmxmSJiQma/Tetv2zTuMRkzCz6gxoNMcbo0S0QLbSOyUtXED2tlVJj23PO89zf9VAyNfG67NmnDuZ5vrhcbzRygbtLCNRkkrvQCuQuQJK7JEBZKQnDoJSmtnt40/zCorsX7kUhhBAgQCoKFyAw/k+SYUAQWOE+0N9nu3Zsmr7+jcQqAwwwkAlHEisMMJNkBkJgIDBjy8b1tnVg/czcd0BotGdxWyle2x71tikJ/btasVjLP5zKRZOZhSbJHAwCU+6Y0fOLNbZ5U+/NhUWDIwPhUG/U3WppRBRgCDh90V871xBNgXFsMO7tSN+5qP6ytyZ6/XxNUrncblv6e+cXliTtvTt8emcEGAiMpvcuF6+N54WwFej4fenOvuhfX6ZDPbVT5/IL1ZpgTVebDWxeO39zETi8pdTX6RK/WhOUWxww7PzXPvZx3cWKwHh8qLRvgy0XwdQNf2Oycf1mDnR1tNrgPeu+vfm9RBYHSYhg+7rkiSEPjBUTVR/7qOE0mfHEttb9G4pvl4Mk5K9ni8lqDehsb7Ghwbtm5xbkErcd2hw/OhgGgYDJqo9WGi5AwOF7sgObwrcvcP9aagWvnFlaanh7a2Y7hjZ8NTOvJlYN96XPDFscymCi6qOVhgsQ2G8HWu+9Mzo1vnxHK7/uD/82Xly9UWttSe2B7RuvfTWnJlb13xGfHInSyIHJqo9WGu4CzKyno5TLFpbqeV5gGBQiKyW254HNU1dnJZdYtbEcnxyJstiByaqPVhoufo7AzCilie3fveXS1NeuFdyiX5bT5/dGLXEOTM74WCUvJMOEDCuXu7JSqZHn8/MLtXrdIMtSOzAyeOHSdXcXq3R3V/r8SNSWFsBktRit5C5xi1nwyNGDwzu21euNP/3l1ZnZOSBLE3v4oa2ff3GtcJdY1deZvLAv6kgLwWTVRyt1d5rMgJYse2j/rj27h8defHnmmzkgTRM7fGDbuX9Pe+HitnWdycm9cTnLgYlqMVrJ3cUKM8Bg967hx44fGXvxpanpa0CaxHb04PazE1fcxW3q7UhP7o27W3JgoupjlUYh8QPbtfP+Y8d+8+eXXr1y5SqQprH97tDwmc8uucRt6sriP+5Letpy4L3L/vfxhmgyTAhYv27t7x859NZbp/979TqolCZ27PDOf3520V0gBGbtafTcnnhj2YH3LxenxvNCYpXAuLO7+8SJo2++fXp6+ksgK6X22JEHPz77n6JwjCbRVopObE2NRhIFN5b0j/P1wsWPJHHS09M9Ozu3XKuDOjva7MnjIx988nkjz/mRMLCiUBAEZpJMEmYgbjFMyEBgZh3tLfaHJw+8+8G5Wr3OT5gBRmBNGAgzA5kZIDAMCALr6myzZ586+MmnXxQud7krMMOwVYGZYVhghllgFoQWmIVhGIRBGFhLVkqTOIqC/wGdTy3lROT1ZQAAAABJRU5ErkJggg=="


class HandAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.full((720, 1280, 3), 125, np.uint8)
        self.badge = {"cx": 600, "cy": 630, "kind": "unit", "state": "orange"}
        self.cost = {"candidate": 1, "score": .97, "margin": .3, "numeral_candidate": 1,
                     "numeral_score": .97, "numeral_margin": .3, "angle": 0}

    def real_orange_plate(self):
        crop = cv2.imdecode(np.frombuffer(base64.b64decode(ORANGE_PLATE_PNG), np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(crop.shape, (23, 23, 3))
        self.frame[617:640, 587:610] = crop
        self.badge.update(cx=594, cy=628)
        return self.frame[617:640, 587:610]

    def test_templates_decode_without_external_paths(self):
        bank = availability._templates()
        self.assertEqual(len(bank), 9)
        self.assertEqual({cost for cost, _ in bank}, {1, 2, 3, 4, 6, 8})
        self.assertTrue(all(feature.shape == (22, 22) for _, feature in bank))

    def test_nonunit_or_nonorange_is_always_rejected(self):
        self.real_orange_plate()
        for update in ({"kind": "unknown"}, {"kind": "order"}, {"state": "grey"}, {"state": "unknown"}):
            self.assertFalse(availability.inspect_unit(self.frame, dict(self.badge, **update), credits=20)["allowed"])

    def test_unknown_or_invalid_resource_count_is_optional(self):
        self.real_orange_plate()
        for value in (True, -1, 25, 2.5, "2"):
            result = availability.inspect_unit(self.frame, self.badge, credits=value)
            self.assertTrue(result["allowed"])
            self.assertIsNone(result["credits"])

    def test_default_approval_does_not_consult_numeric_readers(self):
        self.real_orange_plate()
        reader = mock.Mock(side_effect=AssertionError("Numeric OCR is not an action gate"))
        with mock.patch.dict("sys.modules", {"apk_hud_adapter": SimpleNamespace(inspect_kredits=reader)}), \
                mock.patch.object(availability, "_read_cost", reader):
            result = availability.filter_units(self.frame, [self.badge])
        self.assertEqual(len(result["units"]), 1)
        approved = result["units"][0]["apk_availability"]
        self.assertEqual(approved["basis"], "orange_unit_geometry_v1")
        self.assertIsNone(approved["cost"])
        self.assertIsNone(approved["credits"])
        self.assertIsNotNone(result["units"][0]["apk_grab_point"])
        reader.assert_not_called()

    def test_saved_unknown_cost_is_allowed_with_known_or_unknown_hud(self):
        self.real_orange_plate()
        with mock.patch.dict("sys.modules", {"apk_hud_adapter": SimpleNamespace(inspect_kredits=lambda _: {"value": None})}):
            for credits in (None, 1):
                result = availability.inspect_unit(self.frame, self.badge, credits=credits, numeric_diagnostics=True)
                self.assertTrue(result["allowed"])
                self.assertIsNone(result["cost"])
                self.assertIsNone(result["evidence"]["numeric_affordability"])

    def test_visible_interior_unit_precedes_bottom_edge_unit(self):
        crop = self.real_orange_plate().copy()
        self.frame[650:673, 420:443] = crop
        low = dict(self.badge, cx=427, cy=661, card_id="lower")
        high = dict(self.badge, card_id="higher")
        original = [dict(low), dict(high)]
        result = availability.filter_units(self.frame, [low, high])
        self.assertEqual(["higher", "lower"], [b["card_id"] for b in result["units"]])
        self.assertEqual([[619,653], [452,686]], [b["apk_grab_point"] for b in result["units"]])
        self.assertEqual(original, [low, high])
        self.assertTrue(all(b["apk_availability"]["allowed"] for b in result["units"]))

    def test_higher_nonunit_does_not_gain_priority_or_permission(self):
        crop = self.real_orange_plate().copy()
        self.frame[650:673, 420:443] = crop
        low = dict(self.badge, cx=427, cy=661, card_id="lower")
        for update in ({"kind":"order"}, {"kind":"unknown"}, {"state":"grey"}):
            with self.subTest(update):
                high = dict(self.badge, card_id="higher", **update)
                result = availability.filter_units(self.frame, [low, high])
                self.assertEqual(["lower"], [b["card_id"] for b in result["units"]])

    def test_equal_height_candidates_keep_original_order(self):
        crop = self.real_orange_plate().copy()
        self.frame[617:640, 420:443] = crop
        left = dict(self.badge, cx=427, cy=628, card_id="left")
        right = dict(self.badge, card_id="right")
        for candidates in ([left, right], [right, left]):
            result = availability.filter_units(self.frame, candidates)
            self.assertEqual([b["card_id"] for b in candidates],
                             [b["card_id"] for b in result["units"]])

    def test_actual_partial_numeral_occlusion_keeps_confirmed_orange(self):
        crop = self.real_orange_plate()
        # Same 9x2 dark overlay replayed through the real classifier in the
        # saved-frame review. The operation numeral and plate stay intact.
        crop[4:6, 3:12] = 35
        result = availability.inspect_unit(self.frame, self.badge, credits=1, numeric_diagnostics=True)
        self.assertTrue(result["allowed"])
        self.assertIsNone(result["cost"])
        self.assertGreaterEqual(result["evidence"]["primary_ink"]["orange_fraction"], .85)

    def test_numeric_disagreement_is_diagnostic_only(self):
        self.real_orange_plate()
        with mock.patch.object(availability, "_read_cost", return_value=(8, self.cost)):
            result = availability.inspect_unit(self.frame, self.badge, credits=0, numeric_diagnostics=True)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["cost"], 8)
        self.assertFalse(result["evidence"]["numeric_affordability"])

    def test_grey_primary_with_orange_secondary_mark_is_rejected(self):
        crop = self.real_orange_plate()
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hsv[:, :13, 1] = 0
        crop[:] = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        result = availability.inspect_unit(self.frame, self.badge)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "primary_cost_ink_not_orange")

    def test_orange_pixels_without_plate_are_rejected(self):
        self.frame[620:635, 596:602] = (0, 140, 240)
        result = availability.inspect_unit(self.frame, self.badge)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "independent_cost_plate_missing")

    def test_no_independent_plate_stays_rejected(self):
        with mock.patch.object(availability, "_plates", return_value=[]):
            self.assertFalse(availability.inspect_unit(self.frame, self.badge, credits=20)["allowed"])

    def test_fixed_rule_uses_orange_anchor_center_not_dark_plate_center(self):
        self.real_orange_plate()
        approval = availability.inspect_unit(self.frame, self.badge)
        self.assertTrue(approval["allowed"])
        self.assertNotEqual([self.badge["cx"], self.badge["cy"]],
                            [approval["plate"][0]+approval["plate"][2]/2,
                             approval["plate"][1]+approval["plate"][3]/2])
        result = availability._safe_grab(self.frame, self.badge, approval)
        self.assertEqual(result["point"], [619, 653])
        self.assertEqual(result["reason"], "user_fixed_orange_digit_offset")
        self.assertFalse(result["evidence"]["selected_identity_verified"])

    def test_dense_or_irregular_neighbor_does_not_veto_fixed_rule(self):
        self.real_orange_plate()
        approval = availability.inspect_unit(self.frame, self.badge)
        # A valid source fee is already proved independently. Neither a close
        # unknown fee nor a distant artwork fragment may veto the whole hand.
        neighbors = [{"box": [625, 617, 26, 26], "cx": 638, "cy": 630, "angle": 0},
                     {"box": [795, 665, 22, 21], "cx": 806, "cy": 675.5, "angle": -45}]
        with mock.patch.object(availability, "_geometry_plates",
                               side_effect=AssertionError("not a grab gate")):
            result = availability._safe_grab(self.frame, self.badge, approval, geometry=neighbors)
        self.assertEqual(result["point"], [619, 653])
        self.assertFalse(result["evidence"]["selected_identity_verified"])

    def test_source_approval_and_current_candidate_color_are_required(self):
        self.real_orange_plate()
        approval = availability.inspect_unit(self.frame, self.badge)
        for bad in ({}, dict(approval, allowed=False), dict(approval, basis="unknown")):
            self.assertIsNone(availability._safe_grab(self.frame, self.badge, bad)["point"])
        for update in ({"state": "grey"}, {"state": "unknown"}, {"kind": "order"}, {"kind": "unknown"}):
            result = availability._safe_grab(self.frame, dict(self.badge, **update), approval)
            self.assertIsNone(result["point"])

    def test_invalid_center_or_clipped_point_is_rejected_without_clamping(self):
        self.real_orange_plate()
        approval = availability.inspect_unit(self.frame, self.badge)
        for update in ({"cx": True}, {"cy": "630"}, {"cx": float("nan")}, {"cy": float("inf")},
                       {"cx": 179}, {"cx": 1080}, {"cy": 544}, {"cy": 689}):
            result = availability._safe_grab(self.frame, dict(self.badge, **update), approval)
            self.assertIsNone(result["point"])
        for frame in (None, self.frame[:719], self.frame.astype(np.float32)):
            self.assertIsNone(availability._safe_grab(frame, self.badge, approval)["point"])

    def test_rotated_target_outside_calibration_still_has_no_approval(self):
        self.real_orange_plate()
        plate = {"box": [587, 617, 23, 23], "cx": 598.5, "cy": 628.5,
                 "angle": 30, "rectangularity": .95}
        with mock.patch.object(availability, "_geometry_plates", return_value=[plate]):
            result = availability.safe_grab(self.frame, self.badge)
        self.assertIsNone(result["point"])
        self.assertEqual(result["reason"], "plate_rotation_outside_calibration")

    def test_rectangular_unknown_fee_is_retained_as_geometry(self):
        # Both boxes have complete rectangular silhouettes and arbitrary,
        # unsupported interior ink. Geometry must not consult cost templates.
        for x in (587, 625):
            self.frame[617:643, x:x+26] = 35
            self.frame[624:636, x+8:x+18] = 170
        with mock.patch.object(availability, "_read_cost", side_effect=AssertionError("OCR not needed")):
            plates = availability._geometry_plates(self.frame)
        self.assertTrue(any(p["cx"] == 638 for p in plates))

    def test_isolated_irregular_component_stays_an_obstacle(self):
        # Without two complete fee-row anchors, a title-like fragment could
        # also be a chipped real cost plate; geometry cannot discard it.
        self.frame[617:643, 587:593] = 35
        self.frame[617:643, 607:613] = 35
        self.frame[627:633, 593:607] = 35
        self.assertTrue(availability._geometry_plates(self.frame))

    def test_irregular_component_far_below_two_complete_anchors_is_excluded(self):
        for x in (587, 685):
            self.frame[617:643, x:x+26] = 35
            self.frame[624:636, x+8:x+18] = 170
        self.frame[670:696, 625:631] = 35
        self.frame[670:696, 645:651] = 35
        self.frame[680:686, 631:645] = 35
        plates = availability._geometry_plates(self.frame)
        self.assertTrue(plates)
        self.assertFalse(any(625 <= p["cx"] <= 651 for p in plates))

    def test_chipped_real_neighbor_is_never_erased(self):
        for x in (587, 625):
            self.frame[617:643, x:x+26] = 35
            self.frame[624:636, x+8:x+18] = 170
        # Retain chipped real fee geometry for source validation/diagnostics;
        # the new explicit fixed grab rule does not use neighbour vetoes.
        self.frame[617:631, 625:633] = 125
        plates = availability._geometry_plates(self.frame)
        self.assertTrue(any(abs(p["cx"] - 638) < 4 for p in plates))
        # Having another complete anchor on the far side does not permit
        # deleting an incomplete component that remains on the fee row.
        self.frame[617:643, 685:711] = 35
        self.frame[624:636, 693:703] = 170
        plates = availability._geometry_plates(self.frame)
        self.assertTrue(any(abs(p["cx"] - 638) < 4 for p in plates))


if __name__ == "__main__":
    unittest.main()
