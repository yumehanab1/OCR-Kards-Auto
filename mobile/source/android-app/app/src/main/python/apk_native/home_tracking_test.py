"""Current lobby controls are re-read, not cached observations or input authority."""
import json
import cv2
import numpy as np
from .fast_page import FastPage


def run():
    checks=[]
    def check(name,value):
        if not value:raise AssertionError(name)
        checks.append(name)
    random=np.random.default_rng(166)
    frame=np.zeros((720,1280,3),np.uint8)
    boxes={'home_play':[60,180,40,32],'home_tasks':[600,600,48,24]}
    needles={}
    for name,(x,y,w,h) in boxes.items():
        image=random.integers(10,245,(h,w),dtype=np.uint8)
        needles[name]=image
        frame[y:y+h,x:x+w]=image[:,:,None]
    class Engine:
        supports_turn_controls=True
        def __init__(self):self.calls=0
        def regions(self,*args,**kwargs):self.calls+=1;return [],0
        def __call__(self,*args):self.calls+=1;return [],0
    class Detector:
        def __init__(self):
            self.locations={};self.scaled={};self.calls=0;self.next='home'
        def observe(self,image,features=None):
            self.calls+=1
            evidence={n:dict(score=.98,bounds=list(b),factor=1.,ok=True) for n,b in boxes.items()}
            self.locations.update(evidence)
            self.scaled.update({(n,720,1.):v for n,v in needles.items()})
            return dict(state=self.next,evidence=evidence,plan={'action':None})
    def make():
        page=FastPage(Engine(),{});page.detector=Detector();overlays=[]
        page.inspect_result_overlays=lambda *args:(overlays.append(True) or ({},None))
        return page,overlays
    page,overlays=make()
    first=page.observe(frame)
    check('initial_home_requires_full_detector',first['state']=='home' and page.detector.calls==1)
    check('initial_control_ocr_kept',page.engine.calls==1)
    second=page.observe(frame.copy())
    check('current_two_controls_shortcut',second['path']=='current_home_controls' and second['state']=='home')
    check('no_full_detector_or_turn_ocr_for_reconfirmed_home',page.detector.calls==1 and page.engine.calls==1)
    check('current_result_overlays_still_checked',len(overlays)==1)
    check('never_executable_input_authority',second['plan']['dispatch']=='offline_only' and not second.get('executable'))
    check('source_pixels_unchanged',np.array_equal(frame[180:212,60:100,0],needles['home_play']))
    moved=np.zeros_like(frame)
    for name,(x,y,w,h) in boxes.items():moved[y+5:y+5+h,x+7:x+7+w]=needles[name][:,:,None]
    current=page.observe(moved)
    check('new_pixels_relocate_both_controls',all(current['evidence'][n]['bounds'][:2]==[b[0]+7,b[1]+5] for n,b in boxes.items()))
    for name in boxes:
        page,_=make();page.observe(frame)
        changed=frame.copy();x,y,w,h=boxes[name];changed[y:y+h,x:x+w]=0
        page.detector.next='unknown';miss=page.observe(changed)
        check(name+'_missing_falls_back',page.detector.calls==2 and miss['state']=='unknown' and not page.home_tracking)
    page,_=make();page.observe(frame);page.home_tracking=False
    check('locations_alone_do_not_establish_home',page.current_home(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)) is None)
    page,_=make();page.observe(frame);page.detector.locations['home_tasks']['score']=.92
    check('both_previous_proposals_require_strong_score',page.current_home(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)) is None)
    page,_=make();page.observe(frame);page.detector.scaled.clear()
    check('missing_template_fails_closed',page.current_home(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)) is None)
    page,_=make();page.observe(frame)
    page.inspect_result_overlays=lambda *args:({},dict(state='result_victory',result_proof={'ready':True}))
    result=page.observe(frame)
    check('current_result_overrides_home',result['state']=='result_victory' and not page.home_tracking)
    page,_=make();page.observe(frame);page.detector.next='unknown'
    page.observe(np.zeros((800,1280,3),np.uint8))
    check('shape_change_invalidates_home',page.detector.calls==2 and not page.home_tracking)
    return dict(passed=True,checks=checks,scope='synthetic current-frame lobby tracking, no device execution',device_inputs=0)


if __name__=='__main__':print(json.dumps(run(),ensure_ascii=True))
