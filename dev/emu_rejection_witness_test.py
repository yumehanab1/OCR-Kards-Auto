"""Pure/fixture tests, with opt-in read-only replay of the original local PNGs.

From the PC repo: python/python.exe -B dev/emu_rejection_witness_test.py --replay -v
Without --replay only synthetic cases run; the logs never leave the machine.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import unittest

import cv2
import numpy as np

import emu_rejection_witness as witness

_REPLAY = False
_LOGS = Path(__file__).resolve().parents[1] / 'logs'
_REBOOT = _LOGS / 'pc_emu_b_20261119_reboot_0224'
_LIVE = _REBOOT / 'live-01'
_OLD = _LOGS / 'pc_emu_b_20261119_0128'
_E = _OLD / 'battle-E-resolved-deploy'
_INK = (180, 194, 196)


def _banner():
    frame = np.zeros((720, 1280, 3), np.uint8)
    frame[300:303, 450:830] = (130, 142, 146)
    frame[379:382, 450:830] = (129, 139, 146)
    strokes = witness._GLYPH_MASK.repeat(2, axis=0).repeat(2, axis=1)
    frame[310:374, 204:1076][strokes] = _INK
    return frame


class RejectionWitnessTests(unittest.TestCase):
    def test_veto_schema_and_immutable_input(self):
        frame = _banner()
        before = frame.copy()
        frame.setflags(write=False)
        evidence = witness.deployment_rejection_witness(frame)
        self.assertEqual(evidence, {
            'veto': True,
            'stop_reason': 'deploy_rejected_insufficient_kredits',
            'label': '指挥点数不足，无法使用此卡牌',
            'box': (204, 310, 1076, 374),
            'proof': 'reviewed_zh_insufficient_kredits_banner',
            'glyph_iou': (1.,) * 14,
            'rail_coverage': (1., 1.),
        })
        self.assertEqual(json.loads(json.dumps(evidence))['veto'], True)
        np.testing.assert_array_equal(frame, before)

    def test_reject_invalid_frame_contract(self):
        for frame in (None, 'read-0023.png', np.zeros((720, 1280), np.uint8),
                      np.zeros((720, 1280, 4), np.uint8), np.zeros((720, 1280, 3), np.float32),
                      np.zeros((540, 960, 3), np.uint8)):
            with self.subTest(kind=type(frame).__name__, shape=getattr(frame, 'shape', None)):
                self.assertIsNone(witness.deployment_rejection_witness(frame))

    def test_reject_missing_rail_or_dark_gutter(self):
        for y in (300, 379):
            frame = _banner()
            frame[y:y+3] = 0
            self.assertIsNone(witness.deployment_rejection_witness(frame))
        for y in (304, 374):
            frame = _banner()
            frame[y:y+5, 496:784] = (55, 55, 55)
            self.assertIsNone(witness.deployment_rejection_witness(frame))

    def test_reject_rails_alone_or_solid_text_band(self):
        for fill in (0, _INK):
            frame = _banner()
            frame[310:374, 204:1076] = fill
            self.assertIsNone(witness.deployment_rejection_witness(frame))

    def test_reject_every_single_missing_character_including_comma(self):
        starts = (*witness._GLYPH_STARTS, witness._GLYPH_MASK.shape[1])
        for i, (a, b) in enumerate(zip(starts, starts[1:])):
            with self.subTest(character=witness.LABEL[i], index=i):
                frame = _banner()
                frame[310:374, 204+2*a:204+2*b] = 0
                self.assertIsNone(witness.deployment_rejection_witness(frame))

    def test_reject_damaged_and_replaced_character(self):
        damaged = _banner()
        damaged[310:327, 826:886] = 0
        replaced = _banner()
        replaced[310:374, 826:886] = replaced[310:374, 702:762]
        for frame in (damaged, replaced):
            self.assertIsNone(witness.deployment_rejection_witness(frame))

    def test_reject_full_phrase_as_part_of_longer_text(self):
        for shift in (-48, 876):
            with self.subTest(shift=shift):
                frame = _banner()
                frame[310:374, 204+shift:244+shift] = frame[310:374, 204:244]
                self.assertIsNone(witness.deployment_rejection_witness(frame))

    def test_reject_wrong_ink_or_rail_color(self):
        for color in ((0, 142, 225), (196, 196, 196), (196, 182, 177)):
            with self.subTest(color=color):
                frame = _banner()
                text = frame[310:374, 204:1076]
                text[(text == _INK).all(axis=2)] = color
                self.assertIsNone(witness.deployment_rejection_witness(frame))
        frame = _banner()
        frame[300:303, 450:830] = (0, 130, 150)
        self.assertIsNone(witness.deployment_rejection_witness(frame))

    def test_reject_wrong_position_and_text_rail_misalignment(self):
        base = _banner()
        for dx, dy in ((7, 0), (0, 7), (-21, -13)):
            with self.subTest(dx=dx, dy=dy):
                self.assertIsNone(witness.deployment_rejection_witness(
                    np.roll(base, (dy, dx), axis=(0, 1))))
        base[310:374] = np.roll(base[310:374], 8, axis=1)
        self.assertIsNone(witness.deployment_rejection_witness(base))


class OriginalFrameTests(unittest.TestCase):
    def setUp(self):
        if not _REPLAY:
            self.skipTest('pass --replay to require original local frame fixtures')

    def _events(self, directory):
        return [json.loads(line) for line in (directory / 'events.jsonl').read_text(
            encoding='utf-8').splitlines()]

    def _read_frame(self, directory, name, expected_sha=None):
        raw = (directory / name).read_bytes()
        if expected_sha is not None:
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected_sha, name)
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame, name)
        self.assertEqual(frame.shape, (720, 1280, 3), name)
        return frame

    def test_rejection_frames_and_normal_board_after_toast(self):
        events = self._events(_LIVE)
        dispatch, = [e for e in events if e['event'] == 'dispatch_attempt' and e['attempt'] == 3]
        post = [e for e in events if e['event'] == 'sample' and e['mode'] == 'verify_deploy'
                and e['attempt'] == 3]
        terminal, = [e for e in events if e['event'] == 'terminal_frame']
        self.assertEqual([e['frame'] for e in post], list(range(23, 32)))
        self.assertNotEqual(post[0]['sha256'], post[1]['sha256'])  # distinct captures of one episode
        self.assertEqual(terminal['sha256'], post[-1]['sha256'])  # duplicate, not independent proof
        for e in [*dispatch['evidence'], *post, terminal]:
            with self.subTest(png=e['png']):
                frame = self._read_frame(_LIVE, e['png'], e['sha256'])
                result = witness.deployment_rejection_witness(frame)
                if e['png'] in ('read-0023.png', 'read-0024.png'):
                    self.assertIsNotNone(result)
                    self.assertTrue(result['veto'])
                    self.assertEqual(result['label'], '指挥点数不足，无法使用此卡牌')
                    self.assertEqual(result['stop_reason'], 'deploy_rejected_insufficient_kredits')
                    self.assertEqual(result['box'], (204, 310, 1076, 374))
                else:
                    self.assertIsNone(result)

    def test_other_real_phases_do_not_trigger(self):
        events = self._events(_LIVE)
        current = [e for e in events if e.get('png') in (
            'handoff-1.png', 'handoff-2.png', 'entry.png', 'read-0010.png', 'read-0011.png')]
        self.assertEqual(len(current), 5)  # new-game own turn and positive opponent samples
        for e in current:
            with self.subTest(png=e['png']):
                frame = self._read_frame(_LIVE, e['png'], e['sha256'])
                self.assertIsNone(witness.deployment_rejection_witness(frame))
        for name in ('01-after-stop.png', '02-open-modes.png', '04-japan-deck.png', '06-opening-actual.png'):
            with self.subTest(png=name):
                self.assertIsNone(witness.deployment_rejection_witness(self._read_frame(_OLD, name)))

    def test_old_e_target_selection_is_not_this_rejection(self):
        selected = [e for e in self._events(_E) if (e['event'] == 'verification_sample'
                    and e['attempt'] == 4) or e['event'] == 'terminal_frame']
        self.assertEqual([e['frame'] for e in selected], [*range(34, 41), 40])
        for e in selected:
            with self.subTest(png=e['png']):
                frame = self._read_frame(_E, e['png'], e['sha256'])
                self.assertIsNone(witness.deployment_rejection_witness(frame))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--replay', action='store_true')
    options, remaining = parser.parse_known_args()
    _REPLAY = options.replay
    unittest.main(argv=[__file__, *remaining])
