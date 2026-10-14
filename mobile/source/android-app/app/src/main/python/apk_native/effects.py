"""Paired receipt + unique artwork + stable row relocation evidence."""
import cv2
import numpy as np
import hashlib
from pathlib import Path
def read(path):
    return cv2.imdecode(np.frombuffer(Path(path).read_bytes(),np.uint8),cv2.IMREAD_COLOR)


def validate_sources(pair):
    """Verify original bytes, geometry and chronology before consuming observations."""
    observations=pair.get('observations',[])
    if len(observations)<2:return 'insufficient_paired_sources'
    previous=None;shape=observations[0]['source'].get('shape')
    for index,obs in enumerate(observations):
        source=obs['source'];path=Path(source['path'])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=source.get('sha256'):
            return 'source_hash_mismatch'
        frame=read(path)
        if frame is None or list(frame.shape)!=source.get('shape') or source.get('shape')!=shape:
            return 'source_geometry_mismatch'
        elapsed=source.get('elapsed_ms')
        if not isinstance(elapsed,(int,float)) or (previous is not None and elapsed<=previous):
            return 'source_time_not_increasing'
        if index==0 and (source.get('frame_id')!=pair['request'].get('frame_id') or elapsed>pair['dispatch_elapsed_ms']):
            return 'before_source_not_request_frame'
        if index and elapsed<=pair['dispatch_elapsed_ms']:return 'after_source_precedes_dispatch'
        previous=elapsed
    return None


def artwork(frame,card):
    x,y,w,h=card['card_box_estimate']
    crop=frame[y+round(h*.24):y+round(h*.68),x+round(w*.10):x+round(w*.90)]
    return cv2.resize(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),(64,64))


def movement(pair):
    result={'confirmed':False,'reason':'actor_or_row_unconfirmed','samples':[]}
    if pair['context']!='move_front' or not pair['reply'].get('completed') or not pair['reply'].get('accepted'):
        return dict(result,reason='no_completed_move_receipt')
    error=validate_sources(pair)
    if error:return dict(result,reason=error)
    before=pair['observations'][0];px,py=pair['request']['from']
    actors=[c for c in before['scene']['cards'] if c['card_edges_verified'] and c['row']=='our_support'
            and c['card_box_estimate'][0]<=px<=c['card_box_estimate'][0]+c['card_box_estimate'][2]
            and c['card_box_estimate'][1]<=py<=c['card_box_estimate'][1]+c['card_box_estimate'][3]]
    if len(actors)!=1:return result
    actor=actors[0];image=read(before['source']['path']);needle=artwork(image,actor)
    verified=[]
    for obs in pair['observations'][1:]:
        frame=read(obs['source']['path']);matches=[]
        for c in obs['scene']['cards']:
            if not c['card_edges_verified'] or c['type']!=actor['type']:continue
            score=float(cv2.matchTemplate(artwork(frame,c),needle,cv2.TM_CCOEFF_NORMED)[0,0])
            if score>=.95:matches.append({'card':c,'score':score})
        own=[m for m in matches if m['card']['side']=='our']
        ok=len(own)==1 and own[0]['card']['row']=='front' and obs['scene']['frontline']['owner']=='our'
        # Match uniqueness is restricted to our battlefield; opposing copies
        # cannot be the moved actor, but same-side identical cards veto proof.
        result['samples'].append({'frame_id':obs['source']['frame_id'],'elapsed_ms':obs['source']['elapsed_ms'],
            'unique_own_artwork':len(own)==1,'front_observed':ok,'matches':matches})
        if ok:verified.append(obs['source']['elapsed_ms'])
        else:verified=[]
        if len(verified)>=3 and verified[-1]-verified[-3]>=1000:
            result.update(confirmed=True,reason='completed_move_unique_artwork_support_to_front_three_spaced_samples')
            result['confirmation_window_ms']=verified[-3:]
            return result
    return result


