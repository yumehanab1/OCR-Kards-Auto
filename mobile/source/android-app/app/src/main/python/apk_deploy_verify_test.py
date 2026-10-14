"""Read-only regressions from exact ranked frames and reviewed row snapshots.

Snapshot tests run before the core is extracted in the device self-check.
SavedFrameBoundaryTests additionally runs the real core row observers offline.
All mutated scenes below are synthetic negatives, not claimed live sessions.
"""
import copy
import hashlib
import json
from pathlib import Path
import unittest

import cv2
import numpy as np

import apk_deploy_verify as verify

FIXTURES = Path(__file__).resolve().parent / 'deploy-verify-fixtures'
BADGE = {'kind': 'unit', 'state': 'orange', 'apk_availability': {
    'allowed': True, 'basis': 'orange_unit_geometry_v1'}}


def fixtures():
    provenance = json.loads((FIXTURES / 'provenance.json').read_text(encoding='utf-8'))
    images, observations = [], []
    for item in provenance['fixtures']:
        raw = (FIXTURES / item['file']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise AssertionError('fixture hash mismatch: ' + item['file'])
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if frame is None or frame.shape != (720, 1280, 3):
            raise AssertionError('fixture image missing: ' + item['file'])
        images.append(frame)
        observations.append(item['observation'])
    return images, observations


class DeployBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images, cls.snapshots = fixtures()

    def setUp(self):
        self.frames = [frame.copy() for frame in self.images]
        self.rows = copy.deepcopy(self.snapshots)

    def inspect(self, badge=None, target=(1000, 505)):
        iterator = iter(self.rows)
        return verify.inspect_pair(*self.frames, badge=BADGE if badge is None else badge,
                                   target=target, observer=lambda frame: next(iterator))

    def test_real_pixel_pair_has_persistent_new_outer_bomber(self):
        original = [frame.copy() for frame in self.frames]
        result = self.inspect()
        self.assertTrue(result['confirmed'], result)
        self.assertEqual((result['before_support'], result['after_support']), (3, 4))
        self.assertEqual(result['new_unit'], (4, 'bomber'))
        self.assertEqual(result['support_motion'], 0)
        self.assertFalse(result['selected_identity_verified'])
        self.assertTrue(all(np.array_equal(a, b) for a, b in zip(original, self.frames)))

    def test_enemy_animation_cannot_erase_stable_friendly_gain(self):
        self.frames[2][120:260, 500:800] = (255, 255, 255)
        self.assertTrue(self.inspect()['confirmed'])

    def test_swallowed_drag_and_enemy_only_change_never_establish_gain(self):
        for item in self.rows[1:]:
            item.update(cards=copy.deepcopy(self.rows[0]['cards']), hq=self.rows[0]['hq'])
        self.frames[1][425:590, 200:1060] = self.frames[0][425:590, 200:1060]
        self.frames[2][425:590, 200:1060] = self.frames[0][425:590, 200:1060]
        self.frames[2][120:260, 500:800] = (255, 255, 255)
        self.assertFalse(self.inspect()['confirmed'])

    def test_consumed_order_hand_change_is_not_unit_evidence(self):
        for item in self.rows[1:]:
            item.update(cards=copy.deepcopy(self.rows[0]['cards']), hq=self.rows[0]['hq'])
        self.frames[1][595:720] = 0
        self.frames[2][595:720] = 0
        result = self.inspect()
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['reason'], 'persistent_exactly_one_unit_gain_missing')

    def test_order_or_unknown_source_even_with_new_unit_cannot_confirm(self):
        for updates in ({'kind': 'order'}, {'kind': 'unknown'}, {'state': 'gray'},
                        {'apk_availability': {'allowed': True}},
                        {'apk_availability': {'allowed': False, 'basis': 'orange_unit_geometry_v1'}}):
            with self.subTest(updates=updates):
                result = self.inspect(badge=dict(BADGE, **updates))
                self.assertFalse(result['confirmed'])
                self.assertEqual(result['reason'], 'source_unit_approval_missing')

    def test_choice_modal_or_card_animation_refuses_even_with_gain(self):
        for key, value in (('choice_modal', True), ('transition', 'card_overlay')):
            with self.subTest(key=key):
                self.rows = copy.deepcopy(self.snapshots)
                self.rows[2][key] = value
                self.assertEqual(self.inspect()['reason'], 'transition_or_choice_modal')

    def test_missing_own_button_without_positive_opponent_pair_refuses(self):
        self.rows[2]['opponent']['present'] = False
        self.assertEqual(self.inspect()['reason'], 'positive_opponent_label_pair_missing')

    def test_unit_disappearing_on_second_observation_refuses(self):
        self.rows[2]['cards'].pop()
        self.assertEqual(self.inspect()['reason'], 'persistent_exactly_one_unit_gain_missing')

    def test_support_animation_refuses_even_if_detector_keeps_same_slots(self):
        self.frames[2][470:520, 300:950] = (255, 255, 255)
        self.assertEqual(self.inspect()['reason'], 'support_pixels_still_moving')

    def test_support_geometry_animation_refuses(self):
        self.rows[2]['cards'][-1]['cx'] += 5
        self.assertEqual(self.inspect()['reason'], 'support_geometry_still_moving')

    def test_existing_unit_type_change_cannot_be_counted_as_deployment(self):
        self.rows[1]['cards'][1]['type'] = self.rows[2]['cards'][1]['type'] = 'infantry'
        self.assertEqual(self.inspect()['reason'], 'existing_support_units_not_preserved')

    def test_wrong_dispatched_outer_side_refuses(self):
        self.assertEqual(self.inspect(target=(280, 505))['reason'], 'new_unit_not_on_dispatched_outer_side')

    def test_unclear_row_or_invalid_pixels_refuse(self):
        self.rows[2]['row_reason'] = 'support_unit_evidence_incomplete'
        self.assertEqual(self.inspect()['reason'], 'support_row_incomplete')
        self.frames[2] = None
        self.assertEqual(self.inspect()['reason'], 'invalid_frame')


class SavedFrameBoundaryTests(unittest.TestCase):
    """Needs a scratch core on sys.path; intentionally separate from self_check."""
    def test_actual_core_observers_confirm_exact_ranked_390_392_393(self):
        images, _ = fixtures()
        result = verify.inspect_pair(*images, badge=BADGE, target=(1000, 505))
        self.assertTrue(result['confirmed'], result)
        self.assertEqual(result['new_unit'], (4, 'bomber'))

    def test_actual_core_observer_rejects_no_gain_with_enemy_turn_label(self):
        images, _ = fixtures()
        for image in images[1:]:
            image[425:590, 200:1060] = images[0][425:590, 200:1060]
        result = verify.inspect_pair(*images, badge=BADGE, target=(1000, 505))
        self.assertFalse(result['confirmed'], result)

    def test_actual_core_observer_rejects_choice_overlay(self):
        images, _ = fixtures()
        images[2][120:420, 200:1050] = 220
        result = verify.inspect_pair(*images, badge=BADGE, target=(1000, 505))
        self.assertFalse(result['confirmed'], result)
        self.assertEqual(result['reason'], 'transition_or_choice_modal')


if __name__ == '__main__':
    unittest.main()
