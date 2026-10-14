"""Saved-frame and pure-flow regressions; never connects a live device."""
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest import mock
import cv2
import numpy as np
import apk_match_entry
from apk_match_entry import MenuFlow, Recognizer

ASSETS = FIXTURES = None


def screen(state, mode=''):
    return {'state':state,'selected_mode':mode,'targets':{name:[100,100,60,40] for name in (
        'menu_home_start','menu_battle_mode','menu_select_deck','menu_select_casual',
        'menu_select_ranked','menu_start_queue','menu_dismiss_reward','menu_reconnect',
        'menu_dismiss_task','menu_dismiss_pass','menu_dismiss_box','menu_dismiss_store',
        'menu_dismiss_airdrop','menu_dismiss_starter','menu_dismiss_weekend',
        'menu_dismiss_blocking_popup',
        'menu_close_deck')}}


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.flow = MenuFlow('casual',0)
        # Most flow tests isolate mode/queue after a prior verified first-slot
        # selection. Fresh-session selection has dedicated tests below.
        self.flow.first_deck_selected = True
        self.sequence = 0
        self.now = 0

    def step(self,state,mode='',opening=False,advance=800):
        self.now += advance
        self.sequence += 1
        return self.flow.observe(screen(state,mode),self.sequence,self.now,opening)

    def stable(self,state,mode=''):
        self.step(state,mode)
        return self.step(state,mode)

    def send(self,state,mode='',action=None):
        decision=self.stable(state,mode)
        if action:
            self.assertEqual(action,decision.get('action'))
        self.flow.accepted(decision['action'],self.now)

    def test_full_casual_route(self):
        self.send('disconnected',action='menu_reconnect')
        self.send('login_reward',action='menu_dismiss_reward')
        self.send('home',action='menu_home_start')
        self.send('mode_menu',action='menu_battle_mode')
        self.send('deck_list',action='menu_select_deck')
        self.send('deck_ready','ranked','menu_select_casual')
        self.send('deck_ready','casual','menu_start_queue')
        self.assertEqual('queueing',self.step('queueing')['wait'])
        self.assertFalse(self.step('unknown',opening=True).get('verified',False))
        self.assertTrue(self.step('unknown',opening=True)['verified'])

    def test_ranked_route_changes_remembered_casual(self):
        self.flow=MenuFlow('ranked',0)
        self.flow.first_deck_selected=True
        self.send('deck_ready','casual','menu_select_ranked')
        self.send('deck_ready','ranked','menu_start_queue')
        self.assertEqual(2,self.flow.inputs)

    def test_reward_can_continue_through_all_startup_popups(self):
        self.send('login_reward',action='menu_dismiss_reward')
        self.send('task_popup',action='menu_dismiss_task')
        self.send('pass_popup',action='menu_dismiss_pass')
        self.send('box_popup',action='menu_dismiss_box')
        self.send('home',action='menu_home_start')
        self.assertEqual(5,self.flow.inputs)

    def test_all_distinct_startup_overlays_fit_before_verified_queue(self):
        self.flow=MenuFlow('casual',0)
        self.send('disconnected',action='menu_reconnect')
        self.send('login_reward',action='menu_dismiss_reward')
        for popup,action in apk_match_entry.POPUP_ACTIONS.items():
            self.send(popup,action=action)
        self.send('home',action='menu_home_start')
        self.send('mode_menu',action='menu_battle_mode')
        self.send('deck_list',action='menu_select_deck')
        self.send('deck_ready','ranked','menu_select_casual')
        self.send('deck_ready','casual','menu_start_queue')
        self.assertEqual(7+len(apk_match_entry.POPUP_ACTIONS),self.flow.inputs)
        self.assertFalse(self.step('unknown',opening=True).get('verified',False))
        self.assertTrue(self.step('unknown',opening=True)['verified'])

    def test_each_startup_popup_can_be_omitted(self):
        for popup,action in apk_match_entry.POPUP_ACTIONS.items():
            with self.subTest(popup):
                self.setUp()
                self.send('login_reward',action='menu_dismiss_reward')
                self.send(popup,action=action)
                self.assertEqual('menu_home_start',self.stable('home')['action'])

    def test_popup_that_does_not_close_is_not_retried(self):
        for popup,action in apk_match_entry.POPUP_ACTIONS.items():
            with self.subTest(popup):
                self.setUp()
                self.send(popup,action=action)
                self.assertNotIn('action',self.stable(popup))
                self.assertEqual('menu_action_unconfirmed:'+action,
                                 self.step(popup,advance=15000)['stop'])

    def test_popup_returning_after_another_popup_is_not_retried(self):
        self.send('task_popup',action='menu_dismiss_task')
        self.send('pass_popup',action='menu_dismiss_pass')
        self.assertEqual('menu_repeated_state:menu_dismiss_task',self.stable('task_popup')['stop'])

    def test_popup_after_queue_cannot_emit_dismiss(self):
        self.send('deck_ready','casual','menu_start_queue')
        self.assertNotIn('action',self.stable('task_popup'))
        self.assertEqual('queue_did_not_open',self.step('task_popup',advance=13000)['stop'])

    def test_selected_mode_can_start_without_toggle(self):
        self.assertEqual('menu_start_queue',self.stable('deck_ready','casual')['action'])

    def test_initial_detail_must_close_before_first_slot_selection(self):
        self.flow=MenuFlow('casual',0)
        self.assertFalse(self.flow.first_deck_selected)
        self.send('deck_ready','casual','menu_close_deck')
        self.send('deck_list',action='menu_select_deck')
        self.assertFalse(self.flow.first_deck_selected)
        self.assertNotIn('action',self.step('deck_ready','casual'))
        self.assertFalse(self.flow.first_deck_selected)
        self.assertEqual('menu_start_queue',self.step('deck_ready','casual')['action'])
        self.assertTrue(self.flow.first_deck_selected)

    def test_initial_detail_does_not_switch_mode_before_first_slot(self):
        self.flow=MenuFlow('casual',0)
        self.assertEqual('menu_close_deck',self.stable('deck_ready','ranked')['action'])

    def test_first_slot_unconfirmed_detail_does_not_authorize_queue(self):
        self.flow=MenuFlow('casual',0)
        self.send('deck_list',action='menu_select_deck')
        self.step('deck_ready','casual')
        self.step('unknown')
        self.assertFalse(self.flow.first_deck_selected)
        self.assertNotIn('action',self.step('deck_ready','casual'))
        self.assertFalse(self.flow.first_deck_selected)

    def test_close_detail_failure_cannot_fall_through_to_queue(self):
        self.flow=MenuFlow('casual',0)
        self.send('deck_ready','casual','menu_close_deck')
        self.assertNotIn('action',self.stable('deck_ready','casual'))
        self.assertEqual('menu_action_unconfirmed:menu_close_deck',
                         self.step('deck_ready','casual',advance=15000)['stop'])

    def test_wrong_mode_never_starts(self):
        self.send('deck_ready','ranked','menu_select_casual')
        self.assertNotIn('action',self.stable('deck_ready','ranked'))
        self.assertIn('menu_action_unconfirmed',self.step('deck_ready','ranked',advance=15000)['stop'])

    def test_unknown_selection_is_not_target_authority(self):
        # Recognizer cannot produce deck_ready with an absent selected state.
        obs={'state':'unknown','targets':{'menu_start_queue':[1,1,2,2]}}
        self.assertNotIn('action',self.flow.observe(obs,1,1000))

    def test_duplicate_frame_no_stability(self):
        obs=screen('home')
        self.flow.observe(obs,1,800)
        self.assertNotIn('action',self.flow.observe(obs,1,1600))

    def test_long_gap_no_stability(self):
        self.step('home')
        self.assertNotIn('action',self.step('home',advance=5001))

    def test_short_gap_no_stability(self):
        self.step('home')
        self.assertNotIn('action',self.step('home',advance=100))

    def test_existing_queue_stops(self):
        self.assertEqual('existing_queue_mode_unverified',self.step('queueing')['stop'])

    def test_existing_opening_cannot_verify(self):
        self.assertFalse(self.step('unknown',opening=True).get('verified',False))
        self.assertFalse(self.step('unknown',opening=True).get('verified',False))

    def test_queue_button_sent_once(self):
        self.send('deck_ready','casual','menu_start_queue')
        for _ in range(8):
            self.assertNotIn('action',self.step('deck_ready','casual'))
        self.assertEqual('queue_did_not_open',self.step('deck_ready','casual',advance=13000)['stop'])

    def test_queue_timeout_explains_game_queue(self):
        self.send('deck_ready','casual','menu_start_queue')
        self.assertEqual('matchmaking_timeout_queue_may_continue',self.step('queueing',advance=120000)['stop'])

    def test_queue_disconnect_no_reconnect(self):
        self.send('deck_ready','casual','menu_start_queue')
        self.assertEqual('disconnected_after_queue',self.step('disconnected')['stop'])

    def test_unknown_is_bounded(self):
        self.step('unknown')
        self.assertEqual('menu_unknown_timeout',self.step('unknown',advance=30000)['stop'])

    def test_transition_never_uses_a_provided_target(self):
        observation=screen('menu_transition')
        for frame_id,now in ((1,800),(2,1600),(3,2400)):
            self.assertEqual({'wait':'menu_transition'},
                             self.flow.observe(observation,frame_id,now))
        self.assertEqual(0,self.flow.inputs)

    def test_transition_breaks_a_stable_pair(self):
        self.step('deck_list')
        self.step('menu_transition')
        self.assertNotIn('action',self.step('deck_list'))
        self.assertEqual('menu_select_deck',self.step('deck_list')['action'])

    def test_transition_is_bounded_without_becoming_unknown(self):
        self.step('menu_transition')
        self.assertEqual('menu_transition_timeout',
                         self.step('menu_transition',advance=30000)['stop'])

    def test_transition_after_own_queue_waits_without_new_inputs(self):
        self.send('deck_ready','casual','menu_start_queue')
        self.assertEqual({'wait':'menu_transition'},
                         self.step('menu_transition',advance=13000))
        self.assertEqual(1,self.flow.inputs)

    def test_total_is_bounded(self):
        self.assertEqual('menu_time_budget',self.step('home',advance=180000)['stop'])

    def test_loop_is_not_retried(self):
        self.send('home',action='menu_home_start')
        self.stable('deck_list')
        self.assertEqual('menu_repeated_state:menu_home_start',self.stable('home')['stop'])

    def test_input_budget(self):
        self.flow.inputs=apk_match_entry.MAX_MENU_INPUTS
        self.assertEqual('menu_input_budget',self.stable('home')['stop'])

    def test_modes_strict(self):
        for mode in ('training','',None,'CASUAL',0):
            with self.assertRaises(ValueError): MenuFlow(mode,0)


