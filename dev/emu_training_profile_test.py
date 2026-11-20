"""Offline checks for the supervised first-turn recognition profile (no ADB)."""
import argparse
import json
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

from emu_training_profile import UnitTitles, TrainingVision

ROOT = Path(__file__).resolve().parents[1]
MOBILE = CAPTURE = OLD = None


class TitlesTest(unittest.TestCase):
    def setUp(self):
        rows = [{'json': {'title': {'zh-Hans': name}, 'type': typ}}
                for name, typ in [('样本步兵团', 'infantry'), ('定向指令牌', 'order'),
                                  ('同名测试牌', 'tank'), ('同名测试牌', 'order')]]
        self.words = []
        self.rec = UnitTitles(rows, lambda _: self.words)
        self.frame = np.random.default_rng(2).integers(0, 255, size=(720,1280,3), dtype=np.uint8)
        self.item = [{'anchor': (500,625), 'grab': (525,650)}]

    def read(self, name, *, x=328, conf=.997):
        self.words[:] = [dict(text=name, x=x, y=39, cx=x+28, cy=48, w=56, h=18, conf=conf)]
        return self.rec.on_frame(self.frame, self.item)

    def test_exact_name_and_pixel_recheck(self):
        self.assertEqual(self.read('样本步兵团'), {(500,625): '样本步兵团'})
        self.words.clear()
        self.assertTrue(self.rec.on_frame(self.frame.copy(), self.item))
        self.frame[619:637,528:584] = 0
        self.assertFalse(self.rec.on_frame(self.frame, self.item))

    def test_order_and_name_ambiguity_never_qualify(self):
        for n in ('定向指令牌', '同名测试牌', '样本步', '样本步兵队'):
            self.rec.last = None
            self.assertFalse(self.read(n), n)

    def test_wrong_location_and_low_confidence(self):
        self.assertFalse(self.read('样本步兵团', x=448))
        self.rec.last = None
        self.assertFalse(self.read('样本步兵团', conf=.74))

    def test_cost_must_be_on_this_anchor(self):
        self.assertTrue(self.read('1样本步兵团', x=292))
        self.rec.samples.clear(); self.rec.last = None
        self.assertFalse(self.read('1样本步兵团', x=339))


class LocalCaptureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if MOBILE is None or CAPTURE is None or OLD is None:
            raise unittest.SkipTest('supply local --mobile-root, --capture and --previous-capture for recorded PNGs')
        sys.path.insert(0, str(ROOT/'src'))
        from hover_card_reader import _ocr
        cls.frames = [cv2.imread(str(CAPTURE/f'first-{i}.png')) for i in (1,2)]
        cls.v = TrainingVision(MOBILE, cls.frames, card_db=ROOT/'card_db/kards_data.json', ocr=_ocr)

    def test_named_deployment_on_independent_live_handoff(self):
        samples = [cv2.imread(str(CAPTURE/'live-01'/f'handoff-{i}.png')) for i in (1,2)]
        for frame in samples:
            r = self.v.observe(frame)
            self.assertEqual(r.state, 'own')
            self.assertEqual(r.deploy.target, (786,505))
            chosen = [h['exact_unit_title'] for h in r.evidence['hand'] if h.get('grab') == list(r.deploy.origin)]
            self.assertEqual(chosen, ['骑兵第十五联队'])

    def test_known_empty_patch_not_reusable_over_unit_or_hq(self):
        surface = self.v.drop
        self.assertTrue(surface.slot_matches(self.frames[1], (728,435,844,580)))
        self.assertFalse(surface.slot_matches(self.frames[1], (583,435,699,580)))
        occupied = self.frames[0].copy()
        occupied[435:580,728:844] = self.frames[1][435:580,580:696]
        self.assertFalse(surface.slot_matches(occupied, (728,435,844,580)))

    def test_real_new_enemy_pair_and_missing_glyph(self):
        for n in (1,2):
            frame = cv2.imread(str(CAPTURE/'live-01'/f'a002-post-{n}.png'))
            r = self.v.observe(frame, mode='end_only')
            self.assertEqual(r.state, 'opponent')
            self.assertIsNone(r.end)
        frame[490:540,1102:1191] = 0
        self.assertFalse(self.v.opponent_turn(frame)['present'])

    def test_real_nonbattle_veto_and_no_false_enemy(self):
        for name in ('01-after-stop','03-training-tab','04-japan-deck','06-opening-actual'):
            r = self.v.observe(cv2.imread(str(OLD/f'{name}.png')))
            self.assertIsNone(r.end); self.assertIsNone(r.deploy)
        self.assertFalse(self.v.opponent_turn(self.frames[0])['present'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    for arg in ('--mobile-root','--capture','--previous-capture'):
        parser.add_argument(arg, type=Path)
    args, other = parser.parse_known_args()
    MOBILE, CAPTURE, OLD = args.mobile_root, args.capture, args.previous_capture
    unittest.main(argv=[__file__, *other])
