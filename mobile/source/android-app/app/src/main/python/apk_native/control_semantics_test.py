"""Opening/turn controls independent of unrelated board landmarks; no input."""
import copy,json
from unittest import mock
import numpy as np
from .opening import OpeningRecognizer,text_button
from .turn_ui import structural_end,end_control

def run(assets):
    frame=np.zeros((720,1280,3),np.uint8);checks=[]
    def row(text,box,score=.95):
        x,y,w,h=box
        return dict(text=text,score=score,box=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]])
    labels=[row('选择要替换的卡牌',[460,60,360,40]),row('确认',[610,630,60,30])]
    def check(name,value):
        if not value:raise AssertionError(name)
        checks.append(name)
    result=text_button(frame,labels,False)
    check('opening_no_resources_or_button_border',result is not None and result['bounds']==[610,630,60,30])
    check('opening_missing_title',text_button(frame,labels[1:],False) is None)
    check('opening_missing_confirm',text_button(frame,labels[:1],False) is None)
    check('opening_duplicate_confirm',text_button(frame,labels+[labels[1]],False) is None)
    bad=copy.deepcopy(labels);bad[1]['score']=.89
    check('opening_low_confidence',text_button(frame,bad,False) is None)
    class OCR:
        def regions(self,image,regions):return [(r['box'],r['text'],r['score']) for r in labels],0
    packet=dict(coordinate_space='source_pixels',source_width=1280,source_height=720)
    with mock.patch('apk_native.resource_anchors.inspect',return_value=dict(ok=False)):
        observed=OpeningRecognizer(assets).observe(frame,packet,OCR())
    check('resource_failure_reaches_dynamic_controls',observed['phase']=='MULLIGAN_CONFIRM'
          and observed.get('resources') is False and observed['target_bounds']==[610,630,60,30])
    turn=[row('结束回合',[1080,400,100,28])]
    control=structural_end(frame,turn)
    check('turn_label_needs_no_four_border_checks',control is not None and control['bounds']==[1080.,400.,100.,28.])
    check('battle_accepts_measured_ocr_control',end_control(dict(state='battle',ocr_turn_control=control))==control)
    check('opponent_state_cannot_use_own_control',end_control(dict(state='opponent_turn',ocr_turn_control=control)) is None)
    check('conflicting_current_turn_labels',structural_end(frame,turn+[row('敌方',[1100,430,60,25])]) is None)
    check('turn_label_on_left_not_button',structural_end(frame,[row('结束回合',[100,400,100,28])]) is None)
    check('turn_duplicate_label',structural_end(frame,turn+turn) is None)
    return json.dumps(dict(passed=True,checks=checks,device_inputs=0,captures=0))
