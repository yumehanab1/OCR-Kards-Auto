"""Offline equivalence checks for the narrow PR #4 speedup port."""
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from .fast_page import FastPage
from .frame_features import FrameFeatures
from .native_guard import Guards, MAX_SCALE_CACHE
from .native_objects import Objects, TYPES, normalized
from .page_detector import Detector

ASSETS = Path(__file__).resolve().parents[2] / 'assets'
SIZES = ((1280, 720), (1600, 720), (800, 600), (960, 600))


def combat_templates(names, mode):
    directory = ASSETS / 'mobile-core/ui_templates/android/combat'
    return {name: cv2.imdecode(np.frombuffer((directory / (name + '.png')).read_bytes(),
                                            np.uint8), mode) for name in names}


def direct_scores(bank, glyph):
    return {name: float(cv2.matchTemplate(glyph, needle, cv2.TM_CCOEFF_NORMED)[0, 0])
            for name, needle in bank.items()}


def accepted(scores):
    if scores is None:
        return None
    first, second = sorted(scores, key=scores.get, reverse=True)[:2]
    return first if scores[first] >= .90 and scores[first] - scores[second] >= .12 else None


def stamp(frame, image, x, y):
    h, w = image.shape[:2]
    frame[y:y+h, x:x+w] = image
    return [x, y, w, h]


def scaled_stamp(frame, image, factor, x, y):
    h, w = image.shape[:2]
    scale = frame.shape[0] / 720 * factor
    return stamp(frame, cv2.resize(image, (round(w*scale), round(h*scale))), x, y)


class ObjectChecks(unittest.TestCase):
    def test_score_boundary_and_degenerate_crops(self):
        objects = Objects(combat_templates(TYPES, cv2.IMREAD_GRAYSCALE))
        matrix = objects._unit_templates
        self.assertEqual((matrix.shape, matrix.dtype, matrix.flags.writeable),
                         ((5, 1024), np.dtype('float32'), False))
        np.testing.assert_allclose(matrix.mean(axis=1), 0, atol=1e-8)
        np.testing.assert_allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-6)
        template = objects.bank['artillery']
        noise = np.random.default_rng(0).normal(size=template.shape)
        glyph = np.clip(np.rint(.7*template + 55 + 16.256403923034668*noise), 0, 255).astype(np.uint8)
        glyph.flat[1002] -= 3
        # Reproduce the review's rounding issue with a deterministic perturbation.
        # The exact OpenCV value can vary by a few ULPs across its CPU backends.
        centered = glyph.ravel().astype(np.float32)
        centered -= centered.mean()
        needle = template.ravel().astype(np.float32)
        needle -= needle.mean()
        pr_score = float((needle @ centered) / (np.linalg.norm(needle)*np.linalg.norm(centered)))
        self.assertAlmostEqual(pr_score, .900000, places=6)
        self.assertAlmostEqual(direct_scores(objects.bank, glyph)['artillery'], .899999, delta=2e-6)
        over = np.clip(np.rint(.7*template + 55 + 16.24*noise), 0, 255).astype(np.uint8)
        self.assertEqual(accepted(direct_scores(objects.bank, over)), 'artillery')
        flat = np.full((32, 32), 248, np.uint8)
        almost_flat = flat.copy()
        almost_flat[0, 0] -= 1
        for crop in (glyph, over, flat, almost_flat):
            expected = direct_scores(objects.bank, crop)
            with patch.object(cv2, 'matchTemplate', wraps=cv2.matchTemplate) as match:
                actual = objects._candidate_scores(crop)
            self.assertEqual(match.call_count, len(TYPES))
            self.assertEqual(actual, expected)
            self.assertEqual(accepted(actual), accepted(expected))

        # A constant template has its own OpenCV convention (score 1).
        bank = combat_templates(TYPES, cv2.IMREAD_GRAYSCALE)
        bank['artillery'] = np.full_like(bank['artillery'], 248)
        objects = Objects(bank)
        self.assertEqual(objects._candidate_scores(flat), direct_scores(objects.bank, flat))
        self.assertEqual(objects._candidate_scores(flat)['artillery'], 1.0)

    def test_margin_boundary_and_fast_negative_path(self):
        bank = combat_templates(TYPES, cv2.IMREAD_GRAYSCALE)
        glyph = normalized(bank['artillery'])
        noise = np.random.default_rng(1).normal(size=glyph.shape)
        for amount in (26., 28.):
            variant = np.clip(np.rint(glyph + amount*noise), 0, 255).astype(np.uint8)
            bank['tank'] = np.pad(variant, 2)
            objects = Objects(bank)
            expected = direct_scores(objects.bank, glyph)
            self.assertLess(abs(expected['artillery'] - expected['tank'] - .12), .02)
            with patch.object(cv2, 'matchTemplate', wraps=cv2.matchTemplate) as match:
                self.assertEqual(objects._candidate_scores(glyph), expected)
            self.assertEqual(match.call_count, len(TYPES))
        objects = Objects(combat_templates(TYPES, cv2.IMREAD_GRAYSCALE))
        rng = np.random.default_rng(2)
        rejected = 0
        for _ in range(64):
            crop = rng.integers(0, 256, (32, 32), dtype=np.uint8)
            expected = direct_scores(objects.bank, crop)
            actual = objects._candidate_scores(crop)
            self.assertEqual(accepted(actual), accepted(expected))
            rejected += actual is None
        self.assertGreater(rejected, 0)

    def test_four_pass_conflict_and_deduplication(self):
        rng = np.random.default_rng(3)
        frame = np.full((720, 140), 180, np.uint8)
        core = rng.integers(4, 55, (24, 24), dtype=np.uint8)
        outer = np.full((36, 36), 70, np.uint8)
        stamp(outer, core, 6, 6)
        frame[19:57, 19:57] = 80
        stamp(frame, outer, 20, 20)
        stamp(frame, core, 78, 60)
        image = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        bank = {name: rng.integers(0, 255, (30, 30), dtype=np.uint8) for name in TYPES}
        bank.update(infantry=core, tank=outer)
        objects = Objects(bank)
        self.assertEqual(accepted(direct_scores(objects.bank, normalized(core))), 'infantry')
        self.assertEqual(accepted(direct_scores(objects.bank, normalized(outer))), 'tank')
        with patch.object(objects, '_candidate_scores', side_effect=lambda crop: direct_scores(objects.bank, crop)):
            expected = objects.inspect(image)
        with patch.object(cv2, 'connectedComponentsWithStats',
                          wraps=cv2.connectedComponentsWithStats) as components:
            actual = objects.inspect(image)
        for call, threshold in zip(components.call_args_list, (65, 75, 85, 55), strict=True):
            np.testing.assert_array_equal(call.args[0], frame < threshold)
        self.assertEqual(actual, expected)
        self.assertEqual([(r['box'], r['type'], r['plate_threshold']) for r in actual],
                         [([78, 60, 24, 24], 'infantry', 65)])


