"""Current menu-control semantics; generated frames never become templates."""
import json
from pathlib import Path
import cv2
import numpy as np
from .menu import NativeMenuRecognizer,menu_from_text


def run(assets):
    checks=[]
    def check(name,valid):
        if not valid:raise AssertionError(name)
        checks.append(name)
    def row(text,x,y,w=50,h=24,score=.91):
        return dict(text=text,score=score,box=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]])
    def frame():return np.full((720,1280,3),24,np.uint8)
    def paint(image,items,orange=()):
        for index,item in enumerate(items):
            x,y=np.asarray(item['box'],dtype=int).min(axis=0)
            cv2.putText(image,str(index+123),(int(x),int(y)+17),cv2.FONT_HERSHEY_SIMPLEX,.55,
                        (0,150,255) if item['text'] in orange else (210,210,210),1,cv2.LINE_AA)
        return image
    home=[row('开始',68,110),row('卡牌',70,180)]
    check('home_requires_only_start_and_same_rail_cards',menu_from_text(frame(),home)['state']=='home')
    check('home_also_accepts_shop',menu_from_text(frame(),[home[0],row('商店',70,250)])['state']=='home')
    shifted=[row('开始',130,85,75,38),row('卡牌',133,195,80,38)]
    check('current_boxes_move_and_resize',menu_from_text(frame(),shifted)['targets']['menu_home_start']==[130,85,75,38])
    check('start_alone_has_no_page_authority',menu_from_text(frame(),home[:1]) is None)
    check('right_start_is_not_home',menu_from_text(frame(),[row('开始',1100,540),home[1]]) is None)
    check('unrelated_cards_not_same_rail',menu_from_text(frame(),[home[0],row('卡牌',700,200)]) is None)
    check('duplicate_left_start_is_ambiguous',menu_from_text(frame(),home+[row('开始',80,150)]) is None)
    check('low_confidence_start_not_dispatched',menu_from_text(frame(),[dict(home[0],score=.70),home[1]]) is None)
    check('outside_source_box_not_dispatched',menu_from_text(frame(),[row('开始',-1,100),home[1]]) is None)
    selector=[row('休闲',1040,430),row('排位',1130,430),row('开始',1085,525,70,24)]
    selected=paint(frame(),selector,('休闲',))
    ready=menu_from_text(selected,selector)
    check('queue_uses_selector_and_current_start_without_mode_titles',ready['state']=='deck_ready' and ready['selected_mode']=='casual')
    check('queue_target_is_actual_ocr_box',ready['targets']['menu_start_queue']==[1085,525,70,24])
    check('missing_start_cannot_queue',menu_from_text(selected,selector[:2]) is None)
    check('left_start_cannot_queue',menu_from_text(selected,selector[:2]+[row('开始',80,525)]) is None)
    both=selector+home
    check('right_queue_has_precedence_over_navigation_rail',menu_from_text(selected,both)['state']=='deck_ready')
    grey=paint(frame(),selector)
    check('selected_mode_is_read_from_current_pixels',menu_from_text(grey,selector) is None)
    ranked=paint(frame(),selector,('排位',))
    check('ranked_current_color_is_independent',menu_from_text(ranked,selector)['selected_mode']=='ranked')
    deck=frame();cv2.rectangle(deck,(360,90),(535,340),(230,230,230),7)
    battle=[row('对战模式',65,175,110,24)]
    listed=menu_from_text(deck,battle)
    check('deck_needs_one_mode_label_and_actual_card',listed['state']=='deck_list' and listed['targets']['menu_select_deck'][0]<400)
    check('no_card_no_deck_target',menu_from_text(frame(),battle) is None)
    check('card_without_mode_is_not_menu',menu_from_text(deck,[]) is None)
    check('mode_page_rail_not_misread_as_home',menu_from_text(frame(),battle+home) is None)

    class Bridge:
        def __init__(self):self.calls=0
        def recognizeNativeText(self,request):
            packet=json.loads(str(request));self.calls+=1
            return json.dumps(dict(packet,ok=True,height=packet['source_height'],width=packet['source_width'],
                                   items=[dict(item,score_available=True) for item in self.items]))
    bridge=Bridge();bridge.items=home
    recognizer=NativeMenuRecognizer(Path(assets),bridge,startup=True)
    source=paint(frame(),home)
    packet=dict(coordinate_space='source_pixels',source_height=720,source_width=1280,
                frame_id=1,captured_elapsed_ms=100,foreground_generation=3,png_path='generated-current.png')
    observed=recognizer.observe(source,packet)
    check('startup_unknown_reaches_current_ocr',bridge.calls==1 and observed['state']=='home')
    check('startup_current_target_uses_ocr_box',observed['targets']['menu_home_start']==[68,110,50,24])
    large=cv2.resize(source,(1920,1080));bridge.items=[]
    for item in home:
        bridge.items.append(dict(item,box=(np.asarray(item['box'])*1.5).tolist()))
    packet=dict(packet,source_width=1920,source_height=1080,frame_id=2,png_path='generated-large.png')
    observed=recognizer.observe(large,packet)
    check('source_coordinate_restoration',observed['targets']['menu_home_start']==[102,165,75,36])
    check('source_profile_and_size_remain_explicit',observed['layout_profile']=='standard_16_9' and observed['source_shape']==[1080,1920,3])
    bridge.items=[]
    packet=dict(packet,source_width=1280,source_height=720,frame_id=3,png_path='generated-empty.png')
    empty=recognizer.observe(frame(),packet)
    check('new_frame_never_reuses_old_semantic_verdict',empty['state']=='unknown' and not empty['targets'])
    from .login_reward_test import run as login_reward_checks
    reward=login_reward_checks(assets)
    check('login_reward_suite_passed',reward['passed'])
    checks.extend('login_reward:'+name for name in reward['checks'])
    return json.dumps(dict(passed=True,checks=checks,scope='generated_current_menu_controls',
                           device_inputs=0,captures=0,ocr_calls=bridge.calls))


if __name__=='__main__':
    print(run(Path(__file__).resolve().parents[2]/'assets/match-entry'))
