"""Fake-core and pixel helpers: no core imports, device, capture or input."""
import types
import time
import unittest
from unittest import mock

import numpy as np
import apk_simple_combat as simple


def unit(x=300, y=410, typ="tank", row="support"):
    return {"type": typ, "row": row, "from": (x + 56, y + 58),
            "card": {"x": x, "y": y, "w": 112, "h": 140, "cx": x + 56, "cy": y + 70},
            "badge": {"x": x, "y": y, "w": 28, "h": 28, "cx": x + 14, "cy": y + 14}}


def paint(frame, actor, value):
    c = actor["card"]
    frame[c["y"]+32:c["y"]+100, c["x"]+8:c["x"]+104] = value


class AttackSampleTests(unittest.TestCase):
    """Faster polling is attack-local and preserves observation rejection gates."""
    def fixture(self, frames):
        self.now, self.sleeps = 0., []
        def sleep(seconds):
            self.sleeps.append(seconds)
            self.now += seconds
        ma=types.SimpleNamespace(_grab=mock.Mock(side_effect=frames), HP_POLL=1.,
            _after_samples=mock.Mock(side_effect=AssertionError("global sampler must remain untouched")))
        mb=types.SimpleNamespace(BOARD_MOTION_MAX=.008,
            board_transition_reason=lambda f:f.get("transition", ""),
            frontline_state=lambda f:{"owner":f.get("owner","our")},
            board_motion=lambda a,b:b.get("motion",0.))
        return ma, mb, sleep

    def test_half_second_attack_cadence_keeps_timeout_and_global_poll(self):
        ma,mb,sleep=self.fixture([{} for _ in range(37)])
        samples=list(simple.attack_after_samples(ma,mb,18.,clock=lambda:self.now,sleep=sleep))
        self.assertEqual(len(samples),37)
        self.assertFalse(samples[0][1])
        self.assertTrue(all(sample[1] for sample in samples[1:]))
        self.assertEqual(self.sleeps,[.5]*37)
        self.assertEqual(ma.HP_POLL,1.)
        ma._after_samples.assert_not_called()

    def test_missing_transition_unknown_front_and_global_motion_break_stability(self):
        frames=[{},None,{}, {"transition":"banner"},{},{"owner":"unknown"},{},{},
                {"motion":.009},{}]
        ma,mb,sleep=self.fixture(frames)
        samples=list(simple.attack_after_samples(ma,mb,4.5,clock=lambda:self.now,sleep=sleep))
        self.assertEqual([s[1] for s in samples],[False,False,False,False,False,False,False,True,False,True])
        self.assertTrue(samples[1][2])
        self.assertTrue(samples[3][2])
        self.assertTrue(samples[5][2])

    def test_capture_cancellation_propagates_without_retry_or_extra_sample(self):
        from apk_battle_runtime import Stop
        ma,mb,sleep=self.fixture([{},Stop("capture_rejected:test")])
        sampler=simple.attack_after_samples(ma,mb,18.,clock=lambda:self.now,sleep=sleep)
        self.assertFalse(next(sampler)[1])
        with self.assertRaisesRegex(Stop,"capture_rejected:test"): next(sampler)
        self.assertEqual(ma._grab.call_count,2)
        self.assertEqual(self.sleeps,[.5])


class SimpleCombatTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((720, 1280, 3), np.uint8)
        marker = mock.patch.object(simple, "operation_marker", return_value=None)
        marker.start()
        self.addCleanup(marker.stop)

    def test_skipped_actor_cannot_unlock_after_row_or_slot_reflow(self):
        failed, other = unit(), unit(500)
        paint(self.frame, failed, (25, 90, 155))
        paint(self.frame, other, (160, 60, 30))
        ledger = simple.TurnSkipLedger()
        ledger.sync(4)
        ledger.record(self.frame, failed, "tank")
        after = np.zeros_like(self.frame)
        moved, reordered = unit(740, 230, row="front"), unit(350)
        paint(after, moved, (25, 90, 155))
        paint(after, reordered, (160, 60, 30))
        kept = ledger.filter(after, [reordered, moved])
        self.assertEqual(kept, [])
        ledger.sync(4)
        self.assertEqual(ledger.filter(after, [moved]), [])
        ledger.sync(5)
        self.assertEqual(ledger.filter(after, [moved]), [moved])

    def test_missing_or_changed_actor_conservatively_blocks_same_type_only(self):
        failed = unit()
        paint(self.frame, failed, 30)
        ledger = simple.TurnSkipLedger()
        ledger.sync(1)
        ledger.record(self.frame, failed, "tank")
        after = np.full_like(self.frame, 160)
        tank, fighter = unit(400), unit(750, typ="fighter")
        self.assertEqual(ledger.filter(after, [tank, fighter]), [fighter])

    def test_identical_artwork_does_not_unlock_a_duplicate(self):
        first, second = unit(), unit(600)
        for actor in (first, second):
            paint(self.frame, actor, 80)
        ledger = simple.TurnSkipLedger()
        ledger.record(self.frame, first, "tank")
        self.assertEqual(ledger.filter(self.frame, [first, second]), [])

    def test_invalid_artwork_cannot_authorize_retry(self):
        ledger = simple.TurnSkipLedger()
        ledger.record(None, unit(), "tank")
        self.assertEqual(ledger.filter(self.frame, [unit()]), [])

    def test_changed_failed_art_and_similar_neighbour_cannot_unlock_original(self):
        failed, neighbor = unit(), unit(650)
        paint(self.frame, failed, 50)
        ledger = simple.TurnSkipLedger()
        ledger.record(self.frame, failed, "tank")
        later = np.zeros_like(self.frame)
        paint(later, failed, 67)
        paint(later, neighbor, 65)
        self.assertEqual(ledger.filter(later, [failed, neighbor]), [])

    def _fake_policy(self):
        def plan(kind, actor, target, category, owner, reason, roll=None):
            return {"kind": kind, "unit": actor, "target": target, "target_category": category,
                    "front_owner": owner, "actor_type": actor["type"], "reason": reason,
                    "bomber_roll": roll}
        return types.SimpleNamespace(GROUND={"infantry", "tank"}, RANGED={"artillery", "fighter", "bomber"},
            TYPES={"infantry", "tank", "artillery", "fighter", "bomber"}, _plan=plan,
            _empty=lambda k, r: {"kind": k, "reason": r},
            _nearest=lambda cards, actor: min(cards, key=lambda c: abs(c["cx"] - actor["card"]["cx"])))

    def test_unknown_hp_does_not_block_ranged_front_or_guard_plans(self):
        hq = {"cx": 650, "cy": 180, "hp": None, "geometry_verified": True}
        guard = {"cx": 500, "cy": 180, "row": "enemy_support", "guard_state": "guard"}
        front = {"cx": 500, "cy": 300, "row": "enemy_front", "guard_state": "clear"}
        obs = {"owner": "our", "hq": hq, "enemy_front": [], "guard": {"status": "guarded", "hq_guards": [guard]}}
        with mock.patch.dict("sys.modules", {"mobile_combat_policy": self._fake_policy()}):
            self.assertEqual(simple.actor_options(obs, unit(typ="artillery"))["kind"], "attack_hq")
            self.assertEqual(simple.actor_options(obs, unit(typ="fighter"))["target"], guard)
            self.assertEqual(simple.actor_options(obs, unit(row="front"))["target"], guard)
            bomber_obs = dict(obs, owner="enemy", enemy_front=[front])
            self.assertEqual(simple.actor_options(bomber_obs, unit(typ="bomber"))["kind"], "bomber_choice")
            self.assertEqual(simple.actor_options(dict(obs, guard={"status": "clear"}), unit(typ="fighter"))["kind"], "attack_hq")

    def test_move_does_not_need_hq_or_resource_values(self):
        with mock.patch.dict("sys.modules", {"mobile_combat_policy": self._fake_policy()}):
            for owner in ("our", "empty"):
                plan = simple.actor_options({"owner": owner}, unit())
                self.assertEqual(plan["kind"], "movefront")

    def test_only_known_enemy_support_fighter_intercepts_bomber_hq(self):
        obs = {"owner": "empty", "hq": {"cx": 900, "cy": 170, "hp": None,
               "geometry_verified": True}, "enemy_front": []}
        bomber = unit(typ="bomber")
        with mock.patch.dict("sys.modules", {"mobile_combat_policy": self._fake_policy()}):
            for typ in ("infantry", "tank", "bomber", "artillery", "unknown", None):
                support = {"cx": 400, "type": typ, "row": "enemy_support"}
                self.assertEqual(simple.actor_options(dict(obs, enemy_support=[support]), bomber)["kind"], "attack_hq")
            for row in ("enemy_front", "support", "front", None):
                fighter = {"cx": 400, "type": "fighter", "row": row}
                self.assertEqual(simple.actor_options(dict(obs, enemy_support=[fighter]), bomber)["kind"], "attack_hq")
            # Interception covers the support row, not only HQ-adjacent cards.
            fighter = {"cx": 400, "type": "fighter", "row": "enemy_support"}
            intercepted = dict(obs, enemy_support=[fighter, {"type": "unknown", "row": "enemy_support"}])
            self.assertEqual(simple.actor_options(intercepted, bomber)["kind"], "pending")
            self.assertEqual(simple.actor_options(intercepted, unit(typ="artillery"))["kind"], "attack_hq")

    def test_intercepted_bomber_keeps_enemy_front_without_random_roll(self):
        import mobile_combat_policy as policy
        original = getattr(policy, "_apk_original_choose", policy.choose)
        front = {"cx": 650, "cy": 300, "row": "enemy_front"}
        obs = {"owner": "enemy", "hq": {"cx": 900, "geometry_verified": True},
               "units": [unit(typ="bomber")], "enemy_front": [front],
               "enemy_support": [{"cx": 400, "row": "enemy_support", "type": "fighter"}]}
        with mock.patch.object(policy, "_actor_options", simple.actor_options), \
                mock.patch.object(policy, "_apk_original_choose", original, create=True):
            plan = simple.choose(obs, rng=mock.Mock(side_effect=AssertionError("intercepted bomber must not roll")))
        self.assertEqual((plan["kind"], plan["target_category"], plan["target"]), ("attack_unit", "enemy_front", front))
        self.assertIsNone(plan["bomber_roll"])

    def test_fresh_interceptor_invalidates_old_hq_plan_and_removal_reopens_it(self):
        import mobile_combat_policy as policy
        original = getattr(policy, "_apk_original_choose", policy.choose)
        actor = unit(typ="bomber")
        obs = {"owner": "empty", "hq": {"cx": 900, "cy": 170, "geometry_verified": True},
               "units": [actor], "enemy_front": [], "enemy_support": []}
        fighter = {"cx": 400, "row": "enemy_support", "type": "fighter"}
        with mock.patch.object(policy, "_actor_options", simple.actor_options), \
                mock.patch.object(policy, "choose", original):
            old = policy.choose(obs)
            self.assertEqual(old["kind"], "attack_hq")
            fresh = dict(obs, enemy_support=[fighter])
            rejected = policy.revalidate(fresh, old, actor_match=lambda units, _: units)
            self.assertEqual(rejected["kind"], "pending")
            self.assertEqual(policy.choose(obs)["kind"], "attack_hq")

    def test_intercepted_bomber_does_not_block_other_actor_or_normal_end(self):
        import mobile_combat_policy as policy
        original = getattr(policy, "_apk_original_choose", policy.choose)
        bomber, artillery = unit(typ="bomber"), unit(700, typ="artillery")
        obs = {"owner": "empty", "hq": {"cx": 900, "cy": 170, "geometry_verified": True},
               "units": [bomber, artillery], "enemy_front": [],
               "enemy_support": [{"cx": 400, "row": "enemy_support", "type": "fighter"}]}
        with mock.patch.object(policy, "_actor_options", simple.actor_options), \
                mock.patch.object(policy, "_apk_original_choose", original, create=True):
            selected = simple.choose(obs)
            self.assertEqual(selected["unit"], artillery)
            self.assertEqual(selected["kind"], "attack_hq")
            self.assertEqual(simple.choose(dict(obs, units=[bomber]))["kind"], "none")

    def test_unknown_actor_does_not_block_other_actor_or_end_turn(self):
        policy = self._fake_policy()
        captured = []
        def original(obs, **kwargs):
            captured.append(obs)
            return {"kind": "attack_hq" if obs["units"] else "none"}
        policy._apk_original_choose = original
        known, unknown = unit(typ="artillery"), unit(600, typ="unknown")
        obs = {"owner": "our", "hq": {"cx": 650, "hp": None, "geometry_verified": True}, "units": [unknown, known]}
        with mock.patch.dict("sys.modules", {"mobile_combat_policy": policy}):
            self.assertEqual(simple.choose(obs)["kind"], "attack_hq")
            self.assertEqual(captured[-1]["units"], [known])
            self.assertEqual(simple.choose(dict(obs, units=[unknown]))["kind"], "none")
            self.assertEqual(simple.choose(dict(obs, owner="unknown"))["kind"], "pending")

    def _adapter(self, samples, exhausted=False, removed=False, victory=False, stats_changed=False):
        actor = unit(586, 269, row="front")
        target = {"cx": 650, "cy": 180, "hp": None, "row": "enemy_support"}
        plan = {"unit": actor, "target": target, "actor_type": "tank", "front_owner": "our"}
        ma = types.SimpleNamespace(ACTION_AFTER_WAIT=10, SETTLE_DRAG=1.4,
            _prepare=mock.Mock(return_value=(self.frame, "")), _policy_action=mock.Mock(return_value=(plan, "")),
            _drag=mock.Mock(), _after_samples=lambda timeout: iter(samples), _LAST_ATTEMPT=None,
            _victory_evidence=mock.Mock(side_effect=([ (x, .99) for x in victory ] if isinstance(victory, list) else None),
                                        return_value=(victory, .99)),
            _zero_actor_exhausted=mock.Mock(side_effect=exhausted if isinstance(exhausted, list) else None,
                                            return_value=exhausted),
            _target_outcome=mock.Mock(return_value={"target_removed": removed, "target_stats_changed": stats_changed}),
            _report=mock.Mock(), _remember_actor=mock.Mock(), _dump=mock.Mock(),
            _read_mobile_kredits=mock.Mock(side_effect=AssertionError("numeric resources are not required")),
            read_hq_hp=mock.Mock(side_effect=AssertionError("HP is not required")))
        def begin(kind, before, selected, dst):
            ma._LAST_ATTEMPT = {"kind": kind, "before": before, "unit": selected, "target": dst, "input_sent": True}
        ma._begin_attempt = begin
        mb = types.SimpleNamespace(end_turn_state=mock.Mock(return_value="white"),
            frontline_state=mock.Mock(return_value={"owner": "unknown"}),
            _front_cards=mock.Mock(return_value=[]),
            enemy_front_cards=mock.Mock(return_value=[]), enemy_support_cards=mock.Mock(return_value=[target]),
            unit_combat_type=mock.Mock(return_value="tank"))
        adapter = simple.SimpleCombat.__new__(simple.SimpleCombat)
        adapter.ma, adapter.mb = ma, mb
        adapter.engine = types.SimpleNamespace(turns_seen=2, failed_actions_this_turn=0)
        adapter.skips, adapter.event = simple.TurnSkipLedger(), mock.Mock()
        adapter._observed_frame = adapter._observed_turn = None
        adapter._after_samples = ma._after_samples
        return adapter

    def test_hq_two_stable_gray_marker_frames_confirm_without_any_numeric_read(self):
        adapter = self._adapter([(self.frame, True, "")] * 2, exhausted=True)
        with mock.patch.object(simple, "operation_marker", return_value={}), \
                mock.patch.object(time, "monotonic", side_effect=[0., 1.]):
            ok, detail = adapter.attack_hq()
        self.assertTrue(ok, detail)
        adapter.ma.read_hq_hp.assert_not_called()
        adapter.ma._read_mobile_kredits.assert_not_called()
        self.assertEqual(adapter.ma._drag.call_count, 1)

    def test_faster_samples_do_not_shorten_gray_marker_confirmation(self):
        adapter = self._adapter([(self.frame, True, "")] * 2, exhausted=True)
        with mock.patch.object(simple, "operation_marker", return_value={}), \
                mock.patch.object(time, "monotonic", side_effect=[0., .5]):
            self.assertFalse(adapter.attack_hq()[0])
        self.assertEqual(adapter.ma._drag.call_count, 1)
        adapter.ma._remember_actor.assert_not_called()

    def test_unit_target_removed_in_three_spaced_stable_frames_confirms_without_numbers(self):
        adapter = self._adapter([(self.frame, True, "")] * 3, removed=True)
        with mock.patch.object(simple, "operation_marker", return_value=None), \
                mock.patch.object(time, "monotonic", side_effect=[0., .5, 1.]):
            self.assertTrue(adapter.attack_unit()[0])
        adapter.ma._read_mobile_kredits.assert_not_called()

    def test_actor_death_needs_three_spaced_stable_observations_and_one_drag(self):
        adapter = self._adapter([(self.frame, True, "")] * 3)
        with mock.patch.object(simple, "actor_removal", return_value={"actor_removed": True}), \
                mock.patch.object(time, "monotonic", side_effect=[0., .5, 1.]):
            ok, detail = adapter.attack_unit()
        self.assertTrue(ok, detail)
        self.assertEqual(adapter.ma._drag.call_count, 1)
        adapter.note_attempt(adapter.ma._LAST_ATTEMPT, ok)
        self.assertEqual(adapter.skips.entries, [])
        self.assertEqual(adapter.engine.failed_actions_this_turn, 0)
        self.assertEqual(adapter.ma._LAST_ATTEMPT['simple_combat_evidence']['actor_removed_streak'], 3)

    def test_two_removed_frames_or_unspaced_repeats_are_not_death_confirmation(self):
        for stamps in ([0., 1.], [0., .1, .2]):
            adapter = self._adapter([(self.frame, True, "")] * len(stamps))
            with mock.patch.object(simple, "actor_removal", return_value={"actor_removed": True}), \
                    mock.patch.object(time, "monotonic", side_effect=stamps):
                self.assertFalse(adapter.attack_unit()[0])
            adapter.ma._remember_actor.assert_not_called()

    def test_animation_temporary_loss_reappearance_never_confirms_or_retries(self):
        adapter = self._adapter([(self.frame, True, "")] * 4)
        with mock.patch.object(simple, "actor_removal", side_effect=[
                {"actor_removed": True}, {"actor_removed": True},
                {"actor_removed": False}, {"actor_removed": False}]), \
                mock.patch.object(time, "monotonic", side_effect=[0., 1., 2., 3.]):
            ok, _ = adapter.attack_unit()
        self.assertFalse(ok)
        adapter.note_attempt(adapter.ma._LAST_ATTEMPT, ok)
        self.assertEqual(adapter.ma._drag.call_count, 1)
        self.assertEqual(len(adapter.skips.entries), 1)

    def test_motion_missing_frame_and_opponent_turn_reset_actor_death_streak(self):
        for middle in ((self.frame, False, "animation"), (None, False, "missing")):
            adapter = self._adapter([(self.frame, True, "")] * 2 + [middle] + [(self.frame, True, "")] * 2)
            with mock.patch.object(simple, "actor_removal", return_value={"actor_removed": True}), \
                    mock.patch.object(time, "monotonic", side_effect=[0., 1., 2., 3.]):
                self.assertFalse(adapter.attack_unit()[0])
        adapter = self._adapter([(self.frame, True, "")] * 5)
        adapter.mb.end_turn_state.side_effect = ['white', 'white', None, 'white', 'white']
        with mock.patch.object(simple, "actor_removal", return_value={"actor_removed": True}), \
                mock.patch.object(time, "monotonic", side_effect=[0., 1., 2., 3.]):
            self.assertFalse(adapter.attack_unit()[0])

    def test_actor_disappearance_is_not_hq_attack_success(self):
        adapter = self._adapter([(self.frame, True, "")] * 3)
        with mock.patch.object(simple, "actor_removal", return_value={"actor_removed": True}) as probe:
            self.assertFalse(adapter.attack_hq()[0])
        probe.assert_not_called()

    def test_normal_animation_observation_is_bounded_explicit_diagnostic_window_preserved(self):
        for kwargs, expected in (({}, simple.ATTACK_OBSERVE_SECONDS), ({"late_wait": 0}, 1.4)):
            adapter = self._adapter([])
            adapter.ma._after_samples = mock.Mock(return_value=iter([]))
            adapter._after_samples = mock.Mock(return_value=iter([]))
            self.assertFalse(adapter.attack_hq(**kwargs)[0])
            selected = adapter.ma._after_samples if kwargs else adapter._after_samples
            selected.assert_called_once_with(expected)
            unused = adapter._after_samples if kwargs else adapter.ma._after_samples
            unused.assert_not_called()

    def _death_geometry(self):
        actor = unit(586, 269, row="front")
        before, after = self.frame.copy(), self.frame.copy()
        art = np.random.default_rng(46).integers(0, 256, (68, 96, 3), dtype=np.uint8)
        before[301:369, 594:690] = art
        card = dict(actor['card'], n_stats=3)
        mb = types.SimpleNamespace(
            frontline_state=lambda f: {'owner': 'our' if f is before else 'empty'},
            _front_cards=lambda f: [card] if f is before else [])
        def changed(a, b, box):
            x0,y0,x1,y1=box
            return float((np.abs(a[y0:y1,x0:x1].astype(int)-b[y0:y1,x0:x1].astype(int)).max(axis=2)>25).mean())
        return actor, before, after, mb, types.SimpleNamespace(_diff_frac=changed)

    def test_complete_empty_frontline_and_changed_absent_art_confirms_actor_removal(self):
        actor, before, after, mb, ma = self._death_geometry()
        self.assertTrue(simple.actor_removal(before, after, actor, mb, ma)['actor_removed'])

    def test_gray_marker_or_missing_orange_candidate_never_proves_actor_removal(self):
        actor, before, after, mb, ma = self._death_geometry()
        mb.frontline_state=lambda f:{'owner':'our'}
        mb._front_cards=lambda f:[dict(actor['card'], n_stats=3)]
        self.assertFalse(simple.actor_removal(before, after, actor, mb, ma)['actor_removed'])

    def test_unknown_owner_unbalanced_row_and_unchanged_art_refuse_actor_removal(self):
        for variant in ('owner', 'row', 'art'):
            actor, before, after, mb, ma = self._death_geometry()
            if variant == 'owner':
                mb.frontline_state=lambda f:{'owner':'our' if f is before else 'unknown'}
            elif variant == 'row':
                mb._front_cards=lambda f:[dict(actor['card'], cx=700, n_stats=3)] if f is before else []
            else:
                after[:]=before
            self.assertFalse(simple.actor_removal(before, after, actor, mb, ma)['actor_removed'])

    def test_art_relocated_or_duplicate_surviving_on_own_board_refuses_death(self):
        actor, before, after, mb, ma = self._death_geometry()
        after[450:518, 400:496]=before[301:369,594:690]
        detail=simple.actor_removal(before,after,actor,mb,ma)
        self.assertFalse(detail['actor_removed'])
        self.assertEqual(detail['reason'], 'actor_art_still_on_board')

    def test_support_death_requires_existing_complete_row_verifier(self):
        actor, before, after, _, ma = self._death_geometry()
        actor['row']='support'
        card=dict(actor['card'], row_kind='unit')
        for missing, expected in ((False, True), (True, False)):
            rows = types.SimpleNamespace(_row=lambda f: (
                ([card] if f is before else None if missing else []), '', {}))
            with mock.patch.dict('sys.modules', {'apk_deploy_target': rows}):
                self.assertEqual(simple.actor_removal(before, after, actor, None, ma)['actor_removed'], expected)

    def test_one_gray_frame_never_claims_success(self):
        adapter = self._adapter([(self.frame, True, "")], exhausted=True)
        with mock.patch.object(simple, "operation_marker", return_value={}):
            self.assertFalse(adapter.attack_unit()[0])
        adapter.ma._remember_actor.assert_not_called()

    def test_persistent_target_health_change_confirms_when_duplicate_actor_survives(self):
        adapter = self._adapter([(self.frame, True, "")] * 3, stats_changed=True)
        with mock.patch.object(simple, "actor_removal", return_value={
                "actor_removed": False, "reason": "actor_art_still_on_board"}), \
                mock.patch.object(time, "monotonic", side_effect=[0., .5, 1.]):
            ok, detail = adapter.attack_unit()
        self.assertTrue(ok, detail)
        evidence = adapter.ma._LAST_ATTEMPT['simple_combat_evidence']
        self.assertEqual(evidence['target_stats_streak'], 3)
        self.assertFalse(evidence['actor_removed'])
        self.assertFalse(evidence['target_removed'])
        self.assertEqual(adapter.ma._drag.call_count, 1)
        adapter.ma._read_mobile_kredits.assert_not_called()
        adapter.ma.read_hq_hp.assert_not_called()

    def test_target_health_change_needs_three_observations_spanning_one_second(self):
        for stamps in ([0., 1.], [0., .1, .2]):
            adapter = self._adapter([(self.frame, True, "")] * len(stamps), stats_changed=True)
            with mock.patch.object(simple, "actor_removal", return_value={"actor_removed": False}), \
                    mock.patch.object(time, "monotonic", side_effect=stamps):
                self.assertFalse(adapter.attack_unit()[0])
            adapter.ma._remember_actor.assert_not_called()

    def test_missing_motion_opponent_or_reverted_health_breaks_stats_sequence(self):
        for middle in ((self.frame, False, "motion"), (None, False, "missing")):
            adapter = self._adapter([(self.frame, True, "")] * 2 + [middle] + [(self.frame, True, "")] * 2,
                                    stats_changed=True)
            with mock.patch.object(simple, "actor_removal", return_value={"actor_removed": False}), \
                    mock.patch.object(time, "monotonic", side_effect=[0., .5, 1., 1.5]):
                self.assertFalse(adapter.attack_unit()[0])
        adapter = self._adapter([(self.frame, True, "")] * 5, stats_changed=True)
        adapter.mb.end_turn_state.side_effect = ['white', 'white', None, 'white', 'white']
        with mock.patch.object(simple, "actor_removal", return_value={"actor_removed": False}), \
                mock.patch.object(time, "monotonic", side_effect=[0., .5, 1., 1.5]):
            self.assertFalse(adapter.attack_unit()[0])
        adapter = self._adapter([(self.frame, True, "")] * 5)
        adapter.ma._target_outcome.side_effect = [
            {"target_stats_changed": value} for value in (True, True, False, True, True)]
        with mock.patch.object(simple, "actor_removal", return_value={"actor_removed": False}), \
                mock.patch.object(time, "monotonic", side_effect=[0., .5, 1., 1.5, 2.]):
            self.assertFalse(adapter.attack_unit()[0])

    def test_motion_missing_capture_and_opponent_turn_break_evidence_pair(self):
        for middle in ((self.frame, False, "motion"), (None, False, "missing")):
            adapter = self._adapter([(self.frame, True, ""), middle, (self.frame, True, "")], exhausted=True)
            with mock.patch.object(simple, "operation_marker", return_value={}):
                self.assertFalse(adapter.attack_hq()[0])
        adapter = self._adapter([(self.frame, True, "")] * 3, exhausted=True)
        adapter.mb.end_turn_state.side_effect = ["white", None, "white"]
        with mock.patch.object(simple, "operation_marker", return_value={}):
            self.assertFalse(adapter.attack_hq()[0])

    def test_two_victory_frames_confirm_even_without_board_markers(self):
        adapter = self._adapter([(self.frame, False, "result")] * 2, victory=True)
        with mock.patch.object(simple, "operation_marker", return_value=None):
            self.assertTrue(adapter.attack_hq()[0])

    def test_dispatch_error_propagates_instead_of_skipping(self):
        adapter = self._adapter([])
        adapter.ma._drag.side_effect = RuntimeError("accepted_completion_unknown")
        with mock.patch.object(simple, "operation_marker", return_value={}), self.assertRaisesRegex(RuntimeError, "completion_unknown"):
            adapter.attack_hq()
        adapter.ma._report.assert_not_called()

    def test_only_failed_attempt_locks_actor_successful_move_stays_available(self):
        adapter = self._adapter([])
        attempt = {"kind": "movefront", "before": self.frame, "unit": unit(), "input_sent": True}
        adapter.note_attempt(attempt, True)
        self.assertEqual(adapter.skips.entries, [])
        adapter.note_attempt(attempt, False)
        self.assertEqual(len(adapter.skips.entries), 1)
        self.assertEqual(adapter.engine.failed_actions_this_turn, 1)
        self.assertEqual(adapter.skips.filter(self.frame, [unit()]), [])


if __name__ == "__main__":
    unittest.main()