class GuardChecks(unittest.TestCase):
    def test_uncached_equivalence_and_lru(self):
        bank = combat_templates(('guard_unit', 'guard_hq'), cv2.IMREAD_COLOR)
        guards = Guards(bank)

        def uncached(height):
            scale = height / 720
            for name, template in guards.bank.items():
                variants = []
                for factor in (.9, 1., 1.1):
                    h, w = template.shape
                    needle = cv2.resize(template, (round(w*scale*factor), round(h*scale*factor)))
                    variants.append(needle)
                    if name == 'guard_hq':
                        variants.append(cv2.flip(needle, 1))
                yield name, variants

        rng = np.random.default_rng(4)
        for height in (540, 720, 721, 900):
            scale = height / 720
            box = (40, 80, 38, 48)
            x, y, w, _ = box
            plain = rng.integers(60, 78, (height, 240), dtype=np.uint8)
            for name, variants in uncached(height):
                positive = plain.copy()
                point = [x+w+round(3*scale), y+2]
                stamp(positive, variants[-1], *point)
                for gray, verified in ((positive, True), (plain, True), (plain, False)):
                    frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                    with patch.object(guards, '_variants_for', side_effect=uncached):
                        expected = guards.inspect(frame, box, {'gray': gray}, verified)
                    self.assertEqual(guards.inspect(frame, box, {'gray': gray}, verified), expected)
                    if gray is positive:
                        self.assertEqual(expected['state'], 'guard' if name == 'guard_unit' else 'protected')
                        self.assertEqual(expected['at'], point)
                    elif verified:
                        self.assertEqual(expected['state'], 'clear')
                        self.assertIsNotNone(expected['empty_tab_evidence'])
        fresh = Guards(bank)
        for height in range(720, 720 + MAX_SCALE_CACHE):
            fresh._variants_for(height)
        newest = fresh._variants_for(720)
        fresh._variants_for(720 + MAX_SCALE_CACHE)
        self.assertEqual(len(fresh._scale_cache), MAX_SCALE_CACHE)
        self.assertNotIn(721, fresh._scale_cache)
        self.assertIs(fresh._variants_for(720), newest)
        for _, variants in newest:
            for variant in variants:
                self.assertFalse(variant.flags.writeable)
                with self.assertRaises(ValueError):
                    variant[0, 0] = 0
        self.assertIsNot(guards._variants_for(720), newest)


def original_rectangles(mask, mode, min_w, min_h):
    contours, _ = cv2.findContours(mask, mode, cv2.CHAIN_APPROX_SIMPLE)
    return [cv2.boundingRect(c) for c in contours
            if cv2.boundingRect(c)[2] >= min_w and cv2.boundingRect(c)[3] >= min_h]


