"""Deploy-target regressions, including the green-table surface fix.

Fixtures are one real 640x320 tabletop crop from a reviewed saved session
(`deploy-fixtures/green-table-00091.png`); the surface signature is calibrated
to real pixels, so a synthetic plate cannot stand in for it. The crop contains
areas that confirm the paint signature and areas that do not, which keeps both
directions honest.

The fix that motivated this file: on the green (painted) table a developed board
covers both calibrated painted-green references, so the surface used to stay
unconfirmed and every real empty slot was refused. Position may now be resolved
per frame, therefore the negative direction matters most - a card must never be
accepted as the surface, and a wood board must never be read as paint.
"""
import json
from pathlib import Path
import unittest
from unittest import mock

import cv2
import numpy as np

import apk_deploy_target as dt

WIDTH, HEIGHT = 116, 145
FIXTURES = Path(__file__).resolve().parent / "deploy-fixtures"
CONFIRMED_AT = (200, 100)          # 116x145 window that passes on the fixture
REFUSED_AT = (0, 0)                # window on the same crop that does not


def fixture():
    frame = cv2.imread(str(FIXTURES / "green-table-00091.png"))
    if frame is None:
        raise unittest.SkipTest("green table fixture missing")
    return frame


def plate(shape=(720, 1280, 3), at=(0, 0)):
    """A full frame whose surface is the real tabletop crop, tiled."""
    frame = np.zeros(shape, np.uint8)
    crop = fixture()
    for y in range(0, shape[0], crop.shape[0]):
        for x in range(0, shape[1], crop.shape[1]):
            tile = crop[:min(crop.shape[0], shape[0] - y), :min(crop.shape[1], shape[1] - x)]
            frame[y:y + tile.shape[0], x:x + tile.shape[1]] = tile
    return frame


def card_crop():
    """Real card art, pasted to test that artwork is never surface evidence."""
    frame = cv2.imread(str(FIXTURES / "green-table-00091.png"))
    return frame


