"""Scoped semantic rejection and capture-identity checks, without input."""
import copy
import json
import numpy as np
from .opening_dynamic import inspect
from .ocr_bridge import NativeOCR


def run(frame,observed):
    checks=[];items=observed['items']
    def check(name,valid):
        if not valid:raise AssertionError(name)
        checks.append(name)
    class Scoped:
        def __init__(self,rows):self.rows=rows;self.calls=0
        def regions(self,image,regions):
            self.calls+=1
            return [(r['box'],r['text'],r['score']) for r in self.rows],0
    for name,rows in [('low_confidence',copy.deepcopy(items)),('wrong_title',copy.deepcopy(items)),
                      ('duplicate_confirm',copy.deepcopy(items))]:
        if name=='low_confidence':
            for row in rows:row['score']=.89
        elif name=='wrong_title':rows[0]['text']='请选择商品'
        else:rows.append(copy.deepcopy(next(r for r in rows if r['text']=='确认')))
        check(name+'_rejected',not inspect(frame,Scoped(rows),True)['ready'])
    guard=Scoped(items)
    check('resources_do_not_block_visible_controls',inspect(frame,guard,False)['ready'] and guard.calls==1)
    check('button_border_does_not_block_semantic_controls',inspect(np.zeros_like(frame),guard,True)['ready'] and guard.calls==2)

    h,w=frame.shape[:2];source_h,source_w=1264,2780;sx,sy=source_w/w,source_h/h
    packet=dict(frame_id=77,captured_elapsed_ms=999,foreground_generation=4,
                source_width=source_w,source_height=source_h,png_path='/current.png',coordinate_space='source_pixels')
    class Bridge:
        mismatch=False;unavailable=False;request=None
        def recognizeNativeText(self,raw):
            self.request=json.loads(raw)
            result=dict(packet,ok=not self.unavailable,width=source_w,height=source_h,scope='opening_controls',items=[])
            for row in items:
                result['items'].append(dict(row,box=(np.asarray(row['box'])*[sx,sy]).tolist(),score_available=True))
            if self.mismatch:result['frame_id']+=1
            return json.dumps(result)
    bridge=Bridge();ocr=NativeOCR(bridge);ocr.bind(packet)
    rows,_=ocr.regions(frame,observed['regions'])
    check('scoped_current_source_identity',bridge.request['frame_id']==77 and bridge.request['ocr_scope']=='opening_controls')
    check('restored_current_region_boxes',np.allclose(rows[0][0],items[0]['box']))
    bridge.mismatch=True
    try:ocr.regions(frame,observed['regions'])
    except ValueError:check('different_capture_rejected',True)
    else:check('different_capture_rejected',False)
    bridge.mismatch=False;bridge.unavailable=True
    check('unavailable_has_no_cached_evidence',ocr.regions(frame,observed['regions'])[0]==[])
    return dict(passed=True,checks=checks,inputs=0)
