"""Offline tests for Route B fast Vision. No transport, including with real PNGs."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from emu_route_b_fast_vision import adapt
from emu_route_b_readonly import description, load_profile, sha256

SESSION = None
SEQUENCES = (66, 68, 69, 70, 71)
TANK = '九三式装甲车'


class CountingCv:
    def __init__(self, counts):
        self.counts = counts

    def __getattr__(self, attr):
        if attr not in ('cvtColor', 'connectedComponentsWithStats'):
            return getattr(cv2, attr)

        def measured(*args, **kwargs):
            self.counts[attr] += 1
            return getattr(cv2, attr)(*args, **kwargs)
        return measured


class FrameReuseTests(unittest.TestCase):
    def setUp(self):
        self.calls = Counter()
        self.frame = np.zeros((20, 20, 3), np.uint8)
        self.frame[10:, :] = 100
        self.other = self.frame.copy()
        self.other[:] = 255
        self.ort_calls = []
        calls = self.calls

        class OriginalVision:
            def __init__(self, refs):
                self.board = ModuleType('fake_board')
                self.hand = ModuleType('fake_hand')
                self.available = ModuleType('fake_available')
                self.native_hand = ModuleType('fake_native')
                self.right = SimpleNamespace(regular=SimpleNamespace(), opening=SimpleNamespace())
                for module in (self.board, self.hand, self.available, self.native_hand):
                    module.cv2 = CountingCv(calls)

                def transition(frame, *, extra=False):
                    calls['transition'] += 1
                    return (int(frame[0, 0, 0]), extra)

                def front(frame):
                    calls['front'] += 1
                    return self.board.board_transition_reason(frame)

                def plates(frame):
                    calls['plates'] += 1
                    return self.available.cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2]

                self.board.board_transition_reason = transition
                self.board.frontline_state = front
                self.available._geometry_plates = plates
                self.board._hsv = lambda f: self.board.cv2.cvtColor(f, cv2.COLOR_BGR2HSV)

            def observe(self, frame, *, mode):
                a = self.board.frontline_state(frame)
                assert a == self.board.frontline_state(frame) == self.board.board_transition_reason(frame)
                hsv = self.native_hand.cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                v = self.available._geometry_plates(frame)
                assert np.array_equal(v, self.available._geometry_plates(frame))
                mask = (v < 90).astype(np.uint8)
                ca = self.native_hand.cv2.connectedComponentsWithStats(mask, 8)
                cb = self.available.cv2.connectedComponentsWithStats(mask.copy(), 8)
                assert np.array_equal(ca[1], cb[1]) and np.array_equal(hsv[:, :, 2], v)
                if mode == 'different_inputs':
                    x = self.available.cv2.connectedComponentsWithStats(1-mask, 8)
                    assert not np.array_equal(ca[1], x[1])
                    assert self.board.board_transition_reason(frame, extra=True)[1]
                    assert self.board.board_transition_reason(self.other)[0] == 255
                    self.native_hand.cv2.cvtColor(frame.copy(), cv2.COLOR_BGR2HSV)
                if mode == 'raise':
                    raise RuntimeError('test observation failure')
                return a

            def credits(self, frame):
                raise AssertionError('old HUD cache consulted')

        self.old = OriginalVision([])
        cls = adapt(OriginalVision, lambda self, f: self._ocr(f))
        self.new = cls([], ocr=lambda roi: self.ort_calls.append(roi) or int(roi[0, 0, 0]))
        self.new.other = self.other

    def test_exact_work_shared_without_substituting_detector_rules(self):
        self.assertEqual(self.old.observe(self.frame, mode='plan'), self.new.observe(self.frame))
        self.assertEqual(self.calls, {'front': 3, 'transition': 4, 'plates': 3,
                                      'cvtColor': 4, 'connectedComponentsWithStats': 3})

    def test_same_object_next_observation_recomputes(self):
        self.assertEqual(self.new.observe(self.frame), (0, False))
        self.frame[0, 0] = 255
        self.assertEqual(self.new.observe(self.frame), (255, False))
        self.assertEqual(self.calls['front'], 2)
        self.assertEqual(self.calls['plates'], 2)
        self.assertEqual(self.calls['connectedComponentsWithStats'], 2)

    def test_different_mask_frame_and_parameters_are_not_reused(self):
        self.new.observe(self.frame, mode='different_inputs')
        self.assertEqual(self.calls['transition'], 3)
        self.assertEqual(self.calls['cvtColor'], 2)
        self.assertEqual(self.calls['connectedComponentsWithStats'], 2)

    def test_failed_observation_does_not_leak_scope(self):
        with self.assertRaisesRegex(RuntimeError, 'observation failure'):
            self.new.observe(self.frame, mode='raise')
        self.new.board.board_transition_reason(self.frame)
        self.new.board.board_transition_reason(self.frame)
        self.assertEqual(self.calls['transition'], 3)
        self.new.observe(self.frame)
        self.assertEqual(self.calls['transition'], 4)

    def test_no_legacy_credit_or_title_cache(self):
        self.assertIs(self.new.right.regular.ocr, self.new._ocr)
        self.assertIs(self.new.right.opening.ocr, self.new._ocr)
        self.assertEqual(self.new.credits(self.frame), 0)
        self.frame[0, 0] = 2
        self.assertEqual(self.new.credits(self.frame), 2)
        self.assertEqual(len(self.ort_calls), 2)


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if SESSION is None:
            raise unittest.SkipTest('pass --session-root for real replay and bound-Pilot guard tests')
        cls.b, cls.s, cls.session = load_profile(SESSION)
        cls.old = cls.s.Vision([f.pixels for f in cls.session.refs])
        cls.new = adapt(cls.s.Vision, cls.b.Vision.credits)([f.pixels for f in cls.session.refs])
        cls.events = {row['frame']: row for row in map(json.loads, (SESSION / 'battle-01/events.jsonl').read_text('utf-8').splitlines())
                      if row['event'] == 'discarded_plan'}
        cls.proposals = {}
        for i in SEQUENCES:
            event = cls.events[i]
            data = (SESSION / 'battle-01' / event['png']).read_bytes()
            if sha256(data) != event['sha256']:
                raise AssertionError(event['png'] + ' did not match the original journal')
            cls.proposals[i] = cls.b.host.Frame.read(i, event['capture_monotonic'], data, cls.session.binding)

    def pixels(self, path):
        return self.b.host.decode_png(path.read_bytes())[0]

    def assertEquivalent(self, frame, *, mode='plan'):
        a, b = (v.observe(frame, mode=mode) for v in (self.old, self.new))
        self.assertEqual(description(a), description(b))
        return b

    def test_five_reviewed_turn_five_frames_and_full_journal_evidence(self):
        for i, frame in self.proposals.items():
            with self.subTest(frame=i):
                rd = self.assertEquivalent(frame.pixels)
                logged = self.events[i]['observation']
                self.assertEqual(json.loads(json.dumps(rd.brief())), logged)
                self.assertEqual(rd.support.units, ((1, 'infantry'),))
                self.assertEqual(rd.deploy, self.b.host.Plan('deploy', (903, 667), (855, 505)))
                self.assertEqual(self.b.deploy_witness(rd, rd.deploy), (TANK, 'tank', 1, 5))

    def test_opening_pair_still_accepted_and_himeji_not_tank(self):
        proofs = tuple(self.b.entry_pair(v, *self.session.refs) for v in (self.old, self.new))
        self.assertEqual(*proofs)
        self.assertTrue(proofs[1]['accepted'])
        for frame in self.session.refs:
            rd = self.assertEquivalent(frame.pixels)
            self.assertEqual(self.b.deploy_witness(rd, rd.deploy), ('姬路联队', 'infantry', 1, 1))

    def test_overlay_rejection_opponent_lobby_and_missing_unit_controls(self):
        parent, battle = SESSION.parent, SESSION / 'battle-01'
        replay = [
            (battle/'read-0063.png', 'plan', 'unknown', 'transition:存在中央状态文字横幅'),
            (battle/'read-0064.png', 'plan', 'own', 'own_turn_control_and_board'),
            (battle/'read-0045.png', 'end_only', 'opponent', 'explicit_opponent_and_own_button_absent'),
            (SESSION/'lobby-inspection-1.png', 'plan', 'unknown', 'transition:存在放大卡牌/展示层'),
            (parent/'pc_emu_b_20261119_0128/battle-E-resolved-deploy/v-004-0035.png', 'plan', 'choice', self.b.host.TARGET_SELECTION_PENDING),
            (parent/'pc_emu_b_20261119_reboot_0224/live-01/read-0023.png', 'verify_deploy', 'rejected', self.b.host.REJECTION_REASON),
        ]
        for path, mode, state, reason in replay:
            with self.subTest(path=path.name, mode=mode):
                rd = self.assertEquivalent(self.pixels(path), mode=mode)
                self.assertEqual((rd.state, rd.reason, rd.deploy), (state, reason, None))

    def test_lost_title_and_blocked_support_never_reuse_positive_frame(self):
        frame = self.proposals[66].pixels
        for coords, want in [((625, 695, 888, 1052), 'title'), ((435, 580, 797, 913), 'slot')]:
            with self.subTest(veto=want):
                self.assertIsNotNone(self.assertEquivalent(frame).deploy)
                y0, y1, x0, x1 = coords
                modified = frame.copy()
                modified[y0:y1, x0:x1] = 0
                rd = self.assertEquivalent(modified)
                self.assertIsNone(rd.deploy)

    def test_hidden_available_credits_cannot_inherit_previous_positive(self):
        frame = self.proposals[66].pixels
        self.assertIsNotNone(self.assertEquivalent(frame).deploy)
        modified = frame.copy()
        modified[496:558, 33:87] = 0
        rd = self.assertEquivalent(modified)
        self.assertIsNone(rd.deploy)
        tank, = (item for item in rd.evidence['hand'] if item.get('exact_unit_title') == TANK)
        self.assertEqual((tank['visible_cost'], tank['available'], tank['session_veto']),
                         (1, None, 'visible_cost_or_affordability_not_confirmed'))

    def test_fresh_ocr_each_frame_including_identical_pngs(self):
        real = self.new._ocr
        calls = Counter()

        def ocr(roi):
            calls[roi.shape[:2]] += 1
            return real(roi)

        def mocks(reader):
            return (patch.object(reader, '_ocr', ocr), patch.object(reader.right.regular, 'ocr', ocr),
                    patch.object(reader.right.opening, 'ocr', ocr))

        a, b = (self.proposals[i] for i in (68, 69))
        self.assertEqual(a.png, b.png)
        m1, m2, m3 = mocks(self.new)
        with m1, m2, m3:
            for frame in (a, b):
                self.assertIsNotNone(self.new.observe(frame.pixels).deploy)
        self.assertEqual(calls, {(70, 164): 2, (152, 136): 2})

    def test_original_pair_gate_rejects_single_or_unbound_same_image(self):
        a, b = (self.proposals[i] for i in (68, 69))
        pilot = self.b.Pilot(SimpleNamespace(), self.new, None, None, action_limit=1)
        ar, br = (self.new.observe(f.pixels) for f in (a, b))
        pilot.plan_reads = [(b, br)]
        self.assertFalse(pilot.approve_pair(b, br.deploy))
        pilot.plan_reads = [(a, ar), (b, br)]
        self.assertTrue(pilot.approve_pair(b, br.deploy))  # independent original captures, same pixel bytes
        self.assertFalse(pilot.approve_pair(a, ar.deploy))
        unbound = self.b.host.Frame.read(b.seq, b.started, b.png)
        pilot.plan_reads = [(a, ar), (unbound, br)]
        self.assertFalse(pilot.approve_pair(unbound, br.deploy))

    def test_unchanged_new_battle_and_freshness_boundaries(self):
        self.assertEqual((self.b.PLAN_MAX_AGE, self.b.host.FRESHNESS), (1.65, 2.))
        frame = self.session.refs[0]
        device = SimpleNamespace(capture=lambda: frame)
        journal = SimpleNamespace(event=lambda *args, **kw: None, frame=lambda *args: {})
        pilot = self.b.Pilot(device, self.new, SimpleNamespace(clock=lambda: frame.started + 1.651), journal, action_limit=1)
        _, reading = pilot.read('plan')
        self.assertEqual(reading.reason, 'discard_slow_plan_no_dispatch')
        self.assertEqual(pilot.plan_reads, [])
        pilot.verified['end_turn'] = 1
        pilot.attempts = 1
        with self.assertRaisesRegex(self.b.Halt, 'first_turn_reappeared_after_progress'):
            pilot.read('plan')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--session-root', type=Path)
    opts, rest = parser.parse_known_args()
    SESSION = opts.session_root.resolve() if opts.session_root else None
    unittest.main(argv=[__file__, *rest])
