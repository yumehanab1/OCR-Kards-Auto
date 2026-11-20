"""Offline only. Run with --battle-dir to replay the saved original PNGs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import unittest

import cv2
import numpy as np

import emu_board_witness as witness

BATTLE = None


def banner(*, dx=0, dy=0, rails=True):
    frame = np.zeros((720, 1280, 3), np.uint8)
    x0, y0, x1, y1 = witness._BOX
    frame[y0+dy:y1+dy, x0+dx:x1+dx][witness._STROKES] = 211
    if rails:
        for y in (251, 311):
            frame[y+dy:y+dy+2, 580+dx:700+dx] = 211
    return frame


class TargetSelectionWitnessTests(unittest.TestCase):
    def test_prompt_and_common_offset(self):
        for dx, dy in [(0, 0), (-2, 2), (2, -2)]:
            with self.subTest(dx=dx, dy=dy):
                frame = banner(dx=dx, dy=dy)
                frame.setflags(write=False)
                found = witness.target_selection_witness(frame)
                self.assertIsNotNone(found)
                self.assertEqual(found['proof'], 'reviewed_zh_select_target_banner')
                self.assertEqual(found['label'], '选择目标')
                self.assertEqual(found['box'], (563+dx, 262+dy, 717+dx, 301+dy))
                self.assertEqual(found['glyph_iou'], (1.,)*4)

    def test_bad_frame(self):
        for frame in (None, np.empty((720, 1280), np.uint8),
                      np.empty((720, 1280, 4), np.uint8), np.empty((720, 1280, 3), np.float32),
                      np.empty((540, 960, 3), np.uint8)):
            self.assertIsNone(witness.target_selection_witness(frame))

    def test_neither_rails_nor_unrelated_text_are_evidence(self):
        bare = banner(rails=False)
        rails = banner()
        rails[262:301, 563:717] = 0
        rectangles = banner()
        for x in (567, 609, 651, 693):
            rectangles[264:299, x:x+20] = 211
        for frame in (bare, rails, rectangles, np.full_like(rails, 211)):
            self.assertIsNone(witness.target_selection_witness(frame))

    def test_reject_missing_rail(self):
        for y in (251, 311):
            frame = banner()
            frame[y:y+2] = 0
            self.assertIsNone(witness.target_selection_witness(frame))

    def test_reject_partial_or_wrong_glyph(self):
        for s in witness._GLYPHS:
            with self.subTest(glyph=(s.start, s.stop)):
                frame = banner()
                glyph = frame[262:301, 563+s.start:563+s.stop]
                glyph[:13] = 0  # retain the other whole glyphs and both rails
                self.assertIsNone(witness.target_selection_witness(frame))
        frame = banner()
        glyph = frame[262:301, 615:643]
        glyph[:] = glyph[:, ::-1].copy()
        self.assertIsNone(witness.target_selection_witness(frame))

    def test_reject_wrong_position_color_or_partial_alignment(self):
        wrong_color = banner()
        white = wrong_color[:, :, 0] > 0
        wrong_color[white] = (0, 143, 230)
        misaligned = banner()
        rail = misaligned[311:313].copy()
        misaligned[311:313] = 0
        misaligned[317:319] = rail
        for frame in (banner(dx=10), banner(dy=10), wrong_color, misaligned):
            self.assertIsNone(witness.target_selection_witness(frame))

    def test_real_scene(self):
        if BATTLE is None:
            self.skipTest('pass --battle-dir for local frame replay')
        events = [json.loads(line) for line in (BATTLE/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        dispatch, = [e for e in events if e['event'] == 'dispatch_attempt' and e['attempt'] == 4]
        samples = [e for e in events if e['event'] == 'verification_sample' and e['attempt'] == 4]
        terminal, = [e for e in events if e['event'] == 'terminal_frame']
        self.assertEqual([e['frame'] for e in samples], list(range(34, 41)))
        self.assertEqual(terminal['sha256'], samples[-1]['sha256'])  # not an independent positive

        def read_frame(record):
            raw = (BATTLE/record['png']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), record['sha256'])
            return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)

        for e in dispatch['evidence']:
            with self.subTest(png=e['png']):
                self.assertIsNone(witness.target_selection_witness(read_frame(e)))
        for e in [*samples, terminal]:
            with self.subTest(png=e['png']):
                found = witness.target_selection_witness(read_frame(e))
                self.assertIsNotNone(found)
                self.assertEqual(found['label'], '选择目标')
                self.assertEqual(found['box'], (563, 262, 717, 301))
        previous_clean, = [f for e in events if e['event'] == 'effect_verified' and e['attempt'] == 3
                           for f in e['evidence'] if f['png'] == 'a003-post-2.png']
        entry, = [e for e in events if e['event'] == 'entry']
        for e in (previous_clean, entry):
            with self.subTest(png=e['png']):
                self.assertIsNone(witness.target_selection_witness(read_frame(e)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--battle-dir', type=Path)
    options, remaining = parser.parse_known_args()
    BATTLE = options.battle_dir
    unittest.main(argv=[__file__, *remaining])
