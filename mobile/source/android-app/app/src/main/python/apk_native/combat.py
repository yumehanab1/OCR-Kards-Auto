import time
import cv2,numpy as np
import unit_state
import apk_simple_combat as policy
from .native_hq import inspect as hq_inspect
from .native_guard import Guards
from .frame_features import FrameFeatures

def markers(frame,scene,features):
    hsv=features.get('hsv');h,w=frame.shape[:2];scale=h/720
    _,_,stats,_=cv2.connectedComponentsWithStats((hsv[:,:,2]<95).astype(np.uint8),8)
    found=[]
    for x,y,bw,bh,area in stats[1:]:
        if not (19*scale<=bw<=38*scale and 19*scale<=bh<=38*scale and
                .75<bw/bh<1.3 and .40<area/(bw*bh)<.95):continue
        # Detect complete plates globally, then associate with verified cards.
        cards=[c for c in scene['cards'] if c['card_edges_verified'] and c['side']=='our'
               and abs(x-c['card_box_estimate'][0])<12*scale
               and abs(y-c['card_box_estimate'][1])<12*scale]
        if len(cards)!=1:continue
        crop=cv2.resize(frame[y:y+bh,x:x+bw],(28,28),interpolation=cv2.INTER_AREA)
        local=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
        state=unit_state.analyze_digit(local[:,:,2],local[:,:,1],limits=unit_state.DIGIT_LIMITS_MOBILE)
        card=cards[0];rx,ry,rw,rh=card['card_box_estimate']
        found.append({'badge_box':[int(x),int(y),int(bw),int(bh)],'state':state['state'] if state else 'unknown',
            'type':card['type'],'row':'support' if card['row']=='our_support' else 'front',
            'card':{'cx':rx+rw/2,'cy':ry+rh/2},'input_authorized':False})
    return found


def observe(frame,entry,features=None,guards=None):
    features=features or FrameFeatures(frame)
    if guards is None:raise ValueError("native_guard_bank_required")
    t=time.perf_counter()
    actors=markers(frame,entry['scene'],features)
    hqs=[c for c in hq_inspect(frame,features,row='enemy_support') if c['structural_candidate']]
    hq=None
    if len(hqs)==1:
        x,y,w,h=hqs[0]['card_box'];hq={'cx':x+w/2,'cy':y+h/2,'geometry_verified':True,'hp':None}
    enemy_cards=[]
    for c in entry['scene']['cards']:
        if not c['card_edges_verified'] or c['side']!='enemy':continue
        x,y,w,h=c['card_box_estimate']
        glyph=guards.inspect(frame,c['card_box_estimate'],features,geometry_verified=True)
        enemy_cards.append({'cx':x+w/2,'cy':y+h/2,'guard_state':glyph['state'],
            'protected':glyph['state']=='protected','guard_evidence':glyph,
            'type':c['type'],'row':'enemy_front' if c['row']=='front' else 'enemy_support'})
    enemy_front=[c for c in enemy_cards if c['row']=='enemy_front']
    hq_glyph=guards.inspect(frame,hqs[0]['card_box'],features,geometry_verified=True) if hq else {'state':'unknown'}
    hq_guard='guarded' if hq_glyph['state']=='protected' else ('clear' if hq_glyph['state']=='clear' else 'unknown')
    guard_info={'status':hq_guard,'hq_guards':[c for c in enemy_cards if c['row']=='enemy_support' and c['guard_state']=='guard']}
    obs={'owner':entry['scene']['frontline']['owner'],'hq':hq,'enemy_front':enemy_front,
         'enemy_support':[c for c in enemy_cards if c['row']=='enemy_support'],
         'guard':guard_info}
    options=[]
    for actor in actors:
        if entry['state']=='opponent_turn' or actor['state']!='orange':continue
        # PC-style fail-soft targeting: unknown remains observation evidence,
        # but does not discard every attack. The executor quarantines a missed
        # actor for this turn after its completed gesture.
        option=policy.actor_options(obs,actor,allow_unknown_guard=True) if obs['owner']!='unknown' else {'kind':'pending','reason':'frontline_unknown'}
        option['guard_policy']='attempt_unknown_once'
        option.update(dispatch='offline_only',executable=False,
                      requires=['fresh_own_turn','same_turn_retry_budget','touch_receipt','action_postcondition'])
        options.append(option)
    result={'dataset':entry['dataset'],'file':entry['file'],'turn_state':entry['state'],
            'actors':actors,'enemy_hq_candidates':hqs,'options':options,
            'enemy_cards':enemy_cards,'hq_guard_evidence':hq_glyph,'guard_info':guard_info,
            'ms':(time.perf_counter()-t)*1000,'guard_detection_implemented':True}
    return result

