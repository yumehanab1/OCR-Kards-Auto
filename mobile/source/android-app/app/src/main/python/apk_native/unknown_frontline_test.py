"""Bounded unknown-frontline ending, with independent fake captures and receipts."""
import copy
import json
import tempfile
from unittest import mock

from .action_request import request
from .end_audit import audit,UnknownFrontlineRecheck,unknown_frontline_skip_ready
from .executor import ActionExecutor


def run():
    checks=[]
    def check(name,value):
        if not value:raise AssertionError(name)
        checks.append(dict(name=name,passed=True))
    actors=[dict(state='orange',type='infantry',card=dict(cx=400,cy=500),row='support')]
    observed=dict(state='battle',source_shape=[720,1280,3],choice_modal=False,
        card_display=dict(ready=False),turn_preparation=dict(ready=True),
        scene=dict(frontline={'owner':'unknown'},support_full_confirmed=True,cards=[]),
        support_probe=dict(coverage_candidate=True),combat=dict(actors=actors,options=[dict(kind='pending',reason='frontline_unknown')]),
        plan=dict(action='skip_deploy',reason='four_support_units_observed'),
        page=dict(state='battle',evidence={'end_turn_btn':dict(score=.99,bounds=[1100,500,140,40])}))
    def packet(fid=1,captured=1000,**changes):
        return dict(ok=True,coordinate_space='source_pixels',frame_id=fid,captured_elapsed_ms=captured,
                    foreground_generation=7,source_width=1280,source_height=720,**changes)
    def source(fid=1,captured=1000,**changes):
        p=packet(fid,captured);p.update(changes);return p
    raw=audit(observed,lambda action:True,allow_local_unknown=True)
    check('current_other_conditions_pass_but_frontline_remains_unknown',raw['ready'] is False
          and raw['frontline_recheck_eligible'] and raw['reason']=='ready_actor_frontline_unconfirmed')
    strict=audit(observed,lambda action:True)
    check('strict_audit_not_globally_relaxed',strict==dict(ready=False,reason='frontline_unknown'))

    def seed(counter=None):
        counter=counter or UnknownFrontlineRecheck()
        counter.observe(raw,source(1,1000),7,1100)
        second=counter.observe(raw,source(2,1800),7,1900)
        return counter,second

    counter,second=seed()
    check('two_frames_cannot_skip',not second['ready'])
    evidence=counter.observe(raw,source(3,2600),7,2700)
    check('third_independent_frame_after_span_can_skip',evidence['ready'] and unknown_frontline_skip_ready(evidence,source(3,2600)))
    check('unknown_never_becomes_exhausted_or_known',evidence['unresolved_frontline_skipped']
          and evidence['reason']=='bounded_unknown_frontline_skipped' and not evidence.get('current_frame_exhausted')
          and not evidence.get('stable_pair') and observed['scene']['frontline']['owner']=='unknown')
    counter=UnknownFrontlineRecheck()
    for now in (1100,1500,2000,3000):current=counter.observe(raw,source(),7,now)
    check('reused_same_frame_never_adds_samples',len(counter.samples)==1 and not current['ready'])
    counter=UnknownFrontlineRecheck()
    for fid,t in ((1,1000),(2,1100),(3,1200)):current=counter.observe(raw,source(fid,t),7,t+100)
    check('near_duplicate_frames_not_independent',len(counter.samples)==1 and not current['ready'])
    counter.observe(raw,source(4,1800),7,1900)
    current=counter.observe(raw,source(5,2600),7,2700)
    check('near_duplicates_do_not_move_first_time_anchor',current['ready'] and current['frontline_recheck']['samples'][0]['frame_id']==1)
    counter=UnknownFrontlineRecheck()
    for fid,t in ((1,1000),(2,1250),(3,1500)):current=counter.observe(raw,source(fid,t),7,t+100)
    check('minimum_gap_alone_does_not_replace_total_span',len(counter.samples)==3 and not current['ready'])
    current=counter.observe(raw,source(4,2500),7,2600)
    check('exact_span_boundary_accepted',current['ready'] and current['frontline_recheck']['capture_span_ms']==1500)

    for name,changes,turn in [('turn',{},8),('generation',dict(foreground_generation=8),7),
                              ('width',dict(source_width=1400),7),('height',dict(source_height=800),7)]:
        counter,_=seed();current=counter.observe(raw,source(3,2600,**changes),turn,2700)
        check(name+'_change_resets_window',not current['ready'] and len(counter.samples)==1)
    for name,p,now in [('expired',source(3,2600),5601),('future',source(3,2600),2599),
                       ('old_frame_id',source(1,2600),2700),('same_frame_new_time',source(2,2600),2700),
                       ('backwards_time',source(3,1700),1800),('normalized',source(3,2600,coordinate_space='normalized_1280x720'),2700),
                       ('invalid_generation',source(3,2600,foreground_generation=-1),2700)]:
        counter,_=seed();current=counter.observe(raw,p,7,now)
        check(name+'_cannot_complete_window',not current['ready'] and not counter.samples)

    cases=[('choice_not_ready',lambda o:o.update(choice_modal=True,choice_evidence=dict(ready=False))),
           ('card_display',lambda o:o['card_display'].update(ready=True)),
           ('draw_unsettled',lambda o:o['turn_preparation'].update(ready=False)),
           ('opponent_turn',lambda o:o.update(state='opponent_turn')),
           ('missing_end',lambda o:o['page'].update(evidence={})),
           ('weak_end',lambda o:o['page']['evidence']['end_turn_btn'].update(score=.82)),
           ('deploy_available',lambda o:o.update(plan=dict(action='deploy',grab_source=[400,660]))),
           ('combat_available',lambda o:o['combat']['options'].append(dict(kind='attack_hq',unit=actors[0],target=dict(cx=640,cy=120))))]
    for name,change in cases:
        counter,_=seed();bad=copy.deepcopy(observed);change(bad)
        refusal=audit(bad,lambda action:True,allow_local_unknown=True)
        current=counter.observe(refusal,source(3,2600),7,2700)
        check(name+'_blocks_skip_and_clears_window',not current['ready'] and not counter.samples
              and not refusal.get('frontline_recheck_eligible'))
    counter,_=seed();known=copy.deepcopy(observed);known['scene']['frontline']['owner']='enemy'
    current=counter.observe(audit(known,lambda a:True,allow_local_unknown=True),source(3,2600),7,2700)
    check('known_frontline_returns_to_normal_audit',current['ready'] and not current.get('unresolved_frontline_skipped') and not counter.samples)

    ready=copy.deepcopy(observed);ready['selected_action']=dict(action='end_turn_verified',end_turn_evidence=dict(evidence,frame_id=3))
    plan=request(ready,source(3,2600),2700,20000)
    check('bounded_proof_uses_current_end_control',plan['context']=='end_turn' and plan['from']==[1170.,520.])
    mutations=[('missing_samples',lambda e:e['frontline_recheck'].pop('samples')),
               ('last_frame_changed',lambda e:e['frontline_recheck']['samples'][-1].update(frame_id=99)),
               ('generation_changed',lambda e:e['frontline_recheck']['samples'][0].update(foreground_generation=8)),
               ('duplicate_frame',lambda e:e['frontline_recheck']['samples'][1].update(frame_id=1)),
               ('fake_span',lambda e:e['frontline_recheck'].update(capture_span_ms=9999)),
               ('fake_count',lambda e:e['frontline_recheck'].update(sample_count=99)),
               ('fake_exhausted',lambda e:e.update(current_frame_exhausted=True)),
               ('fake_stable_pair',lambda e:e.update(stable_pair=True)),
               ('missing_skip_flag',lambda e:e.pop('unresolved_frontline_skipped')),
               ('stale_control',lambda e:e['control'].update(bounds=[1000,500,140,40]))]
    for name,change in mutations:
        bad=copy.deepcopy(ready);change(bad['selected_action']['end_turn_evidence'])
        try:request(bad,source(3,2600),2700,20000)
        except ValueError:check(name+'_request_rejected',True)
        else:raise AssertionError(name)

    class Bridge:
        def __init__(self):self.now=1100;self.requests=[];self.events=[]
        def elapsedRealtime(self):return self.now
        def isCancelled(self):return False
        def emit(self,value):self.events.append(json.loads(value))
        def dispatch(self,value):self.requests.append(json.loads(value));return json.dumps(dict(accepted=True,completed=True))
    with tempfile.TemporaryDirectory(prefix='unknown-frontline-') as directory:
        b=Bridge();executor=ActionExecutor(b,None,None,directory,50000,20);executor.shape=(720,1280,3);executor.turn=7
        for fid,t in ((1,1000),(2,1800),(3,2600)):
            current=copy.deepcopy(observed);b.now=t+100
            allowed=executor.audit_end_candidate(current,source(fid,t))
            check('executor_candidate_'+str(fid),allowed==(fid==3))
        check('executor_skip_has_no_exhaustion_claim',current['selected_action']['end_turn_evidence'].get('unresolved_frontline_skipped')
              and not current['selected_action']['end_turn_evidence'].get('current_frame_exhausted'))
        executor.execute(current,source(3,2600))
        check('actual_end_still_requires_completed_receipt_then_pending_transition',len(b.requests)==1
              and executor.report['game_inputs']==1 and executor.end_ledger.pending is not None
              and executor.report['end_turns_confirmed']==0 and not executor.frontline_recheck.samples)
        info=dict(source(4,3100),state='in_game',button=None,button_present=False,choice_modal=False,
                  opponent_turn_label=dict(present=True,box=[1130,500,60,30]))
        executor.settle_end(executor.end_ledger.observe(info,3200,7))
        check('one_opponent_frame_still_not_success',executor.report['end_turns_confirmed']==0)
        executor.settle_end(executor.end_ledger.observe(dict(info,frame_id=5,captured_elapsed_ms=3600),3700,7))
        check('independent_end_confirmation_unchanged',executor.report['end_turns_confirmed']==1)
        for name,change in cases:
            b=Bridge();executor=ActionExecutor(b,None,None,directory,50000,20);executor.shape=(720,1280,3);executor.turn=7
            executor.frontline_recheck,_=seed();bad=copy.deepcopy(observed);change(bad)
            executor.last_id=3;executor.last_capture_time=2600;executor.foreground_generation=7;b.now=2700
            executor.ready_observation=(bad,source(3,2600))
            result=executor.take_ready_observation()
            check(name+'_reused_frame_does_not_carry_old_counter',not executor.frontline_recheck.samples
                  and (result is None or result[0]['selected_action']['action'] in ('attack_hq','deploy')))
    return dict(passed=True,check_count=len(checks),checks=checks,device_inputs=0,activity_launches=0,
                original_unknown_ledger_unchanged=True)
