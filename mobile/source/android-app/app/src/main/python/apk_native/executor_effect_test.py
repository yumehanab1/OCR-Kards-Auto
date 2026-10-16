"""Local effect sampling and same-original planning, with no device APIs."""
import copy
import hashlib
import json
import tempfile
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from apk_battle_runtime import Replan, Stop
from .executor import ActionExecutor
from .action_request import request


def run():
    checks=[]
    def check(name,condition):
        if not condition:raise AssertionError(name)
        checks.append(dict(name=name,passed=True))

    class OCR:
        def __init__(self):self.bindings=[]
        def bind(self,packet):self.bindings.append(dict(packet))

    full=dict(state='battle',page=dict(state='battle',evidence={
        'end_turn_btn':dict(score=.99,bounds=[1100,500,140,40])}),
        scene=dict(frontline={'owner':'empty'},cards=[],support_observed=2,support_full_confirmed=False),
        support_probe=dict(coverage_candidate=True,vacancy_candidate=True,hq_box=[600,450,80,120],
                           unknown_rectangles=[],unaccounted_edge_fraction=0.),
        hand=[dict(box=[380,620,40,40],orange=True,kind='unit',grab_source=[400,660])],
        combat=dict(actors=[],options=[]),plan=dict(action='deploy',grab_source=[400,660],drop_source=[448,497]),
        selected_action=dict(action='deploy',grab_source=[400,660],drop_source=[448,497]),
        choice_modal=False,choice_evidence=dict(ready=False),card_display=dict(ready=False),
        source_shape=[720,1280,3],coordinate_space='source_pixels',planning_complete=True,
        hand_scanned=True,combat_scanned=True,current_state_key='complete-current-state',timings_ms={})

    class Pipeline:
        def __init__(self,bridge):
            self.bridge=bridge;self.local=[];self.completions=[];self.full_calls=0
            self.full=copy.deepcopy(full);self.token=None;self.fail=None;self.completion_ms=0
            self.page=type('Page',(),dict(detector=None))()
        def observe(self,frame):
            self.full_calls+=1;return copy.deepcopy(self.full)
        observe_turn_ui=observe
        def observe_effect(self,frame,context):
            partial=copy.deepcopy(self.full)
            partial.update(observation_scope='effect_'+context,planning_complete=False,
                hand=None,hand_scanned=False,combat=None,combat_scanned=False,current_state_key=None,
                plan=dict(action='wait',reason='effect_planning_incomplete'),
                selected_action=dict(action='wait',reason='effect_planning_incomplete'))
            if context!='deploy':partial['support_probe']=None
            self.token=partial;self.local.append(context)
            return partial
        def complete_planning(self,frame,partial):
            if partial is not self.token:raise ValueError('effect_planning_cache_miss')
            if self.fail:raise ValueError(self.fail)
            self.token=None;self.completions.append(partial)
            self.bridge.now+=self.completion_ms
            return copy.deepcopy(self.full)

    with tempfile.TemporaryDirectory(prefix='native-executor-effect-') as directory:
        root=Path(directory).resolve()
        frame=np.zeros((720,1280,3),np.uint8)
        raw=cv2.imencode('.png',frame)[1].tobytes()
        class Bridge:
            def __init__(self):
                self.now=1000;self.index=100;self.cancelled=False;self.requests=[];self.events=[]
            def elapsedRealtime(self):return self.now
            def isCancelled(self):return self.cancelled
            def emit(self,value):self.events.append(json.loads(value))
            def captureNative(self):
                self.now+=650;self.index+=1
                return json.dumps(packet_for(self.index,self.now))
            def dispatch(self,value):
                self.requests.append(json.loads(value))
                return json.dumps(dict(accepted=True,completed=True))

        def packet_for(index,captured):
            path=root/('frame-%06d.png'%index);path.write_bytes(raw)
            return dict(ok=True,png_path=str(path),frame_id=index,captured_elapsed_ms=captured,
                foreground_generation=7,source_width=1280,source_height=720,width=1280,height=720,
                coordinate_space='source_pixels')
        def source_for(packet):
            return dict(path=packet['png_path'],sha256=hashlib.sha256(raw).hexdigest(),
                shape=[720,1280,3],frame_id=packet['frame_id'],elapsed_ms=packet['captured_elapsed_ms'])
        def make():
            bridge=Bridge();pipeline=Pipeline(bridge);ocr=OCR()
            executor=ActionExecutor(bridge,pipeline,ocr,root,50000,20)
            executor.shape=(720,1280,3);executor.foreground_generation=7
            executor.last_id=100;executor.last_capture_time=1000;executor.previous_state='battle'
            executor.turn_preparation.ready=True
            return bridge,pipeline,executor
        def local_ready():
            bridge,pipeline,executor=make()
            observed,packet=executor.capture_effect('deploy')
            executor.ready_observation=(observed,packet)
            return bridge,pipeline,executor,observed,packet

        bridge,pipeline,executor=make()
        with mock.patch('apk_native.executor.select',side_effect=AssertionError('Partial selection')), \
                mock.patch.object(executor.turn_preparation,'observe',side_effect=AssertionError('Partial preparation')), \
                mock.patch.object(executor,'resume_current_state',side_effect=AssertionError('Partial resume')), \
                mock.patch.object(executor,'audit_end_candidate',side_effect=AssertionError('Partial audit')):
            partial,packet=executor.capture_effect('deploy')
        check('local_capture_skips_all_planning_state_machines',pipeline.local==['deploy'] and not pipeline.completions)
        check('unscanned_hand_is_not_empty_hand',partial['hand'] is None and partial['hand_scanned'] is False)
        check('unscanned_combat_and_identity_remain_unknown',partial['combat'] is None and partial['current_state_key'] is None)
        check('local_capture_retains_effect_board_and_complete_support',partial['scene']['support_observed']==2
              and partial['support_probe']['coverage_candidate'])
        check('local_frame_has_real_source_metadata',partial['source']==source_for(packet) and executor.report['captures']==1)
        check('local_capture_context_is_scoped',executor.effect_capture_context is None)
        check('direct_partial_audit_is_rejected',executor.audit_end_candidate(partial,packet) is False)
        check('direct_partial_resume_is_rejected',executor.resume_current_state(partial,packet,True,{'ready':True}) is False)
        try:executor.execute(partial,packet)
        except Replan as error:check('direct_partial_execute_is_rejected',str(error)=='effect_planning_incomplete' and not bridge.requests)
        else:raise AssertionError('Partial dispatched')
        for action in ('deploy','end_turn_verified'):
            bad=copy.deepcopy(full);bad['planning_complete']=False
            bad['selected_action']['action']=action
            try:request(bad,packet,bridge.now,50000)
            except ValueError as error:
                check('request_rejects_partial_even_with_forged_'+action,str(error)=='native_action_requires_complete_planning')
            else:raise AssertionError('Partial request accepted')

        executor.ready_observation=(partial,packet)
        with mock.patch.object(executor.turn_preparation,'observe',wraps=executor.turn_preparation.observe) as preparation:
            reused=executor.take_ready_observation()
        check('last_partial_is_completed_once_before_selection',pipeline.completions==[partial]
              and reused[0]['selected_action']['action']=='deploy')
        check('completion_preserves_new_hand_and_current_state_identity',reused[0]['hand']==full['hand']
              and reused[0]['current_state_key']=='complete-current-state')
        check('completion_adds_exactly_one_full_preparation_sample',preparation.call_count==1)
        check('completion_reuses_exact_source_without_capture_or_input',reused[1]==packet and reused[0]['source']==partial['source']
              and executor.report['captures']==1 and not bridge.requests)
        check('completion_does_not_modify_partial_effect_record',partial['hand'] is None and partial['planning_complete'] is False)
        planning=json.loads((root/('native-planning-%06d.json'%packet['frame_id'])).read_text(encoding='utf8'))
        event=next(event['value'] for event in bridge.events if event['kind']=='effect_planning_completed')
        check('complete_planning_has_independent_record_and_turn',planning['packet']==packet
              and planning['observation']['source']==partial['source'] and planning['planning_turn']==executor.turn
              and event['record_file']=='native-planning-%06d.json'%packet['frame_id']
              and event['planning_turn']==executor.turn and event['turn']==executor.turn)
        check('completed_reuse_is_one_shot',executor.take_ready_observation() is None and len(pipeline.completions)==1)

        bridge,pipeline,executor,partial,packet=local_ready()
        with mock.patch.object(executor.turn_preparation,'observe',return_value=dict(ready=False,reason='draw_unsettled')):
            check('unready_complete_observation_does_not_select',executor.take_ready_observation() is None)
        planning=json.loads((root/('native-planning-%06d.json'%packet['frame_id'])).read_text(encoding='utf8'))
        check('unready_complete_observation_still_has_full_evidence',planning['observation']['planning_complete']
              and planning['observation']['hand']==full['hand']
              and planning['observation']['turn_preparation']['ready'] is False)

        bridge,pipeline,executor=make();executor.turn=7
        executor.isolated=[('attack_hq',[500,400])];executor.failed_deploys=2
        executor.failed_inputs=3;executor.report['failed_inputs']=3;executor.same_state_end_attempts=2
        pipeline.full['state']='opponent_turn';pipeline.full['page']['state']='opponent_turn'
        with mock.patch('apk_native.executor.opponent_evidence',return_value=dict(state='in_game',
                opponent_turn_label={'present':True,'box':[1100,500,80,40]},button_present=False)):
            executor.capture_effect('deploy')
        check('real_opponent_observation_keeps_old_epoch_until_own_proof',executor.previous_state=='opponent_turn'
              and executor.turn==7 and executor.last_end_state_key is None)
        pipeline.full['state']='battle';pipeline.full['page']['state']='battle'
        partial,packet=executor.capture_effect('deploy');executor.ready_observation=(partial,packet)
        check('partial_own_frame_does_not_advance_epoch',executor.turn==7 and executor.previous_state=='opponent_turn')
        executor.take_ready_observation()
        check('completed_own_frame_after_opponent_advances_epoch_once',executor.turn==8 and executor.previous_state=='battle')
        check('completed_own_transition_clears_previous_turn_retry_state',not executor.isolated and executor.failed_deploys==0
              and executor.failed_inputs==0 and executor.report['failed_inputs']==0 and executor.same_state_end_attempts==0)
        planning=json.loads((root/('native-planning-%06d.json'%packet['frame_id'])).read_text(encoding='utf8'))
        check('planning_evidence_records_advanced_epoch',planning['planning_turn']==8
              and planning['observation']['planning_turn']==8)
        executor.capture()
        check('following_own_full_frame_does_not_advance_twice',executor.turn==8)
        bridge,pipeline,executor,partial,packet=local_ready();executor.turn=7
        executor.isolated=[('attack_hq',[500,400])];executor.failed_inputs=3
        executor.take_ready_observation()
        check('same_turn_completion_preserves_epoch_and_isolation',executor.turn==7
              and executor.isolated==[('attack_hq',[500,400])] and executor.failed_inputs==3)

        for expected,options in (
                ('attack_hq',[dict(kind='movefront',unit=dict(card=dict(cx=500,cy=450))),
                              dict(kind='attack_hq',unit=dict(card=dict(cx=550,cy=450)),target=dict(cx=640,cy=100))]),
                ('movefront',[dict(kind='movefront',unit=dict(card=dict(cx=500,cy=450)))])):
            bridge,pipeline,executor,partial,packet=local_ready();pipeline.full['combat']['options']=options
            reused=executor.take_ready_observation()
            check('complete_planning_retains_priority_'+expected,reused[0]['selected_action']['action']==expected)

        mutations=(
            ('source_hash_changed',lambda b,p,e,o,k:Path(k['png_path']).write_bytes(b'changed')),
            ('source_frame_changed',lambda b,p,e,o,k:o['source'].update(frame_id=2)),
            ('source_time_changed',lambda b,p,e,o,k:o['source'].update(elapsed_ms=2)),
            ('source_shape_changed',lambda b,p,e,o,k:o['source'].update(shape=[720,1281,3])),
            ('source_path_changed',lambda b,p,e,o,k:o['source'].update(path=str(root/'missing.png'))),
            ('last_frame_changed',lambda b,p,e,o,k:setattr(e,'last_id',999)),
            ('last_capture_time_changed',lambda b,p,e,o,k:setattr(e,'last_capture_time',999)),
            ('foreground_changed',lambda b,p,e,o,k:setattr(e,'foreground_generation',8)),
            ('source_geometry_changed',lambda b,p,e,o,k:setattr(e,'shape',(800,1280,3))),
            ('already_consumed',lambda b,p,e,o,k:e.consumed.add(k['frame_id'])),
            ('expired_before_completion',lambda b,p,e,o,k:setattr(b,'now',k['captured_elapsed_ms']+3001)),
            ('future_capture',lambda b,p,e,o,k:setattr(b,'now',k['captured_elapsed_ms']-1)))
        for name,change in mutations:
            bridge,pipeline,executor,partial,packet=local_ready();change(bridge,pipeline,executor,partial,packet)
            check('reuse_rejects_'+name,executor.take_ready_observation() is None and not pipeline.completions
                  and not bridge.requests)
        for error in ('effect_planning_cache_miss','effect_planning_source_changed'):
            bridge,pipeline,executor,partial,packet=local_ready();pipeline.fail=error
            check('reuse_resamples_after_'+error,executor.take_ready_observation() is None and not bridge.requests)
        for name,change in (
                ('expired_during_completion',lambda b,p:setattr(p,'completion_ms',3001)),
                ('hand_still_unscanned',lambda b,p:p.full.update(hand_scanned=False)),
                ('combat_still_unscanned',lambda b,p:p.full.update(combat_scanned=False)),
                ('hand_still_unknown',lambda b,p:p.full.update(hand=None)),
                ('combat_still_unknown',lambda b,p:p.full.update(combat=None)),
                ('support_still_unknown',lambda b,p:p.full.update(support_probe=None)),
                ('identity_still_unknown',lambda b,p:p.full.update(current_state_key=None)),
                ('planning_still_incomplete',lambda b,p:p.full.update(planning_complete=False)),
                ('geometry_differs',lambda b,p:p.full.update(source_shape=[720,1281,3]))):
            bridge,pipeline,executor,partial,packet=local_ready();change(bridge,pipeline)
            with mock.patch.object(executor.turn_preparation,'observe',side_effect=AssertionError('Invalid completion sampled')):
                reused=executor.take_ready_observation()
            check('reuse_rejects_'+name,reused is None and not bridge.requests)
        for reason in ('cancelled','time_budget'):
            bridge,pipeline,executor,partial,packet=local_ready()
            original=pipeline.complete_planning
            def stop_during(frame,observed):
                complete=original(frame,observed)
                if reason=='cancelled':bridge.cancelled=True
                else:bridge.now=executor.deadline
                return complete
            pipeline.complete_planning=stop_during
            try:executor.take_ready_observation()
            except Stop as error:check('completion_retains_'+reason,str(error)==reason and not bridge.requests)
            else:raise AssertionError(reason)

        for state,overlay in (('opponent_turn',None),('unknown',None),('result_victory',None),
                              ('battle','choice'),('battle','display')):
            bridge,pipeline,executor=make();pipeline.full['state']=state;pipeline.full['page']['state']=state
            if overlay=='choice':pipeline.full.update(choice_modal=True,choice_evidence={'ready':True})
            if overlay=='display':pipeline.full['card_display']={'ready':True}
            with mock.patch('apk_native.executor.opponent_evidence',return_value=None), \
                    mock.patch.object(executor.turn_preparation,'observe',wraps=executor.turn_preparation.observe) as preparation:
                after,_=executor.capture_effect('deploy')
            check('transition_is_full_before_runtime_'+state+'_'+str(overlay),after['planning_complete'] is True
                  and len(pipeline.completions)==1 and preparation.call_count==1)

        for context in ('deploy','move_front','attack_unit'):
            bridge,pipeline,executor=make();after,_=executor.capture_effect(context)
            check('ordinary_context_uses_local_api_'+context,pipeline.local==[context] and after['planning_complete'] is False)
        for context in ('choice_select','end_turn','attack_hq'):
            bridge,pipeline,executor=make();after,_=executor.capture_effect(context)
            check('other_context_keeps_full_path_'+context,not pipeline.local and pipeline.full_calls==1)
        for missing in ('observe_effect','complete_planning'):
            bridge,pipeline,executor=make();setattr(pipeline,missing,None)
            after,_=executor.capture_effect('deploy')
            check('old_pipeline_falls_back_when_missing_'+missing,not pipeline.local and pipeline.full_calls==1)
        bridge,pipeline,executor=make()
        with mock.patch.object(executor,'capture',side_effect=Replan('retry')):
            try:executor.capture_effect('deploy')
            except Replan:pass
        check('capture_error_never_leaks_local_mode',executor.effect_capture_context is None)

        # Exercise the real receipt/source/three-spaced-sample deployment proof
        # using synthetic observations, not device captures or screenshots.
        bridge,pipeline,executor=make();packet=packet_for(100,1000)
        before=copy.deepcopy(full);before['source']=source_for(packet)
        before['scene']['support_observed']=1;before['turn_preparation']={'ready':True}
        with mock.patch('apk_native.executor.time.sleep'):
            effect=executor.execute(before,packet)
        check('local_samples_keep_three_independent_frame_proof',effect['confirmed'] and len(effect['samples'])==3
              and effect['confirmation_window_ms'][-1]-effect['confirmation_window_ms'][0]>=1000)
        check('local_samples_keep_real_completed_receipt',len(bridge.requests)==1 and executor.report['game_inputs']==1
              and executor.report['actions_confirmed']==1 and not pipeline.completions)
        check('effect_pair_records_partial_samples_without_fake_hands',len(pipeline.local)==3
              and executor.ready_observation[0]['hand'] is None)
        reused=executor.take_ready_observation()
        check('next_action_completes_last_original_and_sees_deploy',reused[0]['selected_action']['action']=='deploy'
              and len(pipeline.completions)==1 and executor.report['captures']==3)

    return dict(passed=True,check_count=len(checks),checks=checks,device_inputs=0,host_captures=0,
                source='synthetic_frames_and_fake_bridge',three_frame_effect_standard_unchanged=True,
                frame_age_limit_ms=3000)
