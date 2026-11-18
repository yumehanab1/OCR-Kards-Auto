"""Current-frame task ROI proof, full fallback, blank and capture identity."""
import json
from unittest import mock
import numpy as np
from .menu import NativeMenuRecognizer


def run(assets):
    checks=[]
    title=dict(text='入伍任务',score=.99,box=[[500,140],[720,140],[720,170],[500,170]])
    footer=dict(text='完成所有入伍任务获取奖励',score=.99,box=[[420,570],[860,570],[860,600],[420,600]])
    class Bridge:
        def __init__(self):self.calls=[];self.rows=[title,footer];self.wrong=False
        def recognizeNativeText(self,request):
            p=json.loads(request);self.calls.append(p)
            r=dict(p,ok=True,scope=p.get('ocr_scope'),width=p['source_width'],height=p['source_height'],
                items=[dict(v,score_available=True) for v in self.rows])
            if self.wrong:r['frame_id']+=1
            return json.dumps(r)
    packet=dict(coordinate_space='source_pixels',source_width=1280,source_height=720,
        frame_id=1,captured_elapsed_ms=100,foreground_generation=1,png_path='current.png')
    regions=[[380,100,520,110],[360,540,560,90]]
    def make():
        b=Bridge();m=NativeMenuRecognizer(assets,b,startup=True)
        m.detector.match=lambda gray,name:dict(score=0.,bounds=[0,0,8,8],ok=False)
        return b,m
    image=np.zeros((720,1280,3),np.uint8)
    with mock.patch('apk_native.menu.login_reward_regions',return_value=regions):
        b,m=make();r=m.observe(image,packet)
        assert r['state']=='blocking_popup' and len(b.calls)==1 and b.calls[0]['ocr_scope']=='menu_controls'
        checks.append('task_two_current_regions_skip_whole_ocr')
        b,m=make();b.rows=[title];r=m.observe(image,packet)
        assert not r['targets'] and len(b.calls)==2 and 'ocr_scope' not in b.calls[-1]
        checks.append('missing_subtitle_retains_full_fallback_no_authority')
        b,m=make();b.wrong=True
        try:m.observe(image,packet)
        except ValueError as e:assert str(e)=='native_ocr_capture_mismatch'
        else:raise AssertionError('wrong capture accepted')
        checks.append('scoped_task_identity_binding_unchanged')
        b,m=make();changed=image.copy();changed[650:680,620:660]=255;r=m.observe(changed,packet)
        assert len(b.calls)==2
        checks.append('nonblank_dismissal_rejects_early_path')
    b=Bridge();b.rows=[];m=NativeMenuRecognizer(assets,b,settlement=True)
    r=m.observe(image,packet);q=b.calls[-1]
    assert q['ocr_scope']=='menu_controls' and len(q['ocr_regions'])==2 and not r['targets']
    assert sum(w*h for x,y,w,h in q['ocr_regions'])<1280*720*.45
    checks.append('settlement_bounded_navigation_regions_unknown_stays_unknown')
    return dict(passed=True,checks=checks,device_inputs=0)