class RunTests(unittest.TestCase):
    """Execute the real run loop/recognizer with saved pixels and a scripted bridge.

    Opening inspector verdicts are fake Java replies here; the Java recognizer has
    its own saved-frame checks. No Android bridge, game input or real sleep runs.
    """
    class Bridge:
        def __init__(self, rows, reply=None, cancelled=False):
            self.rows = list(rows)
            self.reply = reply if reply is not None else {'accepted':True,'completed':True}
            self.cancelled = cancelled
            self.now = 10000
            self.sequence = 0
            self.requests, self.events, self.opening_calls = [], [], []
            self.last = None

        def elapsedRealtime(self): return self.now
        def deadlineElapsedRealtime(self): return 240000
        def isCancelled(self): return self.cancelled

        def capture(self):
            if not self.rows:
                self.cancelled = True
                return json.dumps({'ok':False,'reason':'cancelled'})
            row = self.rows.pop(0)
            self.sequence += 1
            self.now += row.get('advance_ms', 0)
            self.last = row
            if 'error' in row:
                return json.dumps({'ok':False,'reason':row['error']})
            packet = {'ok':True,'frame_id':self.sequence,
                'captured_elapsed_ms':self.now-row.get('age_ms',0),
                'foreground_generation':1,'source_width':1920,'source_height':1080,
                'png_path':str(Path(FIXTURES)/(row.get('fixture','ready_casual')+'.png'))}
            if row.get('cancel_after_capture'): self.cancelled = True
            return json.dumps(packet)

        def emit(self, event):
            event=json.loads(event)
            self.events.append(event)
            if event.get('kind')=='menu' and self.last:
                self.now += self.last.get('emit_ms',0)

        def dispatchMenu(self, request):
            self.requests.append(json.loads(request))
            return json.dumps(self.last.get('reply', self.reply))

        def inspectOpening(self):
            self.opening_calls.append(self.sequence)
            return json.dumps({'ok':True,
                'phase':'MULLIGAN_CONFIRM' if self.last.get('opening') else 'UNKNOWN',
                'frame_id':self.sequence+self.last.get('inspector_frame_offset',0)})

        def sleep(self, seconds): self.now += round(seconds*1000)

    def execute(self, rows, reply=None, cancelled=False, selected_deck=True):
        bridge = self.Bridge(rows,reply,cancelled)
        # Age/dispatch tests isolate the post-deck stage. End-to-end and
        # remembered-detail tests explicitly start with selected_deck=False.
        def flow_factory(mode,started):
            flow=MenuFlow(mode,started)
            flow.first_deck_selected=selected_deck
            return flow
        with mock.patch.object(apk_match_entry.time,'sleep',side_effect=bridge.sleep), \
                mock.patch.object(apk_match_entry,'MenuFlow',side_effect=flow_factory):
            result = json.loads(apk_match_entry.run(bridge,ASSETS,'casual'))
        return result, bridge

    def test_expired_precursor_and_one_fresh_frame_cannot_dispatch(self):
        result, bridge = self.execute([{'age_ms':4000},{}])
        self.assertEqual([],bridge.requests)
        self.assertFalse(result['queue_requested'])
        self.assertTrue(any(e['value'].get('reason')=='menu_frame_age_expired' for e in bridge.events))

    def test_two_fresh_frames_after_expired_precursor_can_dispatch(self):
        result, bridge = self.execute([{'age_ms':4000},{},{}])
        self.assertEqual([3],[r['frame_id'] for r in bridge.requests])
        self.assertEqual('menu_start_queue',bridge.requests[0]['context'])
        self.assertTrue(result['queue_requested'])

    def test_future_precursor_cannot_confirm_next_frame(self):
        result, bridge = self.execute([{'age_ms':-1},{}])
        self.assertEqual([],bridge.requests)
        self.assertFalse(result['verified'])

    def test_age_is_rechecked_after_progress_emission(self):
        result, bridge = self.execute([{}, {'emit_ms':3100}, {}, {}])
        self.assertEqual([4],[r['frame_id'] for r in bridge.requests])
        self.assertEqual(1,result['menu_inputs'])

    def test_native_menu_uses_java_three_second_freshness(self):
        bridge=self.Bridge([{'age_ms':3500},{}])
        bridge.captureNative=bridge.capture
        recognizer=mock.Mock()
        recognizer.observe.return_value=screen('home')
        with mock.patch.object(apk_match_entry.time,'sleep',side_effect=bridge.sleep), \
                mock.patch('apk_native.menu.NativeMenuRecognizer',return_value=recognizer):
            result=json.loads(apk_match_entry.run(bridge,ASSETS,'casual',native=True))
        self.assertEqual([2],[r['frame_id'] for r in bridge.requests])
        self.assertTrue(any(e['value'].get('reason')=='menu_frame_age_expired' for e in bridge.events))

    def test_waiting_for_game_retries_capture(self):
        result, bridge = self.execute([
            {'error':'waiting_for_new_game_foreground'},
            {'error':'waiting_for_new_game_foreground'},{},{}])
        self.assertEqual([4],[r['frame_id'] for r in bridge.requests])
        self.assertEqual(2,sum(e['value'].get('state')=='waiting_for_game' for e in bridge.events))
        self.assertEqual(1,result['menu_inputs'])

    def test_non_waiting_capture_failure_stops_without_input(self):
        result, bridge = self.execute([{'error':'foreground_changed'},{},{}])
        self.assertEqual('foreground_changed',result['reason'])
        self.assertEqual([],bridge.requests)
        self.assertEqual(1,bridge.sequence)

    def test_cancelled_before_capture_does_nothing(self):
        result, bridge = self.execute([{},{}],cancelled=True)
        self.assertEqual('cancelled',result['reason'])
        self.assertEqual(0,bridge.sequence)
        self.assertEqual([],bridge.requests)

    def test_cancelled_between_observations_does_not_complete_pair(self):
        result, bridge = self.execute([{'cancel_after_capture':True},{}])
        self.assertFalse(result['verified'])
        self.assertEqual([],bridge.requests)
        self.assertEqual(1,bridge.sequence)

    def test_rejected_gesture_is_not_retried(self):
        result, bridge = self.execute([{}, {}, {}, {}],
            {'accepted':False,'completed':False,'reason':'platform_rejected'})
        self.assertEqual('menu_dispatch:platform_rejected',result['reason'])
        self.assertEqual(1,len(bridge.requests))
        self.assertEqual(0,result['menu_inputs'])
        self.assertFalse(result['queue_requested'])

    def test_expired_rejection_reacquires_two_fresh_frames(self):
        expired={'accepted':False,'completed':False,'reason':'frame_age_expired'}
        result, bridge = self.execute([{}, {'reply':expired}, {}, {}])
        self.assertEqual([2,4],[r['frame_id'] for r in bridge.requests])
        self.assertEqual(1,result['menu_inputs'])
        self.assertTrue(result['queue_requested'])
        self.assertEqual(1,sum(e['kind']=='menu_replan' for e in bridge.events))

    def test_repeated_expired_dispatch_is_bounded(self):
        result, bridge = self.execute([{} for _ in range(10)],
            {'accepted':False,'completed':False,'reason':'frame_age_expired'})
        self.assertEqual('menu_dispatch_expired_3_times',result['reason'])
        self.assertEqual([2,4,6],[r['frame_id'] for r in bridge.requests])
        self.assertEqual(0,result['menu_inputs'])
        self.assertFalse(result['queue_requested'])

    def test_expiry_reason_with_uncertain_receipt_is_not_retried(self):
        for reply in ({'accepted':True,'completed':False,'reason':'frame_age_expired'},
                      {'accepted':False,'reason':'frame_age_expired'}):
            result, bridge = self.execute([{}, {}, {}, {}],reply)
            self.assertEqual('menu_dispatch:frame_age_expired',result['reason'])
            self.assertEqual(1,len(bridge.requests))

    def test_incomplete_accepted_gesture_is_not_retried(self):
        result, bridge = self.execute([{}, {}, {}, {}],
            {'accepted':True,'completed':False,'reason':'gesture_cancelled'})
        self.assertEqual('menu_dispatch:gesture_cancelled',result['reason'])
        self.assertEqual(1,len(bridge.requests))
        self.assertEqual(1,result['menu_inputs'])
        self.assertTrue(result['queue_requested'])
        self.assertFalse(result['verified'])

    def test_existing_queue_cannot_be_adopted(self):
        result, bridge = self.execute([{'fixture':'queue_plane'}])
        self.assertEqual('existing_queue_mode_unverified',result['reason'])
        self.assertEqual([],bridge.requests)
        self.assertFalse(result['verified'])

    def test_existing_opening_is_not_inspected_or_adopted(self):
        result, bridge = self.execute([
            {'fixture':'battle','opening':True},
            {'fixture':'battle','opening':True,'advance_ms':31000}])
        self.assertEqual('menu_unknown_timeout',result['reason'])
        self.assertEqual([],bridge.requests)
        self.assertEqual([],bridge.opening_calls)
        self.assertFalse(result['verified'])

    def test_own_queue_then_two_opening_verdicts_hands_over(self):
        result, bridge = self.execute([{}, {}, {'fixture':'queue_plane'},
            {'fixture':'battle','opening':True},{'fixture':'battle','opening':True}])
        self.assertTrue(result['verified'])
        self.assertEqual('mulligan_ready',result['reason'])
        self.assertEqual([2],[r['frame_id'] for r in bridge.requests])
        self.assertEqual([3,4,5],bridge.opening_calls)

    def test_opening_verdict_must_belong_to_same_capture(self):
        result, bridge = self.execute([{}, {},
            {'fixture':'battle','opening':True,'inspector_frame_offset':-1},
            {'fixture':'battle','opening':True}])
        self.assertFalse(result['verified'])
        self.assertEqual([2],[r['frame_id'] for r in bridge.requests])

    def test_expired_opening_verdict_does_not_confirm_fresh_successor(self):
        result, bridge = self.execute([{}, {},
            {'fixture':'battle','opening':True,'age_ms':4000},
            {'fixture':'battle','opening':True}])
        self.assertFalse(result['verified'])
        self.assertEqual([2],[r['frame_id'] for r in bridge.requests])

    def test_saved_login_popup_chain_reaches_home_without_promotional_taps(self):
        rows = [{'fixture':name} for name in ('login','task_popup','pass_popup','box_popup','home')
                for _ in range(2)]
        result,bridge = self.execute(rows)
        self.assertEqual(['menu_dismiss_reward','menu_dismiss_task','menu_dismiss_pass',
                          'menu_dismiss_box','menu_home_start'],[r['context'] for r in bridge.requests])
        self.assertEqual([2,4,6,8,10],[r['frame_id'] for r in bridge.requests])
        self.assertEqual([906.,600.],bridge.requests[1]['from'])
        for request in bridge.requests[2:4]:
            self.assertTrue(930 < request['from'][0] < 967)
            self.assertTrue(196 < request['from'][1] < 232)
        self.assertFalse(result['queue_requested'])

    def test_saved_task_popup_is_not_reclicked_when_no_change_observed(self):
        result,bridge = self.execute([{'fixture':'task_popup'} for _ in range(4)])
        self.assertEqual(['menu_dismiss_task'],[r['context'] for r in bridge.requests])
        self.assertFalse(result['verified'])

    def test_saved_distinct_offers_follow_prior_store_and_pass_once_each(self):
        # Real, independent offer fixtures, with earlier existing promotions.
        # Both new actions must remain independent of already-issued store/pass.
        rows = [{'fixture':name} for name in ('store_popup','pass_popup',
                    'airdrop_popup','starter_popup','home') for _ in range(2)]
        result,bridge = self.execute(rows)
        self.assertEqual(['menu_dismiss_store','menu_dismiss_pass',
                          'menu_dismiss_airdrop','menu_dismiss_starter','menu_home_start'],
                         [r['context'] for r in bridge.requests])
        self.assertEqual([2,4,6,8,10],[r['frame_id'] for r in bridge.requests])
        for request in bridge.requests[2:4]:
            self.assertEqual([938,202,25,25],request['target_bounds'])
            self.assertEqual([950.5,214.5],request['from'])
            self.assertEqual(request['from'],request['to'])
        self.assertFalse(result['queue_requested'])

    def test_expired_offer_precursor_does_not_authorize_white_x(self):
        for name in ('airdrop_popup','starter_popup','weekend_popup'):
            with self.subTest(name):
                result,bridge = self.execute([{'fixture':name,'age_ms':4000},{'fixture':name}])
                self.assertEqual([],bridge.requests)
                self.assertFalse(result['verified'])

    def test_saved_weekend_follows_prior_offers_then_observes_home_twice(self):
        # Weekend fixtures are held-out captures of the same occurrence used
        # for crop training; no independent popup/session generalization claim.
        names=('login','task_popup','pass_popup','starter_popup','airdrop_popup',
               'weekend_popup','home')
        rows=[{'fixture':name} for name in names for _ in range(2)]
        result,bridge=self.execute(rows)
        self.assertEqual(['menu_dismiss_reward','menu_dismiss_task','menu_dismiss_pass',
                          'menu_dismiss_starter','menu_dismiss_airdrop','menu_dismiss_weekend',
                          'menu_home_start'],[r['context'] for r in bridge.requests])
        request=bridge.requests[-2]
        self.assertEqual([938,202,25,25],request['target_bounds'])
        self.assertEqual([950.5,214.5],request['from'])
        self.assertEqual(request['from'],request['to'])
        self.assertEqual([2,4,6,8,10,12,14],[r['frame_id'] for r in bridge.requests])
        self.assertFalse(result['queue_requested'])

    def test_incomplete_weekend_close_stops_without_retry(self):
        result,bridge=self.execute([{'fixture':'weekend_popup'}]*4,
            {'accepted':True,'completed':False,'reason':'gesture_cancelled'})
        self.assertEqual(['menu_dismiss_weekend'],[r['context'] for r in bridge.requests])
        self.assertEqual('menu_dispatch:gesture_cancelled',result['reason'])
        self.assertFalse(result['verified'])

    def test_armed_wait_then_popups_and_mode_switch_reach_own_opening(self):
        rows = [{'error':'waiting_for_new_game_foreground'}]
        rows += [{'fixture':name} for name in ('login','task_popup','pass_popup','box_popup',
                  'home','deck_list','ready_ranked','ready_casual') for _ in range(2)]
        rows += [{'fixture':'queue_plane'},{'fixture':'battle','opening':True},
                 {'fixture':'battle','opening':True}]
        result,bridge = self.execute(rows,selected_deck=False)
        self.assertTrue(result['verified'])
        self.assertEqual(8,result['menu_inputs'])
        self.assertEqual(['menu_dismiss_reward','menu_dismiss_task','menu_dismiss_pass',
                          'menu_dismiss_box','menu_home_start','menu_select_deck',
                          'menu_select_casual','menu_start_queue'],[r['context'] for r in bridge.requests])
        self.assertEqual('casual',bridge.requests[-1]['selected_mode'])
        self.assertTrue(bridge.requests[-1]['first_deck_selected'])

    def test_remembered_second_deck_is_closed_then_first_slot_reselected(self):
        rows=[{'fixture':name} for name in ('second_deck_detail','deck_list','ready_casual') for _ in range(2)]
        result,bridge=self.execute(rows,selected_deck=False)
        self.assertEqual(['menu_close_deck','menu_select_deck','menu_start_queue'],
                         [r['context'] for r in bridge.requests])
        self.assertEqual([False,False,True],[r['first_deck_selected'] for r in bridge.requests])
        self.assertEqual([854.,600.],bridge.requests[0]['from'])
        self.assertTrue(result['first_deck_selected'])

    def test_live_menu_fade_waits_for_two_new_complete_frames(self):
        rows=[{'fixture':name} for name in ('home','home','selected_deck_transition',
              'selected_deck_list','selected_deck_list','ready_casual','ready_casual')]
        result,bridge=self.execute(rows,selected_deck=False)
        self.assertEqual(['menu_home_start','menu_select_deck','menu_start_queue'],
                         [r['context'] for r in bridge.requests])
        self.assertEqual([2,5,7],[r['frame_id'] for r in bridge.requests])
        transition=[event for event in bridge.events if event['kind']=='menu'][2]['value']
        self.assertEqual('menu_transition',transition['state'])
        self.assertEqual('first_deck_not_ready',transition['reason'])
        self.assertEqual('imread',transition['frame_reader'])
        self.assertEqual([],list(transition['targets']))
        self.assertFalse(transition['action_ready'])
        self.assertTrue(result['queue_requested'])

    def test_complete_frame_before_fade_cannot_confirm_frame_after_it(self):
        rows=[{'fixture':name} for name in ('selected_deck_list',
                    'selected_deck_transition','selected_deck_list')]
        result,bridge=self.execute(rows,selected_deck=False)
        self.assertEqual([],bridge.requests)
        self.assertFalse(result['queue_requested'])

    def test_expired_complete_frame_after_fade_cannot_authorize_successor(self):
        rows=[{'fixture':'selected_deck_transition'},
              {'fixture':'selected_deck_list','age_ms':4000},
              {'fixture':'selected_deck_list'}]
        result,bridge=self.execute(rows,selected_deck=False)
        self.assertEqual([],bridge.requests)
        self.assertFalse(result['first_deck_selected'])

    def test_repeated_live_transition_reaches_named_timeout_without_input(self):
        rows=[{'fixture':'selected_deck_transition'},
              {'fixture':'selected_deck_transition','advance_ms':30000}]
        result,bridge=self.execute(rows,selected_deck=False)
        self.assertEqual('menu_transition_timeout',result['reason'])
        self.assertEqual([],bridge.requests)


class PixelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recognizer=Recognizer(ASSETS)
        cls.manifest=json.loads((Path(FIXTURES)/'manifest.json').read_text(encoding='utf-8'))

    def fixture(self,name):
        return cv2.imread(str(Path(FIXTURES)/(name+'.png')))

    def test_saved_frames(self):
        for row in self.manifest['fixtures']:
            with self.subTest(row['id']):
                path=Path(FIXTURES)/row['file']
                self.assertEqual(row['sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
                observation=self.recognizer.observe(cv2.imread(str(path)))
                self.assertEqual(row['state'],observation['state'])
                self.assertEqual(row.get('mode',''),observation.get('selected_mode',''))

    def test_dark_overlay(self):
        for name in ('home','deck_list','ready_casual','ready_ranked','task_popup','pass_popup','box_popup',
                     'airdrop_popup','starter_popup','weekend_popup'):
            frame=self.fixture(name)
            frame=(frame.astype(np.float32)*.55).astype(np.uint8)
            self.assertEqual('unknown',self.recognizer.observe(frame)['state'],name)

    def test_two_digit_task_progress_keeps_both_anchors_and_bounded_position(self):
        frame=self.fixture('task_popup_progress10')
        self.assertEqual('task_popup',self.recognizer.observe(frame)['state'])
        for bounds in ((574,102,134,42),(525,158,168,28)):
            damaged=frame.copy()
            x,y,w,h=bounds
            damaged[y:y+h,x:x+w]=0
            self.assertEqual('unknown',self.recognizer.observe(damaged)['state'])
        dark=(frame.astype(np.float32)*.55).astype(np.uint8)
        shifted=cv2.warpAffine(frame,np.float32([[1,0,-8],[0,1,0]]),(1280,720))
        for invalid in (dark,shifted):
            self.assertEqual('unknown',self.recognizer.observe(invalid)['state'])

    def test_result_only_reuses_strict_old_and_live38_result_frames(self):
        for name in ('result_defeat','result_defeat_code38_42','result_defeat_code38_43'):
            with self.subTest(name=name):
                observation=self.recognizer.observe(self.fixture(name),result_only=True)
                self.assertEqual('result_defeat',observation['state'])
                self.assertTrue(observation['evidence']['defeat_banner']['ok'])
                self.assertTrue(observation['evidence']['result_controls']['ok'])
                self.assertEqual({},observation['targets'])

    def test_result_only_rejects_real_battle_network_queue_and_menu_frames(self):
        for row in self.manifest['fixtures']:
            if row['state']=='result_defeat':
                continue
            with self.subTest(row['id']):
                frame=cv2.imread(str(Path(FIXTURES)/row['file']))
                self.assertEqual('unknown',self.recognizer.observe(frame,result_only=True)['state'])

    def test_result_only_requires_complete_result_controls_around_text(self):
        base=self.fixture('result_defeat_code38_42')
        for bounds in ((1065,29,187,3),(1065,70,187,3),(1065,29,3,44),
                       (1249,29,3,44),(618,670,43,24)):
            with self.subTest(bounds=bounds):
                frame=base.copy()
                x,y,w,h=bounds
                frame[y:y+h,x:x+w]=0
                self.assertEqual('unknown',self.recognizer.observe(frame,result_only=True)['state'])
        # Exact source-template pixels would pass the old text-only rule.
        frame=np.zeros_like(base)
        x,y,w,h=self.recognizer.specs['defeat_banner']['bounds']
        frame[y:y+h,x:x+w]=self.recognizer.templates['defeat_banner']
        self.assertEqual('result_defeat',self.recognizer.observe(frame)['state'])
        self.assertEqual('unknown',self.recognizer.observe(frame,result_only=True)['state'])

    def test_result_only_preserves_darkness_and_positional_refusals(self):
        base=self.fixture('result_defeat_code38_42')
        dark=(base.astype(np.float32)*.55).astype(np.uint8)
        shifted=cv2.warpAffine(base,np.float32([[1,0,8],[0,1,0]]),(1280,720))
        for frame in (dark,shifted,np.zeros_like(base)):
            self.assertEqual('unknown',self.recognizer.observe(frame,result_only=True)['state'])

    def test_popups_require_both_independent_anchors(self):
        for name,anchors in (
                ('task_popup',('task_title','task_subtitle')),
                ('pass_popup',('pass_title','pass_close')),
                ('box_popup',('box_title','box_close')),
                ('store_popup',('store_title','store_close'))):
            for anchor in anchors:
                with self.subTest(name,anchor=anchor):
                    frame=self.fixture(name)
                    x,y,w,h=self.recognizer.specs[anchor]['bounds']
                    frame[y:y+h,x:x+w]=0
                    self.assertEqual('unknown',self.recognizer.observe(frame)['state'])

    def test_store_popup_dismisses_only_its_observed_close(self):
        # Third startup promotion: taller panel with its own title block and
        # close slot. Its close X is not the pass/box slot and vice versa.
        frame=self.fixture('store_popup')
        observation=self.recognizer.observe(frame)
        self.assertEqual('store_popup',observation['state'])
        close=list(self.recognizer.specs['store_close']['bounds'])
        self.assertEqual({'menu_dismiss_store':close},observation['targets'])
        self.assertNotEqual(list(self.recognizer.specs['pass_close']['bounds']),close)
        for other in ('pass_popup','box_popup'):
            with self.subTest(other):
                source=self.fixture(other)
                altered=frame.copy()
                x,y,w,h=self.recognizer.specs['store_title']['bounds']
                altered[y:y+h,x:x+w]=source[y:y+h,x:x+w]
                self.assertNotEqual('store_popup',self.recognizer.observe(altered)['state'])

    def test_store_close_alone_is_not_a_menu_authority(self):
        frame=self.fixture('home')
        live=self.fixture('store_popup')
        x,y,w,h=self.recognizer.specs['store_close']['bounds']
        frame[y:y+h,x:x+w]=live[y:y+h,x:x+w]
        observation=self.recognizer.observe(frame)
        self.assertNotEqual('store_popup',observation['state'])
        self.assertNotIn('menu_dismiss_store',observation['targets'])

    def test_task_progress_is_not_required_for_dismiss(self):
        frame=self.fixture('task_popup')
        frame[160:185,700:745]=0
        observation=self.recognizer.observe(frame)
        self.assertEqual('task_popup',observation['state'])
        self.assertEqual({'menu_dismiss_task':[890,585,32,30]},observation['targets'])

    def test_daily_reward_variants_use_separate_observed_anchors(self):
        # Both observed variants share login_title. The press-anywhere form
        # carries 继续, the unclaimed form carries the golden 领取 cell; each
        # anchor alone must decide, and zeroing the other anchor must not
        # degrade the recognised state or its dismiss target.
        claim=list(self.recognizer.specs['login_claim']['bounds'])
        self.assertEqual(list(self.recognizer.specs['login_continue']['bounds']),claim)
        for name,anchor in (('login','login_continue'),('login_claim_variant','login_claim')):
            with self.subTest(name):
                frame=self.fixture(name)
                observation=self.recognizer.observe(frame)
                self.assertEqual('login_reward',observation['state'])
                self.assertEqual({'menu_dismiss_reward':claim},observation['targets'])
                x,y,w,h=self.recognizer.specs[anchor]['bounds']
                frame[y:y+h,x:x+w]=0
                self.assertEqual('unknown',self.recognizer.observe(frame)['state'])

    def test_claim_anchor_alone_is_not_a_menu_authority(self):
        # The live frame this anchor was cut from no longer contains an
        # unclaimed cell, so the label alone must never produce a reward state.
        frame=self.fixture('home')
        live=cv2.imread(str(Path(FIXTURES)/'login_claim_variant.png'))
        x,y,w,h=self.recognizer.specs['login_claim']['bounds']
        frame[y:y+h,x:x+w]=live[y:y+h,x:x+w]
        observation=self.recognizer.observe(frame)
        self.assertNotEqual('login_reward',observation['state'])
        self.assertNotIn('menu_dismiss_reward',observation['targets'])

    def test_promotion_close_alone_is_not_a_menu_authority(self):
        frame=self.fixture('home')
        popup=self.fixture('pass_popup')
        x,y,w,h=self.recognizer.specs['pass_close']['bounds']
        frame[y:y+h,x:x+w]=popup[y:y+h,x:x+w]
        self.assertEqual('home',self.recognizer.observe(frame)['state'])

    def test_offer_requires_exact_title_x_and_all_four_complete_edges(self):
        for popup in ('airdrop','starter','weekend'):
            for suffix in ('title','close','edge_top','edge_bottom','edge_left','edge_right'):
                with self.subTest(popup=popup,suffix=suffix):
                    frame=self.fixture(popup+'_popup')
                    x,y,w,h=self.recognizer.specs[popup+'_'+suffix]['bounds']
                    frame[y:y+h,x:x+w]=0
                    observation=self.recognizer.observe(frame)
                    self.assertEqual('unknown',observation['state'])
                    self.assertEqual({},observation['targets'])

    def test_offer_title_and_x_without_panel_cannot_authorize_dismiss(self):
        for popup in ('airdrop','starter','weekend'):
            for background in ('home','deck_list','ready_casual','decoration','decoration_hq','battle'):
                with self.subTest(popup=popup,background=background):
                    frame=self.fixture(background)
                    source=self.fixture(popup+'_popup')
                    for suffix in ('title','close'):
                        x,y,w,h=self.recognizer.specs[popup+'_'+suffix]['bounds']
                        frame[y:y+h,x:x+w]=source[y:y+h,x:x+w]
                    observation=self.recognizer.observe(frame)
                    self.assertNotIn(observation['state'],('airdrop_popup','starter_popup','weekend_popup'))
                    self.assertFalse(set(observation['targets']) & {'menu_dismiss_airdrop','menu_dismiss_starter','menu_dismiss_weekend'})

    def test_offer_close_on_real_menu_and_card_art_cannot_authorize_dismiss(self):
        for popup in ('airdrop','starter','weekend'):
            for background in ('home','card_collection','decoration','decoration_hq','battle'):
                with self.subTest(popup=popup,background=background):
                    frame=self.fixture(background)
                    source=self.fixture(popup+'_popup')
                    x,y,w,h=self.recognizer.specs[popup+'_close']['bounds']
                    frame[y:y+h,x:x+w]=source[y:y+h,x:x+w]
                    observation=self.recognizer.observe(frame)
                    self.assertNotIn(observation['state'],('airdrop_popup','starter_popup','weekend_popup'))
                    self.assertFalse(set(observation['targets']) & {'menu_dismiss_airdrop','menu_dismiss_starter','menu_dismiss_weekend'})

    def test_offer_anchor_positions_must_describe_one_coherent_panel(self):
        for popup in ('airdrop','starter','weekend'):
            with self.subTest(popup):
                frame=self.fixture(popup+'_popup')
                x,y,w,h=self.recognizer.specs[popup+'_close']['bounds']
                crop=frame[y:y+h,x:x+w].copy()
                frame[y:y+h,x-3:x+w]=0
                frame[y:y+h,x-3:x-3+w]=crop
                observation=self.recognizer.observe(frame)
                for suffix in ('title','close','edge_top','edge_bottom','edge_left','edge_right'):
                    self.assertTrue(observation['evidence'][popup+'_'+suffix]['ok'])
                self.assertFalse(observation['evidence'][popup+'_panel']['ok'])
                self.assertEqual({},observation['targets'])

    def test_offer_coherent_small_panel_shift_preserves_observed_x_target(self):
        for popup in ('airdrop','starter','weekend'):
            with self.subTest(popup):
                frame=self.fixture(popup+'_popup')
                shifted=cv2.warpAffine(frame,np.float32([[1,0,2],[0,1,1]]),(1280,720))
                observation=self.recognizer.observe(shifted)
                self.assertEqual(popup+'_popup',observation['state'])
                self.assertEqual({'menu_dismiss_'+popup:[940,203,25,25]},observation['targets'])

    def test_offer_countdown_and_price_are_not_close_authority(self):
        for popup in ('airdrop','starter','weekend'):
            with self.subTest(popup):
                frame=self.fixture(popup+'_popup')
                frame[218:234,340:410]=0
                frame[455:490,335:420]=0
                observation=self.recognizer.observe(frame)
                self.assertEqual(popup+'_popup',observation['state'])
                self.assertEqual({'menu_dismiss_'+popup:[938,202,25,25]},observation['targets'])

    def test_deck_name_and_art_do_not_gate_detail_recognition(self):
        frame=self.fixture('ready_casual')
        frame[165:400,1090:1240]=0
        self.assertEqual('deck_ready',self.recognizer.observe(frame)['state'])

    def test_first_slot_supports_other_nation_card_art(self):
        frame=self.fixture('deck_list')
        for source_x in (588,817,1047):
            with self.subTest(source_x):
                altered=frame.copy()
                altered[87:337,358:535]=frame[87:337,source_x:source_x+177]
                altered[337:406,358:535]=0
                observed=self.recognizer.observe(altered)
                self.assertEqual('deck_list',observed['state'])
                self.assertEqual([358,87,177,250],observed['targets']['menu_select_deck'])

    def test_clipped_or_empty_first_slot_is_not_a_card(self):
        frame=self.fixture('deck_list')
        for edge in ('top','bottom','left','right','whole'):
            with self.subTest(edge):
                altered=frame.copy()
                x,y,w,h={'top':(358,87,177,10),'bottom':(358,326,177,11),
                         'left':(358,97,9,229),'right':(525,97,10,229),
                         'whole':(358,87,177,250)}[edge]
                altered[y:y+h,x:x+w]=40
                observation=self.recognizer.observe(altered)
                self.assertEqual('menu_transition',observation['state'])
                self.assertEqual({},observation['targets'])
                self.assertFalse(observation['start_control']['ok'])
        altered=frame.copy()
        altered[87:337,358:535]=40
        cv2.rectangle(altered,(359,88),(533,335),(200,200,200),1)
        observation=self.recognizer.observe(altered)
        self.assertEqual('menu_transition',observation['state'])
        self.assertEqual({},observation['targets'])

    def test_selected_and_unselected_start_slots_are_distinguished(self):
        for name,variant,state in (('home','unselected','home'),
                 ('card_collection','unselected','card_collection'),
                 ('selected_deck_list','selected','deck_list')):
            with self.subTest(name):
                observation=self.recognizer.observe(self.fixture(name))
                self.assertEqual(state,observation['state'])
                self.assertTrue(observation['start_control']['ok'])
                self.assertTrue(observation['start_control']['visible'])
                self.assertEqual(variant,observation['start_control']['variant'])

    def test_live_transition_has_visible_control_but_no_click_authority(self):
        observation=self.recognizer.observe(self.fixture('selected_deck_transition'))
        self.assertEqual('menu_transition',observation['state'])
        self.assertEqual('first_deck_not_ready',observation['reason'])
        self.assertEqual({},observation['targets'])
        self.assertFalse(observation['action_ready'])
        self.assertFalse(observation['start_control']['ok'])
        self.assertTrue(observation['start_control']['visible'])
        self.assertEqual('selected',observation['start_control']['variant'])
        self.assertEqual(0.,observation['evidence']['first_deck_frame']['edges']['top'])
        self.assertEqual(0.,observation['evidence']['first_deck_frame']['edges']['bottom'])

    def test_selected_start_icon_without_menu_context_is_not_authority(self):
        selected=self.fixture('selected_deck_list')
        x,y,w,h=self.recognizer.specs['home_play_selected']['bounds']
        for name in ('battle','decoration','decoration_hq','result_defeat'):
            with self.subTest(name):
                altered=self.fixture(name)
                altered[y:y+h,x:x+w]=selected[y:y+h,x:x+w]
                observation=self.recognizer.observe(altered)
                self.assertFalse(observation['start_control']['ok'])
                self.assertFalse(observation['start_control']['visible'])
                self.assertNotIn(observation['state'],('home','deck_list','mode_menu','menu_transition'))
                self.assertEqual({},observation['targets'])

    def test_transition_needs_all_three_observed_menu_anchors(self):
        source=self.fixture('selected_deck_transition')
        for anchor in ('battle_selected','training_unselected','home_play_selected'):
            with self.subTest(anchor):
                altered=source.copy()
                x,y,w,h=self.recognizer.specs[anchor]['bounds']
                altered[y:y+h,x:x+w]=0
                observation=self.recognizer.observe(altered)
                self.assertEqual('unknown',observation['state'])
                self.assertFalse(observation['start_control']['ok'])
                self.assertEqual({},observation['targets'])

    def test_selector_gray_cannot_select(self):
        frame=self.fixture('ready_casual')
        x,y,w,h=self.recognizer.specs['selector_casual']['bounds']
        gray=cv2.cvtColor(frame[y:y+h,x:x+w],cv2.COLOR_BGR2GRAY)
        frame[y:y+h,x:x+w]=cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR)
        self.assertEqual('unknown',self.recognizer.observe(frame)['state'])

    def test_both_modes_orange_rejected(self):
        frame=self.fixture('ready_casual')
        ranked=self.fixture('ready_ranked')
        x,y,w,h=self.recognizer.specs['selector_casual']['bounds']
        frame[y:y+h,x:x+w//2]=ranked[y:y+h,x:x+w//2]
        self.assertEqual('unknown',self.recognizer.observe(frame)['state'])

    def test_missing_background_mode_rejected(self):
        frame=self.fixture('ready_casual')
        x,y,w,h=self.recognizer.specs['detail_battle']['bounds']
        frame[y:y+h,x:x+w]=0
        self.assertEqual('unknown',self.recognizer.observe(frame)['state'])

    def test_black_and_bad_dimensions(self):
        for frame in (None,np.zeros((720,1280,3),np.uint8),np.zeros((1080,1920,3),np.uint8)):
            self.assertEqual('unknown',self.recognizer.observe(frame)['state'])


def self_check(assets_dir,fixtures_dir):
    global ASSETS,FIXTURES
    ASSETS,FIXTURES=str(assets_dir),str(fixtures_dir)
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (FlowTests,RunTests,PixelTests)])
    output=io.StringIO()
    result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
    return json.dumps({'passed':result.wasSuccessful(),'tests_run':result.testsRun,'device_inputs':0,
        'failures':len(result.failures),'errors':len(result.errors),'details':output.getvalue()})


if __name__=='__main__':
    import sys
    result=self_check(sys.argv[1],sys.argv[2])
    print(result)
    raise SystemExit(0 if json.loads(result)['passed'] else 1)
