"""Current post-input frame reuse with fake clocks/receipts and no device APIs."""
import copy
import json
import tempfile
from pathlib import Path
from unittest import mock

from apk_battle_runtime import Stop, Replan
from .executor import ActionExecutor


def run():
    checks=[]

    def check(name,condition):
        if not condition:raise AssertionError(name)
        checks.append(dict(name=name,passed=True))

    class Bridge:
        def __init__(self,reply=None):
            self.now=1200;self.cancelled=False;self.events=[];self.requests=[]
            self.reply=reply if reply is not None else dict(accepted=True,completed=True)
        def elapsedRealtime(self):return self.now
        def deadlineElapsedRealtime(self):return 100000
        def isCancelled(self):return self.cancelled
        def emit(self,value):self.events.append(json.loads(value))
        def dispatch(self,value):
            self.requests.append(json.loads(value))
            return json.dumps(self.reply)

    packet=dict(ok=True,frame_id=9,captured_elapsed_ms=1000,foreground_generation=7,
                source_width=1280,source_height=720,coordinate_space='source_pixels')
    observed=dict(state='battle',source_shape=[720,1280,3],
                  scene=dict(frontline={'owner':'empty'},cards=[],support_full_confirmed=False),
                  support_probe=dict(coverage_candidate=True,vacancy_candidate=True),
                  hand=[],combat=dict(actors=[],options=[]),
                  plan=dict(action='skip_deploy',reason='all_observed_fee_numerals_unavailable'),
                  page=dict(state='battle',evidence={'end_turn_btn':dict(score=.99,bounds=[1100,500,140,40])}),
                  turn_preparation=dict(ready=True,local_vacancy_skip_ready=True),
                  selected_action=dict(action='end_turn_verified',end_turn_evidence=dict(ready=False)))

    with tempfile.TemporaryDirectory(prefix='native-executor-reuse-') as directory:
        def make(obs=None,pkt=None,reply=None):
            bridge=Bridge(reply);executor=ActionExecutor(bridge,None,None,directory,50000,20)
            executor.shape=(720,1280,3);executor.last_id=9;executor.last_capture_time=1000
            executor.foreground_generation=7
            executor.ready_observation=(copy.deepcopy(obs or observed),dict(pkt or packet))
            return bridge,executor

        bridge,executor=make()
        with mock.patch.object(executor.turn_preparation,'observe',side_effect=AssertionError('Duplicate preparation sample')):
            reused=executor.take_ready_observation()
        check('current_postcondition_can_end_turn',reused[0]['selected_action']['action']=='end_turn_verified')
        evidence=reused[0]['selected_action']['end_turn_evidence']
        check('end_turn_audit_rebuilt_for_current_frame',evidence['ready'] and evidence['current_frame_exhausted'] and evidence['frame_id']==9)
        check('reuse_is_one_shot',executor.take_ready_observation() is None)
        check('reuse_has_no_capture_or_input',executor.report['captures']==0 and not bridge.requests)
        event=next(x['value'] for x in bridge.events if x['kind']=='postcondition_frame_reused')
        check('reuse_reports_final_end_turn_action',event['action']=='end_turn_verified' and event['frame_id']==9)
        check('replanned_evidence_saved',Path(directory,'native-replanned-000009.json').is_file())

        executor.execute(*reused)
        check('end_turn_dispatch_retains_real_source_coordinates',len(bridge.requests)==1 and bridge.requests[0]['context']=='end_turn'
              and bridge.requests[0]['from']==[1170.,520.] and bridge.requests[0]['foreground_generation']==7)
        check('completed_end_turn_stays_pending',executor.report['game_inputs']==1 and executor.end_ledger.pending is not None
              and executor.report['end_turns_confirmed']==0)
        executor.ready_observation=reused
        check('consumed_reused_frame_never_dispatches_twice',executor.take_ready_observation() is None and len(bridge.requests)==1)
        proof=dict(packet,state='in_game',button=None,button_present=False,
                   opponent_turn_label=dict(present=True,box=[1130,500,60,30]),choice_modal=False)
        executor.settle_end(executor.end_ledger.observe(dict(proof,frame_id=10,captured_elapsed_ms=1500),1500,0))
        check('single_opponent_frame_does_not_confirm_end',executor.report['end_turns_confirmed']==0)
        executor.settle_end(executor.end_ledger.observe(dict(proof,frame_id=11,captured_elapsed_ms=2000),2000,0))
        check('independent_opponent_pair_still_required',executor.report['end_turns_confirmed']==1 and executor.end_ledger.pending is None)

        deployment=dict(observed,plan=dict(action='deploy',grab_source=[400,660],drop_source=[448,497]),
                        selected_action=dict(action='deploy',grab_source=[400,660],drop_source=[448,497]))
        bridge,executor=make(deployment)
        executor.isolated.append(('deploy',[400,660]))
        reused=executor.take_ready_observation()
        check('isolated_card_is_reselected_as_current_end_turn',reused[0]['selected_action']['action']=='end_turn_verified'
              and reused[0]['end_turn_audit']['deployment_basis']=='current_card_isolated_after_completed_touch')
        bridge,executor=make(deployment);executor.failed_deploys=2
        reused=executor.take_ready_observation()
        check('latest_failed_deploy_budget_is_reaudited',reused[0]['end_turn_audit']['deployment_basis']=='same_turn_two_failed_deploys')

        option=dict(kind='attack_hq',unit=dict(card=dict(cx=500,cy=400)),target=dict(cx=640,cy=120))
        changed=copy.deepcopy(observed);changed['combat']['options']=[option]
        bridge,executor=make(changed);reused=executor.take_ready_observation()
        check('remaining_actor_wins_over_old_end_turn_selection',reused[0]['selected_action']['action']=='attack_hq'
              and 'end_turn_audit' not in reused[0])

        for name,change in (
                ('current_end_control_missing',lambda x:x['page'].update(evidence={})),
                ('current_end_control_weak',lambda x:x['page']['evidence']['end_turn_btn'].update(score=.82)),
                ('draw_not_settled',lambda x:x['turn_preparation'].update(ready=False)),
                ('central_card_display',lambda x:x.update(card_display={'ready':True})),
                ('choice_modal',lambda x:x.update(choice_modal=True)),
                ('not_own_turn',lambda x:x.update(state='opponent_turn'))):
            bad=copy.deepcopy(observed);change(bad);bridge,executor=make(bad)
            check('reuse_rejects_'+name,executor.take_ready_observation() is None and not bridge.requests)

        for key,value in (('frame_id',8),('captured_elapsed_ms',999),('foreground_generation',8),
                          ('source_width',1400),('source_height',800)):
            bridge,executor=make(pkt=dict(packet,**{key:value}))
            check('reuse_rejects_mismatched_'+key,executor.take_ready_observation() is None and not bridge.requests)
        for now in (999,4001):
            bridge,executor=make();bridge.now=now
            check('reuse_rejects_frame_age_'+str(now),executor.take_ready_observation() is None)
        bridge,executor=make();bridge.now=4000
        check('existing_three_second_boundary_preserved',executor.take_ready_observation() is not None)
        bridge,executor=make();executor.end_ledger.pending={'test':True}
        check('pending_end_turn_blocks_reuse',executor.take_ready_observation() is None)
        for name,change in (('cancelled',lambda b:setattr(b,'cancelled',True)),('time_budget',lambda b:setattr(b,'now',50000))):
            bridge,executor=make();change(bridge)
            try:executor.take_ready_observation()
            except Stop as error:check('reuse_stops_'+name,str(error)==name)
            else:raise AssertionError(name)

        # An immutable before-frame gap cannot be repaired by polling more after frames.
        # Exercise production executor accounting with one real fake receipt and one new frame.
        for kind in ('deploy','attack_unit'):
            before=copy.deepcopy(deployment if kind=='deploy' else observed)
            if kind=='attack_unit':
                combat=dict(kind='attack_unit',unit=dict(card=dict(cx=500,cy=400)),
                            target=dict(cx=640,cy=300,guard_state='not_guard'))
                before['selected_action']=dict(action='attack_unit',combat_plan=combat)
            bridge,executor=make(before);executor.ready_observation=None;captured=[]
            def capture():
                bridge.now+=500;captured.append(10)
                executor.last_id=10;executor.last_capture_time=bridge.now
                return copy.deepcopy(observed),dict(packet,frame_id=10,captured_elapsed_ms=bridge.now)
            with mock.patch.object(executor,'capture',side_effect=capture), \
                    mock.patch('apk_native.executor.time.sleep'), \
                    mock.patch('apk_native.executor.sequence_postcondition',return_value=dict(
                        confirmed=False,status='uncovered',reason='fixed_before_uncovered')):
                effect=executor.execute(before,packet)
            check(kind+'_uncovered_stops_after_one_current_post_frame',len(captured)==1 and len(bridge.requests)==1
                  and not effect['confirmed'] and executor.report['actions_confirmed']==0)
            check(kind+'_uncovered_preserves_unknown_and_actor_isolation',executor.report['unconfirmed_inputs']==1
                  and not executor.allow(before['selected_action']) and executor.failed_deploys==(1 if kind=='deploy' else 0))

        for reply in (dict(accepted=False,completed=False,reason='frame_age_expired'),
                      dict(accepted=True,completed=False,reason='gesture_cancelled')):
            bridge,executor=make(reply=reply);reused=executor.take_ready_observation()
            with mock.patch.object(executor,'capture',side_effect=AssertionError('Bad receipt cannot confirm')):
                try:executor.execute(*reused)
                except (Stop,Replan):pass
                else:raise AssertionError('Bad receipt accepted')
            check('reuse_keeps_receipt_boundary_'+str(reply['accepted']),len(bridge.requests)==1
                  and executor.report['end_turns_confirmed']==0 and executor.end_ledger.pending is None)

        from . import runtime
        class RuntimeExecutor(ActionExecutor):
            def __init__(self,bridge,*args):
                super().__init__(bridge,*args)
                self.shape=(720,1280,3);self.last_id=9;self.last_capture_time=1000;self.foreground_generation=7
                self.ready_observation=(copy.deepcopy(observed),dict(packet))
            def capture(self):
                self.bridge.now+=500;self.report['captures']+=1
                return dict(state='result_defeat',page={'evidence':{'defeat_btn':{'score':.99}}}), \
                    dict(packet,frame_id=9+self.report['captures'],captured_elapsed_ms=self.bridge.now)
        bridge=Bridge()
        with mock.patch.object(runtime,'ActionExecutor',RuntimeExecutor), \
                mock.patch.object(runtime,'load_banks',return_value=({},{})), \
                mock.patch.object(runtime,'Pipeline'),mock.patch.object(runtime.time,'sleep'):
            summary=json.loads(runtime.run(bridge,'unused','unused','unused',directory,json.dumps(dict(read_only=False))))
        check('runtime_consumes_reused_end_turn_before_another_capture',len(bridge.requests)==1
              and bridge.requests[0]['context']=='end_turn' and summary['captures']==2)
        check('runtime_preserves_result_proof_and_unknown_end_outcome',summary['result_verified']
              and summary['stop_reason']=='result_defeat' and summary['end_turns_confirmed']==0
              and summary['end_turns_unconfirmed']==1)

    return dict(passed=True,check_count=len(checks),checks=checks,device_inputs=0,activity_launches=0,
                production_touch_receipts=False,three_frame_effect_standard_unchanged=True)