def original_candidates(frame):
    def close(mask):
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 11), np.uint8))

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    orange = cv2.inRange(hsv, (5, 80, 80), (35, 255, 255))
    raw = original_rectangles(orange, cv2.RETR_EXTERNAL, 8, 5)
    white = original_rectangles(close(cv2.inRange(gray, 165, 255)), cv2.RETR_EXTERNAL, 12, 8)
    closed = original_rectangles(close(orange), cv2.RETR_LIST, 12, 8)
    overlay_orange = original_rectangles(close(orange), cv2.RETR_EXTERNAL, 12, 8)
    h, w = gray.shape
    left, top = round(.75*w), round(.45*h)
    dim = []
    for threshold in (80, 145):
        roi = cv2.inRange(gray[top:round(.82*h), left:], threshold, 255)
        dim.extend((left+x, top+y, bw, bh) for x, y, bw, bh in
                   original_rectangles(close(roi), cv2.RETR_LIST, 12, 8)
                   if bw <= .4*h and bh <= .12*h)
    return raw, white, closed, overlay_orange, dim


def page_fixtures():
    names = ('defeat_banner', 'defeat_btn', 'victory_btn', 'mulligan_ok_btn', 'mulligan_ok_btn_compact',
             'end_turn_btn', 'end_turn_btn_white', 'opponent_compact', 'opponent_standard',
             'queue_cancel', 'home_play', 'home_tasks', 'home_play_selected', 'battle_selected',
             'training_unselected', 'detail_start')
    rng = np.random.default_rng(5)
    bank = {name: cv2.cvtColor(rng.integers(170, 256, (38, 60), dtype=np.uint8),
                               cv2.COLOR_GRAY2BGR) for name in names}
    bank['victory_btn'][:, :, 0] = 20
    bank['victory_btn'][:, :, 1] = rng.integers(85, 133, (38, 60), dtype=np.uint8)
    bank['victory_btn'][:, :, 2] = 225
    for w, h in SIZES:
        frame = np.full((h, w, 3), 30, np.uint8)
        low = scaled_stamp(frame, bank['home_play'], .8, 40, 45)
        scaled_stamp(frame, bank['home_play'], 1.3, 390, 135)
        scaled_stamp(frame, bank['home_tasks'], .8, 165, 235)
        frame[320:338, 150:169] = frame[320:338, 174:193] = (20, 110, 225)
        frame[324:334, 154:165] = 30  # Enclosed orange contour, RETR_LIST only.
        frame[h//2:h//2+16, w-78:w-48] = 111  # Dim, not white.
        yield bank, frame, low


class PageChecks(unittest.TestCase):
    def test_separate_contours_scale_order_and_semantic_outputs(self):
        def no_ocr(*args):
            self.fail('synthetic templates should resolve the page without OCR')

        for bank, frame, low in page_fixtures():
            with self.subTest(size=frame.shape[:2]):
                features = FrameFeatures(frame)
                raw, white, closed, overlay_orange, dim = original_candidates(frame)
                self.assertTrue(white and dim and set(closed) - set(overlay_orange))
                self.assertNotEqual(raw, closed)
                reference = Detector(bank, 'filtered', refine=True)
                reference.text_boxes = white + closed + dim
                expected = {name: reference.match(features.get('gray'), name) for name in bank}
                self.assertEqual(expected['home_play']['factor'], .8)
                self.assertEqual(expected['home_play']['bounds'], low)
                self.assertGreater(expected['home_play']['score'], .93)
                for supplied in (None, features):
                    detector = Detector(bank, 'filtered', refine=True)
                    observed = detector.observe(frame, supplied)
                    self.assertEqual(observed['state'], 'home')
                    self.assertEqual(observed['evidence'], expected)
                    self.assertEqual(observed['orange_candidates_source'], list(map(list, raw)))
                    self.assertEqual(detector.text_boxes, white + closed + dim)
                    self.assertEqual([key[-1] for key in detector.scaled if key[0] == 'defeat_banner'],
                                     [.8, .9, 1., 1.1, 1.2, 1.3, 1.4])

                fast = FastPage(no_ocr, bank, clock=lambda: 0.)
                self.assertEqual(fast.observe(frame)['state'], 'home')
                self.assertEqual(fast.observe(frame)['path'], 'current_home_controls')
                result_frame = frame.copy()
                placed = scaled_stamp(result_frame, bank['victory_btn'], .8, 240, 106)
                features = FrameFeatures(result_frame)
                _, white, _, orange, _ = original_candidates(result_frame)
                reference = Detector(bank, 'filtered', refine=True)
                expected = {}
                for name in ('defeat_banner', 'defeat_btn', 'victory_btn'):
                    reference.text_boxes = orange if name == 'victory_btn' else white
                    expected[name] = reference.match(features.get('gray'), name)
                result = fast.observe(result_frame, features)
                self.assertEqual(result['state'], 'result_victory')
                self.assertEqual(result['path'], 'local_label_result_override')
                self.assertEqual(result['evidence'], expected)
                self.assertEqual(result['evidence']['victory_btn']['bounds'], placed)


if __name__ == '__main__':
    unittest.main()
