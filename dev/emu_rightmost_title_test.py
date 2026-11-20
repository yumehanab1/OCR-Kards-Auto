"""Offline only: vetoes at the cropped, rightmost hand title and real-frame replay."""
import argparse
from pathlib import Path
import sys
import unittest
import cv2
import numpy as np
from emu_training_profile import RightmostUnitTitles

CAPTURE = None
TITLE = '35(T)坦克'


class RightmostTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((720,1280,3), np.uint8)
        self.words = [dict(text='35(t) 坦克', conf=.999, x=15, y=13, w=81, h=38, cx=56., cy=32.)]
        self.count = 0
        def ocr(roi):
            self.count += 1
            self.assertEqual(roi.shape, (70,164,3))
            return self.words
        self.reader = RightmostUnitTitles({TITLE}, ocr)
        self.hand = [{'anchor':[859,640], 'grab':[884,665], 'kind':'unit_marker'}]
        self.plates = [dict(cx=864,cy=640)]

    def read(self):
        return self.reader.on_frame(self.frame, self.hand, self.plates)

    def test_visible_exact_single_name_re_read_each_time(self):
        self.assertEqual(self.read(), {(859,640):TITLE})
        self.words[0]['text'] = '35(t)坦'
        self.assertEqual(self.read(), {})
        self.assertEqual(self.count, 2)

    def test_unknown_right_plate_or_right_anchor_blocks_before_ocr(self):
        self.plates.append(dict(cx=890,cy=630)); self.assertFalse(self.read()); self.plates.pop()
        self.hand.append({'anchor':[883,641]}); self.assertFalse(self.read())
        self.assertEqual(self.count, 0)

    def test_no_own_plate_central_or_duplicate_candidate(self):
        self.plates.clear(); self.assertFalse(self.read()); self.plates.append(dict(cx=863,cy=640))
        self.hand.append(dict(self.hand[0])); self.assertFalse(self.read()); self.hand.pop()
        self.hand[0].update(anchor=[391,651],grab=[416,676]); self.assertFalse(self.read())
        self.assertEqual(self.count,0)

    def test_low_confidence_clipped_text_order_or_multiple_words(self):
        for bad in [dict(x=0),dict(y=0),dict(w=155),dict(conf=.92),dict(text='指令')]:
            orig=dict(self.words[0]); self.words[0].update(bad); self.assertFalse(self.read()); self.words[0]=orig
        self.words.append(dict(self.words[0])); self.assertFalse(self.read())

    def test_recorded_rightmost_title_and_occluded_control(self):
        if CAPTURE is None: self.skipTest('pass --capture path to live-04 for independent raw frames')
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
        from hover_card_reader import _ocr
        self.reader = RightmostUnitTitles({TITLE}, _ocr)
        for name in ('handoff-1.png','handoff-2.png','read-0003.png','read-0004.png','terminal.png'):
            self.frame = cv2.imread(str(CAPTURE/name)); self.assertEqual(self.read(), {(859,640):TITLE}, name)
        self.frame[623:693,869:1033] = 0
        self.assertFalse(self.read())


if __name__ == '__main__':
    p = argparse.ArgumentParser(add_help=False); p.add_argument('--capture',type=Path)
    args,rest=p.parse_known_args(); CAPTURE=args.capture
    unittest.main(argv=[__file__,*rest])