class SurfaceTests(unittest.TestCase):
    def _blueprint(self):
        frame = cv2.imread(str(FIXTURES / "blueprint-independent-00050.png"))
        self.assertIsNotNone(frame, "independent later blueprint fixture must be packaged")
        return frame

    def test_blueprint_packaged_atlas_has_only_reviewed_clean_pixels(self):
        dt._blueprint_atlas.cache_clear()
        loaded = dt._blueprint_atlas()
        self.assertIsNotNone(loaded, "both atlas and mask must be packaged and readable")
        atlas, mask = loaded
        self.assertFalse(bool(atlas[mask == 0].any()))
        self.assertFalse(bool(mask[435:580, 575:715].any()), "calibration HQ must not be a clear template")
        self.assertFalse(atlas.flags.writeable)
        self.assertFalse(mask.flags.writeable)

    def test_blueprint_independent_frame_matches_recentered_outer_coordinates(self):
        # Actual frame 50 pixels, independent of calibration frame 49. Different
        # x coordinates cover the existing +/-144 recentering rule, without
        # inventing surface pixels or only supporting the initial 786 landing.
        frame = self._blueprint()
        for x in (424, 498, 786, 856, 928, 1000):
            box = [x-58, 435, x+58, 580]
            clear, detail = dt._blueprint_background(frame, box)
            self.assertTrue(clear, (box, detail))

    def test_blueprint_cannot_cross_calibration_hq_props_or_ui(self):
        frame = self._blueprint()
        for box in ([582, 435, 698, 580], [502, 435, 618, 580],
                    [943, 435, 1059, 580], [294, 435, 410, 580]):
            clear, detail = dt._blueprint_background(frame, box)
            self.assertFalse(clear, box)
            self.assertEqual("blueprint_unreviewed_coordinates", detail["rejection"])

    def test_blueprint_real_blue_card_hq_and_other_surface_crops_are_refused(self):
        # Real saved crops pasted at a landing are synthetic composites; the
        # crop pixels are real, but no claim is made that this scene occurred.
        box = [728, 435, 844, 580]
        for name in ("blue-card", "hq", "wood", "green", "cloth"):
            crop = cv2.imread(str(FIXTURES / ("blueprint-negative-" + name + ".png")))
            self.assertIsNotNone(crop, name)
            self.assertEqual((145, 116, 3), crop.shape, name)
            frame = self._blueprint()
            frame[435:580, 728:844] = crop
            clear, detail = dt._blueprint_background(frame, box)
            self.assertFalse(clear, (name, detail))
            self.assertEqual("blueprint_same_coordinate_drawing_mismatch", detail["rejection"])

    def test_blueprint_flat_noise_shifted_drawing_and_card_rim_are_refused(self):
        box = [728, 435, 844, 580]
        frame = self._blueprint()
        original = frame[435:580, 728:844].copy()
        rng = np.random.RandomState(7)
        variants = {
            "flat_blue": np.full_like(original, np.median(original.reshape(-1, 3), axis=0)),
            "blue_noise": rng.randint(10, 65, original.shape).astype(np.uint8),
            "shifted_drawing": np.roll(original, 4, axis=1),
            "dim_card": (original.astype(np.float32) * .7).astype(np.uint8),
            "card_rim": original.copy(),
        }
        cv2.rectangle(variants["card_rim"], (2, 2), (113, 142), (75, 82, 92), 3)
        for name, crop in variants.items():
            modified = frame.copy()
            modified[435:580, 728:844] = crop
            self.assertFalse(dt._blueprint_background(modified, box)[0], name)

    def test_blueprint_missing_or_widened_mask_abstains(self):
        frame = self._blueprint()
        with mock.patch.object(dt, "_blueprint_atlas", return_value=None):
            clear, detail = dt._blueprint_background(frame, [728, 435, 844, 580])
        self.assertFalse(clear)
        self.assertEqual("blueprint_atlas_unavailable", detail["rejection"])
        # The real loader compares against code-defined reviewed rectangles.
        mask = np.full((720, 1280), 255, np.uint8)
        with mock.patch.object(dt.cv2, "imdecode", side_effect=[frame, mask]):
            dt._blueprint_atlas.cache_clear()
            self.assertIsNone(dt._blueprint_atlas())
        dt._blueprint_atlas.cache_clear()

    def test_fixture_confirms_at_its_known_window(self):
        frame = fixture()
        x0, y0 = CONFIRMED_AT
        patch = frame[y0:y0 + HEIGHT, x0:x0 + WIDTH]
        hsv, gray, raw = dt._pixel_metrics(patch)
        clear, detail = dt._painted_green_background(hsv, gray, raw)
        self.assertTrue(clear, detail.get("rejection"))

    def test_fixture_refuses_where_the_surface_is_not_paint(self):
        frame = fixture()
        x0, y0 = REFUSED_AT
        patch = frame[y0:y0 + HEIGHT, x0:x0 + WIDTH]
        hsv, gray, raw = dt._pixel_metrics(patch)
        clear, _ = dt._painted_green_background(hsv, gray, raw)
        self.assertFalse(clear, "the fixture must keep a non-paint area")

    def test_card_plate_never_confirms_as_surface(self):
        # The load-bearing refusal: a card-sized plate of bright artwork must
        # not pass the paint signature at the calibrated size.
        plate_frame = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
        plate_frame[:] = (150, 160, 175)
        cv2.rectangle(plate_frame, (5, 5), (WIDTH - 6, HEIGHT - 40), (215, 220, 225), -1)
        cv2.circle(plate_frame, (WIDTH // 2, HEIGHT // 2), 30, (60, 70, 90), -1)
        hsv, gray, raw = dt._pixel_metrics(plate_frame)
        clear, detail = dt._painted_green_background(hsv, gray, raw)
        self.assertFalse(clear)
        self.assertTrue(detail.get("rejection"))

    def test_scan_never_returns_a_box_that_fails_its_own_signature(self):
        frame = plate()
        primary = [{"box": [362, 180, 478, 325], "confirmed": False},
                   {"box": [802, 180, 918, 325], "confirmed": False}]
        probes = dt._painted_green_fallbacks(frame, [], primary)
        for probe in probes:
            x0, y0, x1, y1 = probe["box"]
            self.assertEqual([x1 - x0, y1 - y0], [WIDTH, HEIGHT])
            hsv, gray, raw = dt._pixel_metrics(frame[y0:y1, x0:x1])
            clear, _ = dt._painted_green_background(hsv, gray, raw)
            self.assertEqual(bool(probe["confirmed"]), bool(clear),
                             "probe %s disagrees with its own signature" % (probe["box"],))

    def test_scan_boxes_avoid_both_landing_candidates(self):
        frame = plate()
        primary = [{"box": [362, 180, 478, 325], "confirmed": False},
                   {"box": [802, 180, 918, 325], "confirmed": False}]
        probes = dt._painted_green_fallbacks(frame, [], primary)
        landings = [[x - dt.HALF_WIDTH, dt.PATCH_Y0, x + dt.HALF_WIDTH, dt.PATCH_Y1]
                    for x in (640 + dt.ROW_STEP, 640 - dt.ROW_STEP)]
        self.assertTrue(probes)
        for probe in probes:
            for landing in landings:
                self.assertFalse(dt._overlap(probe["box"], landing),
                                 "probe %s overlaps landing %s" % (probe["box"], landing))

    def test_occupied_boxes_are_not_probed(self):
        frame = plate()
        primary = [{"box": [362, 180, 478, 325], "confirmed": False}]
        obstacle = {"kind": "observed_card_or_hq",
                    "box": [200, 260, 1060, 430]}
        probes = dt._painted_green_fallbacks(frame, [obstacle], primary)
        for probe in probes:
            self.assertFalse(dt._overlap(probe["box"], obstacle["box"]),
                             "probe %s ignores an obstacle" % (probe["box"],))

    def test_existing_primary_suppresses_the_scan(self):
        frame = plate()
        primary = [{"box": [362, 180, 478, 325], "confirmed": True, "fallback": False}]
        self.assertEqual([], dt._painted_green_fallbacks(frame, [], primary))


class ProfileSelectionTests(unittest.TestCase):
    def _blue_observed(self, boxes):
        return {"obstacles": [], "references": {"blueprint_aircraft": [
            {"box": box, "confirmed": True} for box in boxes]}}

    def test_blueprint_two_references_and_independent_landing_are_required(self):
        landing = [728, 435, 844, 580]
        one = self._blue_observed([[240, 180, 356, 325]])
        self.assertIsNone(dt._profile_for_landing(one, landing)["profile"])
        pair = self._blue_observed([[240, 180, 356, 325], [920, 435, 1036, 580]])
        self.assertEqual("blueprint_aircraft", dt._profile_for_landing(pair, landing)["profile"])

    def test_blueprint_near_or_overlapping_references_do_not_count_for_landing(self):
        landing = [728, 435, 844, 580]
        for second in ([870, 435, 986, 580], [800, 435, 916, 580]):
            observed = self._blue_observed([[240, 180, 356, 325], second])
            self.assertIsNone(dt._profile_for_landing(observed, landing)["profile"])

    def test_blueprint_reference_geometry_obstacles_are_not_pixel_evidence(self):
        frame = cv2.imread(str(FIXTURES / "blueprint-independent-00050.png"))
        self.assertIsNotNone(frame)
        obstacles = [{"kind": "observed_card_or_hq", "box": [225, 120, 1050, 590]}]
        with mock.patch.object(dt, "_reference_obstacles", return_value=obstacles):
            observed = dt._background_profile(frame)
        self.assertIsNone(observed["profile"])
        self.assertFalse(any(r["confirmed"] for r in observed["references"]["blueprint_aircraft"]))

    def test_blueprint_conflicting_material_stays_unknown(self):
        observed = self._blue_observed([[240, 180, 356, 325], [920, 435, 1036, 580]])
        observed["references"]["wood"] = [
            {"box": [292, 270, 408, 415], "confirmed": True}]
        self.assertEqual("conflicting_background_evidence", dt._profile_for_landing(observed)["reason"])

    def _observed(self, positives, frame=None):
        return {"obstacles": [], "frame": frame,
                "references": {"painted_green": [
                    {"box": box, "confirmed": True} for box in positives]}}

    def test_two_separated_references_select_without_landing(self):
        observed = self._observed([[240, 270, 356, 415], [560, 270, 676, 415]])
        self.assertEqual("painted_green", dt._profile_for_landing(observed).get("profile"))

    def test_single_reference_alone_is_not_enough(self):
        observed = self._observed([[240, 270, 356, 415]])
        self.assertIsNone(dt._profile_for_landing(observed).get("profile"))

    def test_single_reference_plus_landing_paint_selects(self):
        frame = plate()
        observed = self._observed([[240, 270, 356, 415]], frame=frame)
        landing = [640 + dt.ROW_STEP - dt.HALF_WIDTH, dt.PATCH_Y0,
                   640 + dt.ROW_STEP + dt.HALF_WIDTH, dt.PATCH_Y1]
        selected = dt._profile_for_landing(observed, landing)
        self.assertEqual("painted_green", selected.get("profile"))
        self.assertEqual(2, len(selected["selected_references"]))

    def test_single_reference_with_non_paint_landing_is_refused(self):
        frame = plate()
        landing = [640 + dt.ROW_STEP - dt.HALF_WIDTH, dt.PATCH_Y0,
                   640 + dt.ROW_STEP + dt.HALF_WIDTH, dt.PATCH_Y1]
        frame[dt.PATCH_Y0:dt.PATCH_Y1, landing[0]:landing[2]] = (215, 220, 225)
        observed = self._observed([[240, 270, 356, 415]], frame=frame)
        self.assertIsNone(dt._profile_for_landing(observed, landing).get("profile"))

    def test_conflicting_surface_still_wins_as_unknown(self):
        observed = self._observed([[240, 270, 356, 415], [560, 270, 676, 415]])
        observed["references"]["wood"] = [{"box": [292, 270, 408, 415], "confirmed": True},
                                          {"box": [868, 270, 984, 415], "confirmed": True}]
        selected = dt._profile_for_landing(observed)
        self.assertIsNone(selected.get("profile"))
        self.assertEqual("conflicting_background_evidence", selected.get("reason"))


if __name__ == "__main__":
    unittest.main()
