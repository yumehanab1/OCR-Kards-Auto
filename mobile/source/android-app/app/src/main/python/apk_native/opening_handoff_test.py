"""Current turn-text handoff independent of old templates, resources and HQs."""
import copy,json
import numpy as np
from .opening import OpeningRecognizer


def run(assets):
    checks=[]
    def check(name,valid):
        if not valid:raise AssertionError(name)
        checks.append(name)
    def row(text,x,y,w=110,h=30,score=.94):
        return dict(text=text,score=score,box=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]])
    frame=np.full((720,1280,3),24,np.uint8)
    packet=dict(coordinate_space='source_pixels',source_width=1280,source_height=720)
    class OCR:
        def __init__(self,items):self.items=items;self.calls=0
        def __call__(self,frame):
            self.calls+=1
            return [(r['box'],r['text'],r['score']) for r in self.items],0
    def observe(items,opening_score=.20):
        recognizer=OpeningRecognizer(assets)
        recognizer.source_turn=None;recognizer.source_opening=None
        recognizer.detector.match=lambda gray,name:dict(score=opening_score if name.startswith('mulligan_') else .20,
            ok=False,bounds=[500,50,80,30],factor=1.)
        ocr=OCR(items)
        return recognizer.observe(frame,packet,ocr),ocr.calls
    end=row('结束回合',1060,435,145,32)
    own,calls=observe([end])
    check('current_end_text_handoffs_without_any_template_match',own['phase']=='CONFIRMED_MY_TURN' and calls==1)
    check('resources_are_diagnostic_only',not own['resources'] and not own['resource_anchors']['ok'])
    check('target_comes_from_current_text',own['target_bounds']==[1060.,435.,145.,32.])
    opponent=row('敌方',1100,435,70,32)
    enemy,calls=observe([opponent])
    check('current_enemy_text_handoffs_without_hq_template',enemy['phase']=='CONFIRMED_OPPONENT_TURN' and calls==1)
    check('opponent_target_is_current_text_box',enemy['target_bounds']==[1100.,435.,70.,32.])
    check('conflicting_end_enemy_does_not_handoff',observe([end,opponent])[0]['phase']=='UNKNOWN')
    check('weak_end_text_does_not_handoff',observe([dict(end,score=.92)])[0]['phase']=='UNKNOWN')
    check('weak_enemy_text_does_not_handoff',observe([dict(opponent,score=.92)])[0]['phase']=='UNKNOWN')
    check('left_end_caption_not_turn_control',observe([row('结束回合',60,435,145,32)])[0]['phase']=='UNKNOWN')
    check('left_enemy_caption_not_turn_control',observe([row('敌方',60,435,70,32)])[0]['phase']=='UNKNOWN')
    check('duplicate_enemy_labels_ambiguous',observe([opponent,copy.deepcopy(opponent)])[0]['phase']=='UNKNOWN')
    opening=[row('选择要替换的卡牌',440,60,400,36,.91),row('确认',590,600,100,36,.91)]
    check('current_opening_controls_precede_turn_handoff',observe(opening+[end])[0]['phase']=='MULLIGAN_CONFIRM')
    misplaced=[dict(opening[0],box=[[20,60],[420,60],[420,96],[20,96]]),opening[1],end]
    check('present_opening_controls_block_handoff_even_if_target_geometry_unresolved',observe(misplaced)[0]['phase']=='UNKNOWN')
    changed,calls=observe([end],opening_score=.80)
    check('old_opening_template_false_positive_cannot_veto_current_end',changed['phase']=='CONFIRMED_MY_TURN')
    check('one_full_ocr_shared_with_earlier_opening_proposal',calls==1)
    return dict(passed=True,checks=checks,scope='generated_current_opening_turn_handoff',device_inputs=0,captures=0)


if __name__=='__main__':
    from pathlib import Path
    print(json.dumps(run(Path(__file__).resolve().parents[2]/'assets/mulligan-one-shot'),ensure_ascii=False))
