"""Current turn controls before template sweeps; no captures or gestures."""
import copy,json
import cv2
import numpy as np
from .fast_page import FastPage
from .turn_ui import current_turn_control,end_control
from .ocr_bridge import NativeOCR


def run():
    checks=[]
    def check(name,valid):
        if not valid:raise AssertionError(name)
        checks.append(name)
    def row(text,x=1088,y=479,w=142,h=44,score=.94):
        return dict(text=text,score=score,box=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]])
    frame=np.full((720,1280,3),24,np.uint8)
    cv2.putText(frame,'TURN',(1090,511),cv2.FONT_HERSHEY_SIMPLEX,.8,(210,210,210),2)
    cv2.putText(frame,'WIN',(570,435),cv2.FONT_HERSHEY_SIMPLEX,1.4,(230,230,230),3)
    cv2.putText(frame,'GO',(605,678),cv2.FONT_HERSHEY_SIMPLEX,1.1,(230,230,230),2)
    own=row('结束回合');enemy=row('敌方',1100,479,70,35)
    check('current_own_text_box',current_turn_control(frame,[own])['bounds']==[1088.,479.,142.,44.])
    check('current_enemy_text_box',current_turn_control(frame,[enemy])['state']=='opponent_turn')
    check('point_93_is_valid',current_turn_control(frame,[dict(own,score=.93)]) is not None)
    for label,rows in [('below_threshold',[dict(own,score=.929)]),('duplicate_own',[own,own]),
                       ('duplicate_enemy',[enemy,enemy]),('conflict',[own,enemy]),
                       ('left_caption',[row('结束回合',60)]),('outside_source',[row('结束回合',1250)]),
                       ('bottom_caption',[row('结束回合',1088,680)]),
                       ('nonfinite',[dict(own,box=[[float('nan'),479],[1230,479],[1230,523],[1088,523]])])]:
        check(label+'_refused',current_turn_control(frame,rows) is None)
    class Clock:
        value=0.
        def __call__(self):return self.value
    class Engine:
        supports_turn_controls=True
        def __init__(self,turn,result=None):self.turn=turn;self.result=result or [];self.requests=[];self.full_calls=0
        def __call__(self,image):self.full_calls+=1;raise AssertionError('unrelated_full_frame_ocr')
        def regions(self,image,regions,scope):
            self.requests.append(dict(scope=scope,regions=regions))
            rows=self.turn if scope=='turn_controls' else self.result
            return [(r['box'],r['text'],r['score']) for r in rows],0
    class Detector:
        def __init__(self,result=False):self.locations={};self.mode='filtered';self.matches=[];self.result=result
        def observe(self,image,features=None):raise AssertionError('unrelated_full_detector')
        def match(self,gray,name):
            self.matches.append(name)
            if name=='victory_btn' and self.result:return dict(score=.99,ok=True,bounds=[560,390,160,60])
            return dict(score=.20,ok=False,bounds=[560,390,160,60])
    def make(turn,result=None):
        clock=Clock();engine=Engine(turn,result);page=FastPage(engine,{},clock=clock)
        page.shape=frame.shape;page.detector=Detector()
        return clock,engine,page
    for state,label in [('battle',own),('opponent_turn',enemy)]:
        clock,engine,page=make([label]);observed=page.observe(frame)
        check(state+'_current_scoped_path',observed['state']==state and observed['path']=='current_scoped_turn_control')
        check(state+'_avoids_whole_page_ocr_and_detector',engine.full_calls==0
              and [r['scope'] for r in engine.requests]==['turn_controls']
              and all(name in ('defeat_banner','defeat_btn','victory_btn') for name in page.detector.matches))
        check(state+'_partial_not_full_result_inventory','turn_ocr_items' in observed and 'ocr_items' not in observed)
        check(state+'_single_bounded_roi',len(engine.requests[0]['regions'])==1)
        key='ocr_turn_control' if state=='battle' else 'ocr_opponent_control'
        check(state+'_current_control_attached',observed[key]['score']==label['score'])
        if state=='battle':check('end_gate_accepts_current_scoped_control',end_control(observed) is not None)
    result=[row('胜利',560,390,160,60),row('继续',600,645,80,42)]
    clock,engine,page=make([own],result);clock.value=5.;observed=page.observe(frame)
    check('partial_turn_text_does_not_block_due_result_probe',observed['state']=='result_victory'
          and observed['result_proof']['ready'] and [r['scope'] for r in engine.requests]==['turn_controls','result_controls'])
    clock,engine,page=make([own]);page.detector.result=True;observed=page.observe(frame)
    check('current_result_overlay_has_priority_over_turn_control',observed['state']=='result_victory'
          and observed['result_proof']['ready'] and engine.full_calls==0)
    clock,engine,page=make([own]);first=page.observe(frame);second=page.observe(frame)
    check('learned_turn_crop_uses_current_pixels_without_second_ocr',second['state']=='battle'
          and second['path']=='current_frame_local_label' and len(engine.requests)==1)

    normalized=np.asarray(own['box'],dtype=float);source_box=(normalized*1.8).tolist()
    packet=dict(frame_id=43,captured_elapsed_ms=178965,foreground_generation=5,source_width=2304,source_height=1296,
                png_path='/current/00043.png',coordinate_space='source_pixels')
    class Bridge:
        def __init__(self):self.request=None;self.change={};self.ok=True
        def recognizeNativeText(self,encoded):
            self.request=json.loads(str(encoded))
            response=dict(self.request,ok=self.ok,scope='turn_controls',width=2304,height=1296,
                          items=[dict(own,box=source_box,score_available=True)])
            response.update(self.change);return json.dumps(response)
    bridge=Bridge();ocr=NativeOCR(bridge);ocr.bind(packet)
    regions=[[768,230,512,432]];found,_=ocr.regions(frame,regions,scope='turn_controls')
    check('one_point_eight_source_coordinates_restored',np.allclose(found[0][0],normalized))
    check('one_point_eight_roi_sent_in_source_pixels',bridge.request['ocr_regions']==[[1382,414,922,778]])
    check('current_source_identity_preserved',all(bridge.request[k]==v for k,v in packet.items()))
    for key,value in [('frame_id',42),('foreground_generation',4),('source_width',2303),('png_path','/old.png'),('scope','result_controls')]:
        bridge.change={key:value}
        try:ocr.regions(frame,regions,scope='turn_controls');rejected=False
        except ValueError:rejected=True
        check('mismatched_'+key+'_refused',rejected)
    bridge.change={};bridge.ok=False
    check('unavailable_turn_ocr_does_not_reuse_previous_items',ocr.regions(frame,regions,scope='turn_controls')[0]==[])
    try:ocr.regions(frame,regions*2,scope='turn_controls');rejected=False
    except ValueError:rejected=True
    check('multiple_turn_regions_refused',rejected)
    return dict(passed=True,checks=checks,scope='generated_current_turn_controls_and_source_bridge',device_inputs=0,captures=0)


if __name__=='__main__':print(json.dumps(run(),ensure_ascii=True))
