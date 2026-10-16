"""Daily login semantics and same-frame source coordinates; no device input."""
import copy,json
from unittest import mock
import cv2,numpy as np
from .menu import NativeMenuRecognizer,semantic_login_reward,login_reward_regions
from apk_match_entry import MenuFlow


def run(assets):
    checks=[]
    def check(name,value):
        if not value:raise AssertionError(name)
        checks.append(name)
    # Two successful OCR observations from the original code138 archive.
    # These are text/geometry fixtures, not source image or OCR accuracy tests.
    title=dict(text='每日登录奖励',score=.9886714617411295,
               box=[[1288,226],[1632,226],[1632,290],[1288,290]])
    prompt=dict(text='轻触任意位置进入主屏幕。',score=.9955114622910818,
                box=[[1281,988],[1623,994],[1623,1034],[1281,1031]])
    frame=np.zeros((1264,2780,3),np.uint8)
    rows=[title,prompt]
    proof=semantic_login_reward(frame,rows)
    check('original_frame5_text_uses_actual_prompt_bounds',proof['target_bounds']==[1281,988,342,46])
    second=[dict(title,score=.9882027904192606),dict(prompt,score=.993177130818367,
            box=[[1281,987],[1623,992],[1623,1036],[1281,1032]])]
    check('original_frame14_text_is_recognized',semantic_login_reward(frame,second)['target_bounds']==[1281,987,342,49])
    for name,change in (
            ('title_only',lambda value:value.pop()),('prompt_only',lambda value:value.pop(0)),
            ('wrong_title',lambda value:value[0].update(text='每日任务')),
            ('claim_is_not_continue',lambda value:value[1].update(text='点击领取奖励')),
            ('purchase_suffix_is_not_continue',lambda value:value[1].update(text='轻触任意位置进入主屏幕，立即购买')),
            ('weak_title',lambda value:value[0].update(score=.89)),
            ('weak_prompt',lambda value:value[1].update(score=.89)),
            ('duplicate_title',lambda value:value.append(copy.deepcopy(value[0]))),
            ('duplicate_prompt',lambda value:value.append(copy.deepcopy(value[1]))),
            ('invalid_box',lambda value:value[1].update(box=[[1,2],[3,4],[5,6]])),
            ('nonfinite_box',lambda value:value[1].update(box=[[float('nan'),2]]*4)),
            ('outside_source',lambda value:value[1].update(box=[[-1,988],[1623,994],[1623,1034],[-1,1031]])),
            ('prompt_above_title',lambda value:value[1].update(box=[[1281,10],[1623,10],[1623,50],[1281,50]]))):
        bad=copy.deepcopy(rows);change(bad)
        check('rejects_'+name,semantic_login_reward(frame,bad) is None)
    check('blank_frame_does_not_trigger_scoped_ocr_proposal',login_reward_regions(np.zeros((720,1280,3),np.uint8)) is None)
    proposal_frame=np.zeros((720,1280,3),np.uint8)
    for bounds in ((490,65,130,24),(600,135,190,30),(600,565,190,22)):
        x,y,bw,bh=bounds;cv2.rectangle(proposal_frame,(x,y),(x+bw,y+bh),(230,230,230),-1)
    proposed=login_reward_regions(proposal_frame)
    x,y,bw,bh=proposed[0]
    check('upper_distractor_does_not_crop_out_lower_title',x<=600 and y<=135 and x+bw>=790 and y+bh>=165)

    class Bridge:
        def __init__(self,items,early=None):self.items=items;self.early=items if early is None else early;self.calls=[];self.wrong_id=False
        def recognizeNativeText(self,request):
            packet=json.loads(request);self.calls.append(packet)
            items=self.early if packet.get('ocr_scope') else self.items
            if packet.get('ocr_scope'):
                def inside(item):
                    points=np.asarray(item['box']);a,b=points.min(axis=0);c,d=points.max(axis=0)
                    return any(x<=a and y<=b and c<=x+bw and d<=y+bh for x,y,bw,bh in packet['ocr_regions'])
                items=[item for item in items if inside(item)]
            answer=dict(packet,ok=True,scope=packet.get('ocr_scope'),width=packet['source_width'],
                height=packet['source_height'],items=[dict(item,score_available=True) for item in items])
            if self.wrong_id:answer['frame_id']+=1
            return json.dumps(answer)
    def scaled_rows(width,height):
        return [dict(item,box=(np.asarray(item['box'])*[width/2780,height/1264]).tolist()) for item in rows]
    def make(width,height,early=None):
        items=scaled_rows(width,height);bridge=Bridge(items,early)
        recognizer=NativeMenuRecognizer(assets,bridge,startup=True)
        image=np.zeros((height,width,3),np.uint8)
        packet=dict(coordinate_space='source_pixels',source_height=height,source_width=width,
            frame_id=7,captured_elapsed_ms=100,foreground_generation=3,png_path='synthetic-current.png')
        names=[]
        def unmatched(gray,name):
            names.append(name);return dict(score=0.,bounds=[0,0,8,8],ok=False)
        recognizer.detector.match=unmatched
        return recognizer,bridge,image,packet,names
    # Proposal masks only choose work. Force broad valid current ROIs here to
    # isolate source restoration and ordering from a synthetic glyph renderer.
    def regions(image):
        h,w=image.shape[:2]
        return [[round(.25*w),round(.08*h),round(.50*w),round(.30*h)],
                [round(.25*w),round(.65*h),round(.50*w),round(.28*h)]]
    for width,height in ((1280,720),(1920,1080),(2780,1264),(2400,1080)):
        recognizer,bridge,image,packet,names=make(width,height)
        with mock.patch('apk_native.menu.login_reward_regions',side_effect=regions):seen=recognizer.observe(image,packet)
        target=seen['targets']['menu_dismiss_reward'];wanted=np.asarray(scaled_rows(width,height)[1]['box'])
        a,b=wanted.min(axis=0);c,d=wanted.max(axis=0)
        check('source_target_is_current_prompt_'+str(width),max(abs(x-y) for x,y in zip(target,[a,b,c-a,d-b]))<=3)
        check('early_ocr_precedes_long_selector_scan_'+str(width),names==['home_play'] and len(bridge.calls)==1)
        call=bridge.calls[0]
        check('two_source_regions_and_identity_preserved_'+str(width),call['ocr_scope']=='menu_controls'
              and len(call['ocr_regions'])==2 and all(call[key]==packet[key] for key in
              ('frame_id','captured_elapsed_ms','foreground_generation','source_height','source_width','png_path')))
        check('evidence_is_restored_to_source_'+str(width),seen['login_reward_evidence']['target_bounds']==target
              and seen['login_reward_evidence']['prompt']['bounds']==target)
        check('early_cost_is_in_total_'+str(width),seen['timings_ms']['total']>=seen['timings_ms']['login_reward_probe']>=0)
    flow=MenuFlow('casual',100);flow.direct_controls=True
    decision=flow.observe(seen,7,200)
    check('existing_menu_flow_uses_existing_reward_action',decision==dict(action='menu_dismiss_reward',bounds=target))

    recognizer,bridge,image,packet,_=make(1280,720)
    bridge.early=scaled_rows(1280,720)[:1]
    with mock.patch('apk_native.menu.login_reward_regions',side_effect=regions):seen=recognizer.observe(image,packet)
    check('full_ocr_can_complete_a_partial_roi_miss',seen['state']=='login_reward' and len(bridge.calls)==2
          and bridge.calls[0].get('ocr_scope')=='menu_controls' and not bridge.calls[1].get('ocr_scope'))
    check('failed_early_probe_timing_remains_visible',seen['login_reward_probe_metrics']['scope']=='menu_controls'
          and seen['timings_ms']['total']>=seen['timings_ms']['login_reward_probe'])
    recognizer,bridge,image,packet,_=make(1280,720)
    def excludes_title(image):
        h,w=image.shape[:2]
        return [[0,0,round(.1*w),round(.1*h)],regions(image)[1]]
    with mock.patch('apk_native.menu.login_reward_regions',side_effect=excludes_title):seen=recognizer.observe(image,packet)
    check('region_bridge_cannot_leak_full_frame_title_into_early_path',seen['state']=='login_reward'
          and len(bridge.calls)==2 and not bridge.calls[1].get('ocr_scope'))
    recognizer,bridge,image,packet,_=make(1280,720)
    with mock.patch('apk_native.menu.login_reward_regions',return_value=None):seen=recognizer.observe(image,packet)
    check('full_ocr_semantics_also_work_without_visual_proposal',seen['state']=='login_reward' and len(bridge.calls)==1)
    recognizer,bridge,image,packet,_=make(1280,720);bridge.items=bridge.early=bridge.items[:1]
    with mock.patch('apk_native.menu.login_reward_regions',side_effect=regions):seen=recognizer.observe(image,packet)
    check('title_alone_never_authorizes_from_either_path',seen['state']=='unknown' and not seen['targets'])
    recognizer,bridge,image,packet,_=make(1280,720);bridge.wrong_id=True
    with mock.patch('apk_native.menu.login_reward_regions',side_effect=regions):
        try:recognizer.observe(image,packet)
        except ValueError as error:check('roi_keeps_real_capture_binding',str(error)=='native_ocr_capture_mismatch')
        else:raise AssertionError('Mismatched source accepted')
    return dict(passed=True,checks=checks,check_count=len(checks),device_inputs=0,captures=0,
        scope='historical_ocr_text_and_synthetic_coordinate_contracts_not_live_ocr_accuracy')
