"""Source-pixel recognition. Input dispatch stays outside this observation API."""
import json,time
from pathlib import Path
import cv2,numpy as np
from .frame_features import FrameFeatures
from .native_objects import Objects
from .native_board import board
from .native_hand import inspect,blind_point
from .native_hq import inspect as inspect_hq
from .native_guard import Guards
from .fast_page import FastPage
from .combat import observe as combat
from .action_chain import select

def read(path):
    frame=cv2.imdecode(np.frombuffer(Path(path).read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    if frame is None:raise ValueError('native_template_decode_failed')
    return frame

def load_banks(core,menu,opening):
    core,menu,opening=map(Path,(core,menu,opening))
    config=json.loads((core/'config/templates.android.combat.json').read_text(encoding='utf8'))
    combat_bank={name.removeprefix('combat_'):(cv2.imdecode(np.frombuffer((core/meta['path']).read_bytes(),np.uint8),0)
        if name.removeprefix('combat_') in ('infantry','tank','artillery','fighter','bomber') else read(core/meta['path']))
        for name,meta in config['templates'].items()}
    meta=json.loads((menu/'manifest.json').read_text(encoding='utf8'))
    names=('home_play','home_tasks','home_play_selected','battle_selected','training_unselected','detail_start','queue_cancel','defeat_banner')
    bank={name:read(menu/meta['templates'][name]['file']) for name in names}
    for state,names in [('ingame',('end_turn_btn','end_turn_btn_white')),('mulligan',('mulligan_ok_btn',)),
                        ('victory',('victory_btn',)),('defeat',('defeat_btn',))]:
        config=json.loads((core/f'config/templates.android.{state}.json').read_text(encoding='utf8'))
        for name in names:
            if name in config['templates']:bank[name]=read(core/config['templates'][name]['path'])
    for name in ('mulligan_title','mulligan_title_compact','mulligan_ok_btn_compact'):
        bank[name]=read(opening/(name+'.png'))
    from apk_enemy_turn import _template
    for layout in ('compact','standard'):bank['opponent_'+layout]=cv2.cvtColor(_template(layout),cv2.COLOR_GRAY2BGR)
    if (menu/'result_continue_label.png').is_file():
        bank['result_continue_label']=read(menu/'result_continue_label.png')
    return bank,combat_bank

def _support_edges(frame,scene,features,hq_candidates=None):
    candidates=([c for c in inspect_hq(frame,features) if c['structural_candidate']]
                if hq_candidates is None else hq_candidates)
    hq=candidates[0]['card_box'] if len(candidates)==1 else None
    units=[c for c in scene['cards'] if c['row']=='our_support' and c['card_edges_verified']]
    unknown=[r for r in scene['support_rectangles'] if not (hq and abs(r[0]-hq[0])<20 and abs(r[1]-hq[1])<20)
             and not any(abs(r[0]-c['card_box_estimate'][0])<20 and abs(r[1]-c['card_box_estimate'][1])<20 for c in units)]
    h,w=frame.shape[:2];ox,oy=round(w*.27),round(h*.59)
    row=features.get('edges')[oy:round(h*.83),ox:round(w*.73)].copy()
    for x,y,cw,ch in [c['card_box_estimate'] for c in units]+([hq] if hq else []):
        a,b=max(0,x-ox-12),max(0,y-oy-12);c,d=min(row.shape[1],x+cw-ox+12),min(row.shape[0],y+ch-oy+12)
        if a<c and b<d:row[b:d,a:c]=0
    residual=float((row>0).mean())
    return {'hq_box':hq,'hq_basis':'shield_and_card_edges' if hq else None,'unknown_rectangles':unknown,
            'structural_candidates':candidates,'unaccounted_edge_fraction':residual,
            'vacancy_candidate':hq is not None and not unknown and residual<.035 and len(units)<4,
            'coverage_candidate':hq is not None and not unknown and residual<.035,
            'production_authority':False}

def support(frame,scene,features):
    raw=_support_edges(frame,scene,features)
    raw['coverage_basis']='original_card_edges'
    if raw['coverage_candidate']:return raw
    class StructureFeatures:
        def get(self,name):
            return features.get('structure_edges' if name=='edges' else name)
    structure=StructureFeatures()
    # Re-run card-sized contour inventory and edge checks. Every original
    # observed support unit must survive; unclassified card frames veto vacancy.
    structural_scene=board(frame,scene['cards'],structure,frontline_result=scene['frontline'])
    result=_support_edges(frame,structural_scene,structure)
    original=[c for c in scene['cards'] if c['row']=='our_support' and c['card_edges_verified']]
    recalled=[c for c in structural_scene['cards'] if c['row']=='our_support' and c['card_edges_verified']]
    matched=all(any(c['box']==other['box'] for other in recalled) for c in original)
    # A sharp card contour is still an unresolved occupant even if smoothing
    # makes it disappear. Never turn a partial/unknown card into background.
    hq=result.get('hq_box')
    sharp_unknown=[r for r in scene['support_rectangles']
        if not (hq and abs(r[0]-hq[0])<20 and abs(r[1]-hq[1])<20)
        and not any(abs(r[0]-c['card_box_estimate'][0])<20 and abs(r[1]-c['card_box_estimate'][1])<20 for c in recalled)]
    if not matched or sharp_unknown:
        result['vacancy_candidate']=False;result['coverage_candidate']=False
    elif not result['coverage_candidate']:
        class CardinalFeatures:
            def get(self,name):
                return features.get('cardinal_structure_edges' if name=='edges' else name)
        cardinal=_support_edges(frame,structural_scene,CardinalFeatures(),result['structural_candidates'])
        # This is a residual texture filter, not permission to discard a card.
        # Keep both original/full-blur inventories and the independent HQ proof.
        prior=result.get('hq_box');current=cardinal.get('hq_box')
        consistent=prior and current and all(abs(a-b)<20 for a,b in zip(prior,current))
        if consistent and cardinal['coverage_candidate']:
            cardinal['full_structure_unaccounted_edge_fraction']=result['unaccounted_edge_fraction']
            result=cardinal
    result.update(coverage_basis='texture_filtered_axis_aligned_card_structure' if
                  'full_structure_unaccounted_edge_fraction' in result else 'texture_filtered_card_structure',
                  raw_unaccounted_edge_fraction=raw['unaccounted_edge_fraction'],
                  original_units_preserved=matched,sharp_unknown_rectangles=sharp_unknown)
    return result

def deployment(frame,page,scene,hand,probe):
    if page=='opponent_turn':return {'action':'wait','reason':'explicit_opponent_turn'}
    if scene['support_full_confirmed']:return {'action':'skip_deploy','reason':'four_support_units_observed'}
    if not probe['vacancy_candidate']:
        return {'action':'wait','reason':'support_vacancy_or_frontline_unconfirmed'}
    if hand and not any(b['orange'] for b in hand):return {'action':'skip_deploy','reason':'all_observed_fee_numerals_unavailable'}
    playable=[b for b in hand if b['kind']=='unit' and b['orange'] and b['grab_source']]
    fallback=blind_point(frame,hand);point=playable[0]['grab_source'] if playable else fallback['point']
    return {'action':'deploy' if playable else ('blind_middle' if point else 'skip_deploy'),
            'reason':'all_blind_candidates_overlap_suspected_orders' if not playable and point is None else '',
            'grab_source':point,'drop_source':[frame.shape[1]*.35,frame.shape[0]*.69],
            'blind_selection':fallback,'dispatch':'offline_only','executable':False,
            'requires':['fresh_own_turn','same_turn_retry_budget','production_vacancy_validation']}

class Pipeline:
    def __init__(self,page_bank,combat_bank,ocr):
        self.page=FastPage(ocr,page_bank);self.objects=Objects(combat_bank);self.guards=Guards(combat_bank)

    def observe(self,frame):
        from .recognition_scale import shrink,restore
        scaled,factors=shrink(frame)
        if factors==(1.,1.):return self.observe_pixels(frame)
        return restore(self.observe_pixels(scaled),frame,scaled,factors)

    def observe_turn_ui(self,frame):
        """Pending end taps need fresh turn proof before expensive board scans.

        An own-turn frame still takes the complete planning path. This API
        never creates an executable action from an abbreviated observation.
        """
        from .recognition_scale import shrink,restore
        scaled,factors=shrink(frame)
        result=self.observe_pixels(scaled,turn_ui_only=True)
        return result if factors==(1.,1.) else restore(result,frame,scaled,factors)

    def observe_pixels(self,frame,*,turn_ui_only=False):
        if not isinstance(frame,np.ndarray) or frame.dtype!=np.uint8 or frame.ndim!=3 or frame.shape[2]!=3:
            raise ValueError('invalid_native_capture')
        h,w=frame.shape[:2]
        if not 1.70<=w/h<=2.30:raise ValueError('unsupported_native_capture_aspect')
        start=time.perf_counter();features=FrameFeatures(frame);page=self.page.observe(frame,features);paged=time.perf_counter()
        active=page['state'] in ('battle','opponent_turn')
        from .choice import inspect as inspect_choice
        choice_evidence=inspect_choice(frame,features) if active else {'ready':False}
        from .turn_preparation import card_display
        display=card_display(frame,features) if active and not choice_evidence['ready'] else {'ready':False}
        if turn_ui_only and page['state']=='opponent_turn':
            return dict(state=page['state'],page=page,scene={},hand=[],hand_scanned=False,
                support_probe={},combat={},choice_modal=bool(choice_evidence['ready']),
                choice_evidence=choice_evidence,card_display=display,current_state_key=None,
                plan={'action':'wait','reason':'explicit_opponent_turn'},
                selected_action={'action':'wait','reason':'explicit_opponent_turn'},
                source_shape=list(frame.shape),coordinate_space='source_pixels',executable=False,
                observation_scope='current_turn_ui',timings_ms={'page':(paged-start)*1000,
                    'total':(time.perf_counter()-start)*1000})
        icons=self.objects.inspect(frame,features) if active else [];scene=board(frame,icons,features) if active else None
        boarded=time.perf_counter();hand=inspect(frame,features) if active else [];handed=time.perf_counter()
        probe=support(frame,scene,features) if active else None;probed=time.perf_counter()
        plan=deployment(frame,page['state'],scene,hand,probe) if active else page.get('plan',{})
        fight=combat(frame,{'dataset':'native','file':'current','state':page['state'],'scene':scene},features,self.guards) if active else None
        fought=time.perf_counter();selected=select({'state':page['state'],'scene':scene,'plan':plan,'combat':fight});done=time.perf_counter()
        # Bright battlefield skins are not choice evidence. Only the three
        # aligned card frames can interrupt normal battlefield actions.
        choice=choice_evidence['ready']
        from .current_state import identity
        state_key=identity(frame,hand) if active else None
        return {'state':page['state'],'page':page,'scene':scene,'hand':hand,'support_probe':probe,'combat':fight,
                'choice_modal':bool(choice),'choice_evidence':choice_evidence,
                'card_display':display,
                'current_state_key':state_key,
                'plan':plan,'selected_action':selected,'source_shape':list(frame.shape),
                'coordinate_space':'source_pixels','executable':False,
                'timings_ms':{name:(b-a)*1000 for name,a,b in [('page',start,paged),('board',paged,boarded),
                    ('hand',boarded,handed),('support',handed,probed),('combat',probed,fought),
                    ('selection',fought,done),('total',start,done)]}}
