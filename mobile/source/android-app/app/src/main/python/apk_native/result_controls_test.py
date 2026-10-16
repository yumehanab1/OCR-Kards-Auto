"""Result title/continue semantics, current pixels and independent frame checks."""
import copy,json
import cv2
import numpy as np
from .result import ResultRecognizer
from .fast_page import FastPage
from .text_semantics import classify_text
from .runtime import ResultProof


def run():
    checks=[]
    def check(name,valid):
        if not valid:raise AssertionError(name)
        checks.append(name)
    def row(text,x,y,w,h,score=.91):
        return dict(text=text,score=score,box=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]])
    frame=np.full((720,1280,3),25,np.uint8)
    cv2.putText(frame,'WIN',(575,435),cv2.FONT_HERSHEY_SIMPLEX,1.4,(220,220,220),3)
    cv2.putText(frame,'GO',(605,677),cv2.FONT_HERSHEY_SIMPLEX,1.,(220,220,220),2)
    items=[row('胜利',570,395,145,55),row('继续',600,645,75,42)]
    class OCR:
        def __init__(self,items):self.items=copy.deepcopy(items);self.calls=0
        def __call__(self,frame):
            self.calls+=1
            return [(r['box'],r['text'],r['score']) for r in self.items],0
        def regions(self,frame,regions,scope='result_controls'):return self(frame)
    def page(items=None,score=.84):
        value=dict(state='result_victory',evidence={'victory_btn':dict(score=score,ok=score>=.82,bounds=[565,390,155,65])})
        if items is not None:value['ocr_items']=copy.deepcopy(items)
        return value
    def proof(items,source=frame):return ResultRecognizer().inspect(source,page(items),OCR(items))
    result=proof(items)
    check('title_continue_without_view_is_sufficient',result['ready'])
    check('low_nineties_ocr_does_not_require_point_98',classify_text(items)[0]=='result_victory')
    prefix=[items[0],dict(items[1],text='继续查看奖励')]
    check('current_continue_prefix_does_not_need_saved_glyph',proof(prefix)['ready'])
    check('weak_continue_prefix_refused',not proof([items[0],dict(prefix[1],score=.89)])['ready'])
    check('duplicate_continue_prefix_refused',not proof(prefix+[copy.deepcopy(prefix[1])])['ready'])
    defeat=[dict(items[0],text='失败'),items[1]]
    check('defeat_title_continue_is_sufficient',classify_text(defeat)[0]=='result_defeat'
          and ResultRecognizer().inspect(frame,dict(page(defeat),state='result_defeat'),OCR(defeat))['ready'])
    for name,text in [('title','胜利'),('continue','继续')]:
        check('missing_'+name+'_refused',not proof([r for r in items if r['text']!=text])['ready'])
        weak=[dict(r,score=.89) if r['text']==text else r for r in items]
        check('below_point_90_'+name+'_refused',not proof(weak)['ready'])
        duplicate=items+[copy.deepcopy(next(r for r in items if r['text']==text))]
        check('duplicate_'+name+'_refused',not proof(duplicate)['ready'])
    optional=items+[row('查看战场',0,0,60,25,.10)]
    check('unrelated_view_geometry_and_score_do_not_block',proof(optional)['ready'])
    conflict=items+[row('失败',575,460,100,40,.91)]
    check('conflicting_result_titles_refused',not proof(conflict)['ready'] and classify_text(conflict)[0]=='unknown')
    check('conflicting_current_ocr_refuses_strong_template',not ResultRecognizer().inspect(frame,page(conflict,.99),OCR(conflict))['ready'])
    check('continue_must_be_below_title',not proof([items[0],row('继续',600,200,75,42)])['ready'])
    check('result_must_be_central',not proof([row('胜利',50,395,145,55),items[1]])['ready'])
    check('outside_source_box_refused',not proof([items[0],row('继续',1250,645,75,42)])['ready'])
    check('weak_template_geometry_cannot_veto_current_text',ResultRecognizer().inspect(frame,
          dict(page(items),evidence={'victory_btn':dict(score=.84,ok=True,bounds=[0,0,50,30])}),OCR(items))['ready'])
    engine=OCR(items);recognizer=ResultRecognizer()
    observed=page();dynamic=recognizer.inspect(frame,observed,engine)
    check('weak_candidate_gets_current_ocr',dynamic['ready'] and engine.calls==1)
    tracked=recognizer.inspect(frame,page(),engine)
    check('cached_labels_check_current_pixels',tracked['ready'] and tracked['basis']=='two_current_local_result_labels' and engine.calls==1)
    erased=frame.copy();erased[390:455,565:720]=25;engine.items=[]
    check('changed_current_pixels_cannot_reuse_old_result',not recognizer.inspect(erased,page(),engine)['ready'] and engine.calls==2)
    strong_ocr=OCR([])
    check('strong_template_fast_path_avoids_ocr',ResultRecognizer().inspect(frame,page(score=.95),strong_ocr)['ready'] and strong_ocr.calls==0)
    class Detector:
        def __init__(self,state='unknown'):self.locations={};self.state=state
        def observe(self,source,features=None):return dict(state=self.state,evidence={
            'end_turn_btn':dict(score=.84,ok=True,bounds=[1050,420,120,35])},plan={})
    engine=OCR(items);fast=FastPage(engine,{})
    fast.detector=Detector();current=fast.observe(frame)
    check('unknown_fastpage_reaches_dynamic_two_control_result',current['state']=='result_victory' and current['result_proof']['ready'] and engine.calls==1)
    own=[row('结束回合',1060,435,140,32,.94)]
    engine=OCR(own);fast=FastPage(engine,{});fast.detector=Detector('battle')
    strengthened=fast.observe(frame)
    check('weak_battle_candidate_reaches_current_ocr',strengthened['state']=='battle' and engine.calls==1
          and strengthened['ocr_turn_control']['bounds']==[1060.,435.,140.,32.])
    from .turn_ui import end_control
    check('current_ocr_control_authorizes_current_action',end_control(strengthened) is not None)
    engine=OCR([]);fast=FastPage(engine,{});fast.detector=Detector('battle')
    no_control=fast.observe(frame)
    check('weak_battle_without_current_control_not_cached',no_control['state']=='unknown' and not fast.labels)
    engine=OCR(items);fast=FastPage(engine,{});fast.detector=Detector('battle')
    result_over_weak=fast.observe(frame)
    check('result_over_weak_battle_uses_same_single_ocr',result_over_weak['state']=='result_victory'
          and result_over_weak['result_proof']['ready'] and engine.calls==1)
    packet=dict(frame_id=1,captured_elapsed_ms=1000,foreground_generation=3,source_width=1280,source_height=720)
    result_proof=ResultProof()
    check('one_current_result_frame_does_not_complete',not result_proof.observe(dict(state='result_victory',page=current),packet))
    check('two_independent_result_frames_complete',result_proof.observe(dict(state='result_victory',page=current),dict(packet,frame_id=2,captured_elapsed_ms=1600)))
    for label,changed in [('same_frame',dict(frame_id=1,captured_elapsed_ms=1600)),
                          ('generation',dict(frame_id=2,captured_elapsed_ms=1600,foreground_generation=4)),
                          ('source_shape',dict(frame_id=2,captured_elapsed_ms=1600,source_width=1920)),
                          ('too_close',dict(frame_id=2,captured_elapsed_ms=1100)),
                          ('too_far',dict(frame_id=2,captured_elapsed_ms=7000))]:
        result_proof=ResultProof();result_proof.observe(dict(state='result_victory',page=current),packet)
        check(label+'_pair_refused',not result_proof.observe(dict(state='result_victory',page=current),dict(packet,**changed)))
    return dict(passed=True,checks=checks,scope='generated_result_title_and_continue',device_inputs=0,captures=0)


if __name__=='__main__':print(json.dumps(run(),ensure_ascii=False))
