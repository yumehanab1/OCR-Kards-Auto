"""Opponent mulligan waiting is read-only current text, not a battle handoff."""
import copy,json
import numpy as np
from .opening import OpeningRecognizer,opponent_mulligan_wait


def run(assets):
    checks=[]
    def check(name,valid):
        if not valid:raise AssertionError(name)
        checks.append(name)
    def row(text='敌方正在选择起始手牌',score=.96,box=None):
        return dict(text=text,score=score,box=box if box is not None else
                    [[329,310],[951,310],[951,371],[329,371]])
    frame=np.full((720,1280,3),24,np.uint8)
    packet=dict(coordinate_space='source_pixels',source_width=1280,source_height=720)
    class OCR:
        def __init__(self,items):self.items=items;self.calls=0
        def __call__(self,image):
            self.calls+=1
            return [(r['box'],r['text'],r['score']) for r in self.items],0
    def recognizer(opening_score=.20,end_score=.20):
        value=OpeningRecognizer(assets)
        value.source_turn=None;value.source_opening=None
        value.detector.match=lambda gray,name:dict(
            score=opening_score if name.startswith('mulligan_') else end_score if name=='end_turn_btn' else .20,
            ok=False,bounds=[1060,435,145,32] if name=='end_turn_btn' else [500,50,80,30],factor=1.)
        return value
    def observe(items,**kwargs):
        ocr=OCR(items)
        return recognizer(**kwargs).observe(frame,packet,ocr),ocr.calls
    waiting,calls=observe([row()])
    check('current_central_caption_is_waiting',waiting['phase']=='WAITING_OPPONENT_MULLIGAN')
    check('waiting_has_no_click_target',waiting['target_bounds'] is None and bool(waiting['template_id']))
    check('waiting_uses_current_confidence_and_bounds',waiting['score']==.96 and waiting['wait_label']['bounds']==[329.,310.,622.,61.])
    check('waiting_needs_no_extra_ocr',calls==1)
    check('waiting_does_not_require_resources',waiting['resources'] is False)
    check('confidence_boundary_is_supported',observe([row(score=.90)])[0]['phase']=='WAITING_OPPONENT_MULLIGAN')
    check('spacing_does_not_change_exact_caption',observe([row(text='敌方 正在选择 起始手牌')])[0]['phase']=='WAITING_OPPONENT_MULLIGAN')
    for label,text in [('wrong_owner','我方正在选择起始手牌'),('different_caption','敌方正在选择起手牌'),
                       ('extended_caption','敌方正在选择起始手牌请等待')]:
        check(label+'_rejected',observe([row(text=text)])[0]['phase']=='UNKNOWN')
    for label,score in [('weak',.899),('nan',float('nan')),('infinite',float('inf'))]:
        check(label+'_confidence_rejected',observe([row(score=score)])[0]['phase']=='UNKNOWN')
    check('duplicate_caption_is_ambiguous',observe([row(),row()])[0]['phase']=='UNKNOWN')
    for label,box in [
        ('hand_region',[[329,610],[951,610],[951,671],[329,671]]),
        ('top_region',[[329,40],[951,40],[951,101],[329,101]]),
        ('left_caption',[[0,310],[400,310],[400,371],[0,371]]),
        ('out_of_frame',[[-1,310],[951,310],[951,371],[-1,371]]),
        ('nan_point',[[329,310],[951,310],[951,float('nan')],[329,371]]),
        ('zero_width',[[640,310],[640,310],[640,371],[640,371]]),
        ('collinear',[[329,310],[530,330],[731,350],[932,370]]),
        ('wrong_point_shape',[[329,310,1],[951,310,1],[951,371,1],[329,371,1]]),
        ('non_numeric',[['bad',310],[951,310],[951,371],[329,371]])]:
        check(label+'_rejected',opponent_mulligan_wait(frame,[row(box=box)]) is None)
    enemy=dict(text='敌方',score=.96,box=[[1100,435],[1170,435],[1170,467],[1100,467]])
    end=dict(text='结束回合',score=.96,box=[[1060,435],[1205,435],[1205,467],[1060,467]])
    check('waiting_precedes_semantic_enemy_handoff',observe([row(),enemy])[0]['phase']=='WAITING_OPPONENT_MULLIGAN')
    check('waiting_precedes_semantic_own_handoff',observe([row(),end])[0]['phase']=='WAITING_OPPONENT_MULLIGAN')
    earlier,calls=observe([row(),end],opening_score=.80,end_score=.95)
    check('existing_full_ocr_wait_precedes_template_handoff',earlier['phase']=='WAITING_OPPONENT_MULLIGAN' and calls==1)
    value=recognizer();ocr=OCR([row()])
    check('first_current_frame_waits',value.observe(frame,packet,ocr)['phase']=='WAITING_OPPONENT_MULLIGAN')
    ocr.items=[enemy]
    check('waiting_is_not_cached_into_next_frame',value.observe(frame,packet,ocr)['phase']=='CONFIRMED_OPPONENT_TURN' and ocr.calls==2)
    for height,width in ((1440,2560),(1264,2780)):
        source=np.full((height,width,3),24,np.uint8)
        ocr=OCR([row()]);value=recognizer()
        observed=value.observe(source,dict(packet,source_height=height,source_width=width),ocr)
        # The full OCR receives the height720 recognition frame. Restore its
        # current measured text box to the source frame without making a target.
        rw=round(width*720/height);sx,sy=width/rw,height/720
        expected=np.asarray(row()['box'])*[sx,sy]
        check('source_coordinates_restored_'+str(width),observed['phase']=='WAITING_OPPONENT_MULLIGAN'
              and np.allclose(observed['wait_label']['box'],np.rint(expected),atol=1)
              and observed['source_shape']==[height,width,3] and observed['target_bounds'] is None and ocr.calls==1)
    ocr=OCR([row()]);observed=recognizer().observe(frame,dict(packet,source_width=1279),ocr)
    check('wrong_source_geometry_rejected_before_ocr',observed['phase']=='UNKNOWN' and ocr.calls==0)
    check('no_ocr_cannot_invent_waiting',recognizer().observe(frame,packet,None)['phase']=='UNKNOWN')
    return dict(passed=True,checks=checks,scope='current_opponent_mulligan_wait_only',device_inputs=0,captures=0)


if __name__=='__main__':
    from pathlib import Path
    print(json.dumps(run(Path(__file__).resolve().parents[2]/'assets/mulligan-one-shot'),ensure_ascii=False))
