"""Offer semantics from current labels; generated text is never a template."""
import copy,json
from pathlib import Path
import numpy as np
from .menu import semantic_offer_target,NativeMenuRecognizer


def run(assets):
    checks=[]
    def check(name,valid):
        if not valid:raise AssertionError(name)
        checks.append(name)
    def row(text,x,y,w,h,score=.95):
        return dict(text=text,score=score,box=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]])
    items=[row('10月战场通票',320,211,260,43),row('现已上架商店！',321,263,139,27),
           row('XXX 11.99',330,468,114,29),row('任务',549,563,101,58)]
    frame=np.full((720,1280,3),24,np.uint8)
    check('current_title_subtitle_price_authorizes_neutral_target',semantic_offer_target(frame,items)==[628.,653.,24,24])
    for label,word in (('title','10月战场通票'),('subtitle','现已上架商店！'),('price','XXX 11.99')):
        missing=[r for r in items if r['text']!=word]
        check('missing_'+label+'_rejected',semantic_offer_target(frame,missing) is None)
        weak=[dict(r,score=.89) if r['text']==word else r for r in items]
        check('weak_'+label+'_rejected',semantic_offer_target(frame,weak) is None)
        duplicate=items+[copy.deepcopy(next(r for r in items if r['text']==word))]
        check('duplicate_'+label+'_rejected',semantic_offer_target(frame,duplicate) is None)
    check('home_carousel_without_price_not_popup',semantic_offer_target(frame,items[:2]) is None)
    check('title_price_without_subtitle_not_popup',semantic_offer_target(frame,[items[0],items[2]]) is None)
    check('navigation_task_is_not_purchase_requirement',semantic_offer_target(frame,items[:3]) is not None)
    bad=copy.deepcopy(items);bad[2]['box']=[[330,100],[444,100],[444,129],[330,129]]
    check('price_above_title_not_offer',semantic_offer_target(frame,bad) is None)
    bad=copy.deepcopy(items);bad[1]['box']=[[800,263],[939,263],[939,290],[800,290]]
    check('unrelated_subtitle_not_offer',semantic_offer_target(frame,bad) is None)
    check('text_over_neutral_target_refuses_tap',semantic_offer_target(frame,items+[row('领取',620,650,60,30)]) is None)
    bad=copy.deepcopy(items);bad[2]['box']=[[330,625],[444,625],[444,654],[330,654]]
    check('offer_reaches_neutral_target_refuses_tap',semantic_offer_target(frame,bad) is None)
    moved=[]
    for r in items:
        moved.append(dict(r,box=(np.asarray(r['box'])+[40,15]).tolist()))
    check('moved_current_offer_does_not_need_fixed_positions',semantic_offer_target(frame,moved) is not None)
    class Bridge:
        def __init__(self,items):self.items=items
        def recognizeNativeText(self,encoded):
            packet=json.loads(str(encoded))
            return json.dumps(dict(packet,ok=True,height=packet['source_height'],width=packet['source_width'],
                items=[dict(r,score_available=True) for r in self.items]))
    bridge=Bridge(items);recognizer=NativeMenuRecognizer(assets,bridge,startup=True)
    packet=dict(coordinate_space='source_pixels',source_width=1280,source_height=720,frame_id=1,
                captured_elapsed_ms=1000,foreground_generation=3,png_path='current-offer.png')
    observed=recognizer.observe(frame,packet)
    check('production_menu_uses_current_offer_basis',observed['state']=='pass_popup'
          and observed['popup_basis']=='current_offer_title_subtitle_price')
    check('production_tap_is_blank_not_price',observed['targets']['menu_dismiss_pass']==[628.,653.,24,24])
    large=np.full((1080,1920,3),24,np.uint8)
    bridge.items=[dict(r,box=(np.asarray(r['box'])*1.5).tolist()) for r in items]
    observed=recognizer.observe(large,dict(packet,source_width=1920,source_height=1080,frame_id=2))
    check('current_offer_source_coordinates_restore',observed['targets']['menu_dismiss_pass']==[942.,980.,36,36])
    return dict(passed=True,checks=checks,scope='generated_current_offer_title_subtitle_price',device_inputs=0,captures=0)


if __name__=='__main__':
    print(json.dumps(run(Path(__file__).resolve().parents[2]/'assets/match-entry'),ensure_ascii=False))
