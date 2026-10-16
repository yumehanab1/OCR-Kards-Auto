"""Daily-task controls from current OCR boxes, without saved glyph evidence."""
import copy,json
from pathlib import Path
import numpy as np
from .menu import semantic_daily_popup,NativeMenuRecognizer


def run(assets):
    checks=[]
    def check(name,valid):
        if not valid:raise AssertionError(name)
        checks.append(name)
    def row(text,x,y,w,h,score=.94):
        return dict(text=text,score=score,box=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]])
    title=row('每日任务',540,130,200,40,.96)
    buttons=[row('拒绝',330+index*250,485,70,30,.92+index*.01) for index in range(3)]
    frame=np.full((720,1280,3),220,np.uint8)
    for count in (1,2,3):
        observed=semantic_daily_popup(frame,[title]+buttons[:count])
        check('accepts_'+str(count)+'_current_refuse_buttons',observed is not None and len(observed['buttons'])==count)
    proof=semantic_daily_popup(frame,[title]+buttons)
    check('basis_is_current_title_and_buttons',proof['basis']=='current_daily_title_and_buttons')
    check('original_ocr_scores_preserved',proof['title_score']==.96 and proof['buttons'][0]['score']==.92)
    check('no_fabricated_blank_score','blank_score' not in proof)
    check('blank_tap_target_is_below_tasks',proof['target_bounds']==[628.,653.,24,24])
    check('title_without_buttons_not_overlay',semantic_daily_popup(frame,[title]) is None)
    check('buttons_without_title_not_overlay',semantic_daily_popup(frame,buttons) is None)
    check('duplicate_title_ambiguous',semantic_daily_popup(frame,[title,title]+buttons) is None)
    check('weak_title_unavailable',semantic_daily_popup(frame,[dict(title,score=.89)]+buttons) is None)
    check('weak_button_unavailable',semantic_daily_popup(frame,[title,dict(buttons[0],score=.89)]) is None)
    check('more_than_three_controls_ambiguous',semantic_daily_popup(frame,[title]+buttons+[row('拒绝',1100,485,70,30)]) is None)
    check('duplicated_control_not_multiple_task_cards',semantic_daily_popup(frame,[title,buttons[0],copy.deepcopy(buttons[0])]) is None)
    check('unrelated_refuse_on_different_row_rejected',semantic_daily_popup(frame,[title,buttons[0],row('拒绝',830,330,70,30)]) is None)
    check('refuse_above_title_rejected',semantic_daily_popup(frame,[title,row('拒绝',330,70,70,30)]) is None)
    check('text_on_blank_target_rejected',semantic_daily_popup(frame,[title]+buttons+[row('确认',620,650,70,30)]) is None)
    check('dark_blank_pixels_not_a_required_template',semantic_daily_popup(frame,[title]+buttons) is not None)
    check('lower_current_buttons_still_leave_blank_target',
          semantic_daily_popup(frame,[title,row('拒绝',616,585,49,35)]) is not None)
    check('buttons_too_close_to_blank_target_rejected',
          semantic_daily_popup(frame,[title,row('拒绝',616,589,49,43)]) is None)
    class Bridge:
        def __init__(self,items):self.items=items
        def recognizeNativeText(self,encoded):
            packet=json.loads(str(encoded))
            return json.dumps(dict(packet,ok=True,width=packet['source_width'],height=packet['source_height'],
                                   items=[dict(item,score_available=True) for item in self.items]))
    bridge=Bridge([title]+buttons);recognizer=NativeMenuRecognizer(assets,bridge,startup=True)
    packet=dict(coordinate_space='source_pixels',source_width=1280,source_height=720,frame_id=1,
                captured_elapsed_ms=1000,foreground_generation=3,png_path='generated-current-daily.png')
    observed=recognizer.observe(frame,packet)
    check('production_menu_uses_current_daily_evidence',observed['state']=='login_popup_cleanup'
          and observed['login_popup_evidence']['basis']=='current_daily_title_and_buttons')
    check('production_target_avoids_refuse_buttons',observed['targets']['menu_clear_login_popup']==[628.,653.,24,24])
    large=np.full((1080,1920,3),220,np.uint8)
    bridge.items=[dict(r,box=(np.asarray(r['box'])*1.5).tolist()) for r in [title]+buttons]
    observed=recognizer.observe(large,dict(packet,source_width=1920,source_height=1080,frame_id=2))
    check('source_target_restored',observed['targets']['menu_clear_login_popup']==[942.,980.,36,36])
    check('source_evidence_boxes_restored',observed['login_popup_evidence']['buttons'][0]['bounds']==[495,728,105,45])
    return dict(passed=True,checks=checks,scope='generated_current_daily_controls',device_inputs=0,captures=0)


if __name__=='__main__':
    print(json.dumps(run(Path(__file__).resolve().parents[2]/'assets/match-entry'),ensure_ascii=True))