def attack_effect(pair):
    result={'confirmed':False,'reason':'target_or_stable_change_unconfirmed','samples':[]}
    if pair['context']!='attack_unit' or not all(pair['reply'].get(k) for k in ('accepted','completed')):return result
    error=validate_sources(pair)
    if error:return dict(result,reason=error)
    before=pair['observations'][0];px,py=pair['request']['to']
    targets=[c for c in before['scene']['cards'] if c['card_edges_verified'] and c['side']=='enemy'
        and c['card_box_estimate'][0]<=px<=c['card_box_estimate'][0]+c['card_box_estimate'][2]
        and c['card_box_estimate'][1]<=py<=c['card_box_estimate'][1]+c['card_box_estimate'][3]]
    if len(targets)!=1:return result
    target=targets[0];source=read(before['source']['path']);needle=artwork(source,target)
    def defense(image,card):
        x,y,w,h=card['card_box_estimate']
        crop=image[y+round(.78*h):y+round(.98*h),x+round(.70*w):x+round(.98*w)]
        return cv2.resize(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),(28,28))
    old=defense(source,target);stable=[];last=None
    for obs in pair['observations'][1:]:
        image=read(obs['source']['path']);matches=[]
        for c in obs['scene']['cards']:
            if c['side']!='enemy' or not c['card_edges_verified'] or c['type']!=target['type']:continue
            score=float(cv2.matchTemplate(artwork(image,c),needle,cv2.TM_CCOEFF_NORMED)[0,0])
            if score>=.95:matches.append(c)
        changed=False;delta=None
        if len(matches)==1:
            current=defense(image,matches[0]);delta=float(np.mean(np.abs(current.astype(float)-old)))
            changed=bool(delta>=8 and (last is None or np.mean(np.abs(current.astype(float)-last))<3))
            last=current
        else:last=None
        if changed:stable.append(obs['source']['elapsed_ms'])
        else:stable=[]
        result['samples'].append({'frame_id':obs['source']['frame_id'],'unique_target':len(matches)==1,'defense_pixel_delta':delta,'changed':changed})
        if len(stable)>=3 and stable[-1]-stable[-3]>=1000:
            result.update(confirmed=True,reason='completed_attack_unique_target_stable_defense_glyph_change',
                          damage_value_read=False,target_removed=False)
            result['confirmation_window_ms']=stable[-3:]
            return result
    return result


def deployment(pair):
    result={'confirmed':False,'reason':'complete_support_increment_unconfirmed','samples':[]}
    if pair['context']!='deploy' or not all(pair['reply'].get(k) is True for k in ('accepted','completed')):
        return dict(result,reason='no_completed_deploy_receipt')
    error=validate_sources(pair)
    if error:return dict(result,reason=error)
    def complete(obs):
        probe=obs.get('support_probe') or {}
        return bool(probe.get('coverage_candidate') is not False and probe.get('hq_box')
                    and not probe.get('unknown_rectangles')
                    and probe.get('unaccounted_edge_fraction',1)<.035)
    before=pair['observations'][0]
    if not complete(before):return result
    count=before['scene']['support_observed'];stable=[]
    if count>=4:return result
    # Full row coverage is required on both sides; isolated recalled cards
    # or hand disappearance cannot establish deployment.
    for obs in pair['observations'][1:]:
        ok=complete(obs) and obs['scene']['support_observed']==count+1
        result['samples'].append({'frame_id':obs['source']['frame_id'],'complete_row_increment':ok})
        if ok:stable.append(obs['source']['elapsed_ms'])
        else:stable=[]
        if len(stable)>=3 and stable[-1]-stable[-3]>=1000:
            return dict(result,confirmed=True,reason='completed_deploy_complete_support_increment_three_spaced_samples',
                        confirmation_window_ms=stable[-3:])
    return result


def end_turn(pair):
    result={'confirmed':False,'reason':'explicit_opponent_sequence_unconfirmed','samples':[]}
    if pair['context']!='end_turn' or not all(pair['reply'].get(k) is True for k in ('accepted','completed')):
        return dict(result,reason='no_completed_end_turn_receipt')
    error=validate_sources(pair)
    if error:return dict(result,reason=error)
    if pair['observations'][0].get('page',{}).get('state')!='battle':
        return dict(result,reason='before_own_turn_unconfirmed')
    stable=[]
    for obs in pair['observations'][1:]:
        ok=obs.get('page',{}).get('state')=='opponent_turn'
        result['samples'].append({'frame_id':obs['source']['frame_id'],'explicit_opponent':ok})
        if ok:stable.append(obs['source']['elapsed_ms'])
        else:stable=[]
        if len(stable)>=3 and stable[-1]-stable[-3]>=1000:
            return dict(result,confirmed=True,reason='completed_end_turn_explicit_opponent_three_spaced_samples',
                        confirmation_window_ms=stable[-3:])
    return result


def sequence_postcondition(pair):
    """Production receipt/source-pair verification; unsupported effects stay unknown."""
    kind=pair.get('context')
    detectors={'move_front':movement,'attack_unit':attack_effect,'deploy':deployment,'end_turn':end_turn}
    if kind in detectors:
        effect=detectors[kind](pair)
        return dict(effect,status='confirmed' if effect['confirmed'] else 'unconfirmed',scope='source_paired_sequence')
    error=validate_sources(pair)
    return {'confirmed':False,'status':'uncovered','reason':error or 'effect_detector_not_covered','scope':'source_paired_sequence'}
