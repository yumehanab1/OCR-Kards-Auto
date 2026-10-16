"""Deterministic result discovery cadence while a current turn label survives."""
import copy,json
import cv2
import numpy as np
from .fast_page import FastPage
from .runtime import ResultProof


def run():
    checks=[]
    def check(name,valid):
        if not valid:raise AssertionError(name)
        checks.append(name)
    class Clock:
        value=0.
        def __call__(self):return self.value
    def row(text,x,y,w,h,score=.94):
        return dict(text=text,score=score,box=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]])
    results=[row('胜利',560,390,160,60),row('继续',600,645,80,42)]
    frame=np.full((720,1280,3),24,np.uint8)
    cv2.putText(frame,'TURN',(1080,450),cv2.FONT_HERSHEY_SIMPLEX,.8,(210,210,210),2)
    cv2.putText(frame,'WIN',(565,435),cv2.FONT_HERSHEY_SIMPLEX,1.5,(230,230,230),3)
    cv2.putText(frame,'GO',(602,679),cv2.FONT_HERSHEY_SIMPLEX,1.1,(230,230,230),2)
    class Engine:
        def __init__(self,items=None):self.items=copy.deepcopy(items or []);self.full_calls=0;self.requests=[]
        def __call__(self,image):
            self.full_calls+=1
            return [(r['box'],r['text'],r['score']) for r in self.items],0
        def regions(self,image,regions,scope):
            self.requests.append(dict(regions=regions,scope=scope))
            return [(r['box'],r['text'],r['score']) for r in self.items],0
    class Detector:
        def __init__(self,state):self.state=state;self.locations={};self.mode='filtered'
        def match(self,gray,name):return dict(score=.20,ok=False,bounds=[560,390,160,60],factor=1.)
        def observe(self,image,features=None):
            name='opponent_standard' if self.state=='opponent_turn' else 'end_turn_btn'
            return dict(state=self.state,evidence={name:dict(score=.96,ok=True,bounds=[1070,420,145,40])},
                        plan=dict(action='wait',reason='current_turn'))
    def make(state='battle',local=True,items=None):
        clock=Clock();engine=Engine(items);page=FastPage(engine,{},clock=clock)
        page.detector=Detector(state);page.shape=frame.shape
        if local:page.cache(frame,state,[1070,420,145,40])
        else:page.local=lambda gray:None
        return clock,engine,page
    for state in ('battle','opponent_turn'):
        for local in (True,False):
            clock,engine,page=make(state,local)
            key=state+('_local' if local else '_full')
            clock.value=4.99;before=page.observe(frame)
            check(key+'_before_interval_avoids_ocr',before['state']==state and not before['ocr_used']
                  and engine.full_calls==0 and not engine.requests)
            clock.value=5.;negative=page.observe(frame)
            check(key+'_due_probes_scoped_once',negative['state']==state and negative['ocr_used']
                  and engine.full_calls==0 and len(engine.requests)==1
                  and engine.requests[0]['scope']=='result_controls' and len(engine.requests[0]['regions'])==3)
            check(key+'_negative_keeps_current_plan',negative['plan']==before['plan'])
            clock.value=5.1;page.observe(frame)
            check(key+'_negative_does_not_probe_every_frame',len(engine.requests)==1)
            clock.value=10.;page.observe(frame)
            check(key+'_next_interval_probes_again',len(engine.requests)==2)
    clock,engine,page=make(items=results)
    clock.value=5.;first=page.observe(frame)
    check('low_result_templates_do_not_block_current_scoped_words',first['state']=='result_victory'
          and first['result_proof']['ready'] and page.pending_result_state=='result_victory'
          and len(engine.requests)==1 and engine.full_calls==0)
    proof=ResultProof();packet=dict(frame_id=1,captured_elapsed_ms=5000,foreground_generation=3,source_width=1280,source_height=720)
    check('first_discovery_is_not_whole_match_confirmation',not proof.observe(dict(state=first['state'],page=first),packet))
    clock.value=5.6;second=page.observe(frame)
    check('pending_result_immediately_checks_next_current_frame',second['state']=='result_victory'
          and second['result_proof']['ready'] and len(engine.requests)==1
          and second['result_proof']['basis']=='two_current_local_result_labels')
    check('independent_result_pair_finishes_without_five_second_delay',proof.observe(dict(state=second['state'],page=second),
          dict(packet,frame_id=2,captured_elapsed_ms=5600)))
    changed=frame.copy();changed[385:455,555:725]=24;engine.items=[]
    clock.value=5.8;miss=page.observe(changed)
    check('changed_current_result_clears_pending',page.pending_result_state is None and miss['state']=='battle'
          and len(engine.requests)==2 and miss['ocr_used'])
    clock.value=6.;page.observe(changed)
    check('failed_pending_does_not_repeat_scoped_ocr',len(engine.requests)==2)
    clock,engine,page=make(items=results);clock.value=5.;page.observe(frame)
    large=cv2.resize(frame,(1920,1080));clock.value=5.5;engine.items=[]
    resized=page.observe(large)
    check('source_shape_change_clears_pending_and_restarts_interval',page.pending_result_state is None
          and resized['state']=='battle' and len(engine.requests)==1)
    own=[row('结束回合',1070,420,145,40,.99)]
    clock,engine,page=make('unknown',False,own);clock.value=5.;current=page.observe(frame)
    check('current_full_ocr_is_reused_without_scoped_duplicate',current['state']=='battle' and engine.full_calls==1 and not engine.requests)
    clock,engine,page=make('unknown',False,results);clock.value=5.;current=page.observe(frame)
    check('full_ocr_result_avoids_additional_scoped_call',current['state']=='result_victory'
          and current['result_proof']['ready'] and engine.full_calls==1 and not engine.requests)
    clock,engine,page=make(items=results+[row('失败',550,460,100,40)])
    clock.value=5.;conflict=page.observe(frame)
    check('conflicting_current_titles_keep_turn_and_no_pending',conflict['state']=='battle' and page.pending_result_state is None)
    clock,engine,page=make(items=results[:1]);clock.value=5.;missing=page.observe(frame)
    check('title_without_continue_keeps_turn',missing['state']=='battle' and page.pending_result_state is None)
    for state in ('battle','opponent_turn'):
        for local in (True,False):
            clock,engine,page=make(state,local,results);clock.value=5.;found=page.observe(frame)
            check(state+('_local' if local else '_full')+'_semantic_result_overrides_surviving_turn',
                  found['state']=='result_victory' and found['result_proof']['ready']
                  and len(engine.requests)==1 and engine.full_calls==0)
    class Strong(Detector):
        def observe(self,image,features=None):
            return dict(state='result_victory',evidence={'victory_btn':dict(score=.99,ok=True,bounds=[560,390,160,60])},plan={})
    clock,engine,page=make(local=False);page.detector=Strong('result_victory')
    first=page.observe(frame);clock.value=5.1;second=page.observe(frame)
    check('strong_template_pair_keeps_zero_ocr_fast_path',first['result_proof']['ready']
          and second['result_proof']['ready'] and engine.full_calls==0 and not engine.requests
          and page.pending_result_state is None)
    current=dict(state='result_victory',page={'result_proof':{'ready':True}})
    def packet_at(frame_id,elapsed,**changes):
        packet=dict(frame_id=frame_id,captured_elapsed_ms=elapsed,foreground_generation=3,
                    source_width=1280,source_height=720)
        packet.update(changes)
        return packet
    proof=ResultProof()
    check('fast_pair_first_frame_anchors',not proof.observe(current,packet_at(1,1000)))
    check('fast_pair_second_250ms_frame_keeps_first_anchor',not proof.observe(current,packet_at(2,1250))
          and proof.previous[1]['frame_id']==1)
    check('fast_pair_third_frame_confirms_500ms_independent_pair',proof.observe(current,packet_at(3,1500)))
    proof=ResultProof();proof.observe(current,packet_at(5,1000))
    check('duplicate_frame_cannot_supply_second_proof',not proof.observe(current,packet_at(5,1500)))
    check('reverse_frame_cannot_supply_second_proof',not proof.observe(current,packet_at(4,1600)))
    check('duplicate_and_reverse_frames_keep_valid_anchor',proof.previous[1]['frame_id']==5
          and proof.observe(current,packet_at(6,1700)))
    for identity,value in (('foreground_generation',4),('source_width',1920),('source_height',1080)):
        proof=ResultProof();proof.observe(current,packet_at(1,1000))
        changed=packet_at(2,1600);changed[identity]=value
        check(identity+'_change_does_not_form_pair',not proof.observe(current,changed)
              and proof.previous[1][identity]==value)
        next_frame=dict(changed,frame_id=3,captured_elapsed_ms=1900)
        check(identity+'_new_identity_forms_its_own_pair',proof.observe(current,next_frame))
    proof=ResultProof();proof.observe(current,packet_at(1,1000))
    defeat=dict(state='result_defeat',page={'result_proof':{'ready':True}})
    check('different_result_state_reanchors_without_pair',not proof.observe(defeat,packet_at(2,1600))
          and proof.previous[0]=='result_defeat')
    check('different_state_requires_own_independent_pair',proof.observe(defeat,packet_at(3,1900)))
    proof=ResultProof();proof.observe(current,packet_at(1,1000))
    conflict=dict(state='result_victory',page={'result_proof':{'ready':False,'reason':'conflicting_current_result_labels'}})
    check('conflicting_result_observation_clears_anchor',not proof.observe(conflict,packet_at(2,1500))
          and proof.previous is None)
    check('result_after_conflict_is_only_first_proof',not proof.observe(current,packet_at(3,1800)))
    check('post_conflict_independent_result_pair_can_confirm',proof.observe(current,packet_at(4,2100)))
    proof=ResultProof();proof.observe(current,packet_at(1,1000))
    check('timeout_frame_reanchors_without_pair',not proof.observe(current,packet_at(2,6001))
          and proof.previous[1]['frame_id']==2)
    check('timeout_reanchor_still_enforces_minimum_gap',not proof.observe(current,packet_at(3,6251)))
    check('timeout_new_pair_uses_reanchored_capture',proof.observe(current,packet_at(4,6501)))
    proof=ResultProof();proof.observe(current,packet_at(1,1000))
    check('reverse_capture_time_reanchors_without_pair',not proof.observe(current,packet_at(2,800))
          and proof.previous[1]['captured_elapsed_ms']==800)
    check('reversed_time_new_anchor_needs_separation',not proof.observe(current,packet_at(3,1050)))
    check('reversed_time_new_pair_can_confirm',proof.observe(current,packet_at(4,1300)))
    return dict(passed=True,checks=checks,scope='generated_current_result_probe_cadence',device_inputs=0,captures=0)


if __name__=='__main__':print(json.dumps(run(),ensure_ascii=True))
