"""Paired receipt + unique artwork + stable row relocation evidence."""
import cv2
import numpy as np
import hashlib
from pathlib import Path
from collections import OrderedDict

_SOURCE_SHAPES=OrderedDict()
_MAX_SOURCE_SHAPES=64
_MAX_READER_BYTES=64*1024*1024


class _SourceFailure(Exception):
    pass


def _decode(raw):
    return cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)


def _remember_shape(digest,shape):
    _SOURCE_SHAPES[digest]=tuple(shape)
    _SOURCE_SHAPES.move_to_end(digest)
    while len(_SOURCE_SHAPES)>_MAX_SOURCE_SHAPES:_SOURCE_SHAPES.popitem(last=False)


class _SourceReader:
    """One proof call's verified byte snapshots, with a bounded decoded cache.

    Cross-call reuse stores only actual dimensions of successfully decoded SHA
    content. Every call still reads and hashes every original source identity.
    """
    def __init__(self):
        self.raw=OrderedDict();self.frames=OrderedDict();self.raw_bytes=0;self.frame_bytes=0

    def trim(self):
        while self.raw_bytes+self.frame_bytes>_MAX_READER_BYTES:
            if self.frames:
                _,frame=self.frames.popitem(last=False);self.frame_bytes-=frame.nbytes
            elif self.raw:
                _,(_,raw)=self.raw.popitem(last=False);self.raw_bytes-=len(raw)
            else:break

    def original(self,source):
        path=Path(source['path'])
        # Aliases and changed metadata each receive their own hash check. Only
        # detector reuse of this same source identity shares its byte snapshot.
        key=(str(path),source.get('sha256'),tuple(source.get('shape') or ()),
             source.get('frame_id'),source.get('elapsed_ms'))
        if key in self.raw:
            value=self.raw[key];self.raw.move_to_end(key);return value
        try:
            if not path.is_file():raise _SourceFailure('source_hash_mismatch')
            raw=path.read_bytes()
        except OSError:raise _SourceFailure('source_hash_mismatch')
        digest=hashlib.sha256(raw).hexdigest()
        if digest!=source.get('sha256'):raise _SourceFailure('source_hash_mismatch')
        self.raw[key]=(digest,raw);self.raw_bytes+=len(raw);self.trim()
        return digest,raw

    def remember_frame(self,digest,frame):
        if digest in self.frames:self.frame_bytes-=self.frames.pop(digest).nbytes
        self.frames[digest]=frame;self.frame_bytes+=frame.nbytes;self.trim()

    def shape(self,source):
        digest,raw=self.original(source)
        if digest in _SOURCE_SHAPES:
            _SOURCE_SHAPES.move_to_end(digest)
            return list(_SOURCE_SHAPES[digest])
        frame=_decode(raw)
        if frame is None:raise _SourceFailure('source_geometry_mismatch')
        shape=list(frame.shape);_remember_shape(digest,shape);self.remember_frame(digest,frame)
        return shape

    def frame(self,source):
        digest,raw=self.original(source)
        if digest in self.frames:
            frame=self.frames[digest];self.frames.move_to_end(digest)
        else:
            frame=_decode(raw)
            if frame is None:raise _SourceFailure('source_geometry_mismatch')
            _remember_shape(digest,frame.shape);self.remember_frame(digest,frame)
        if list(frame.shape)!=source.get('shape'):raise _SourceFailure('source_geometry_mismatch')
        return frame
def read(path):
    return _decode(Path(path).read_bytes())


def validate_sources(pair,reader=None):
    """Verify original bytes, geometry and chronology before consuming observations."""
    observations=pair.get('observations',[])
    if len(observations)<2:return 'insufficient_paired_sources'
    reader=reader or _SourceReader()
    previous=None;shape=observations[0]['source'].get('shape')
    for index,obs in enumerate(observations):
        source=obs['source']
        try:actual_shape=reader.shape(source)
        except _SourceFailure as error:return str(error)
        if actual_shape!=source.get('shape') or source.get('shape')!=shape:
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


def movement(pair,reader=None):
    result={'confirmed':False,'reason':'actor_or_row_unconfirmed','samples':[]}
    if pair['context']!='move_front' or not pair['reply'].get('completed') or not pair['reply'].get('accepted'):
        return dict(result,reason='no_completed_move_receipt')
    reader=reader or _SourceReader();error=validate_sources(pair,reader)
    if error:return dict(result,reason=error)
    before=pair['observations'][0];px,py=pair['request']['from']
    actors=[c for c in (before.get('scene') or {}).get('cards',[]) if c['card_edges_verified'] and c['row']=='our_support'
            and c['card_box_estimate'][0]<=px<=c['card_box_estimate'][0]+c['card_box_estimate'][2]
            and c['card_box_estimate'][1]<=py<=c['card_box_estimate'][1]+c['card_box_estimate'][3]]
    if len(actors)!=1:return dict(result,status='uncovered',reason='before_move_actor_not_unique')
    actor=actors[0];image=reader.frame(before['source']);needle=artwork(image,actor)
    verified=[]
    for obs in pair['observations'][1:]:
        frame=reader.frame(obs['source']);matches=[]
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


def attack_effect(pair,reader=None):
    result={'confirmed':False,'reason':'target_or_stable_change_unconfirmed','samples':[]}
    if pair['context']!='attack_unit' or not all(pair['reply'].get(k) for k in ('accepted','completed')):return result
    reader=reader or _SourceReader();error=validate_sources(pair,reader)
    if error:return dict(result,reason=error)
    before=pair['observations'][0];px,py=pair['request']['to']
    targets=[c for c in (before.get('scene') or {}).get('cards',[]) if c['card_edges_verified'] and c['side']=='enemy'
        and c['card_box_estimate'][0]<=px<=c['card_box_estimate'][0]+c['card_box_estimate'][2]
        and c['card_box_estimate'][1]<=py<=c['card_box_estimate'][1]+c['card_box_estimate'][3]]
    if len(targets)!=1:return dict(result,status='uncovered',reason='before_attack_target_not_unique')
    target=targets[0];source=reader.frame(before['source']);needle=artwork(source,target)
    def defense(image,card):
        x,y,w,h=card['card_box_estimate']
        crop=image[y+round(.78*h):y+round(.98*h),x+round(.70*w):x+round(.98*w)]
        return cv2.resize(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),(28,28))
    old=defense(source,target);stable=[];last=None
    for obs in pair['observations'][1:]:
        image=reader.frame(obs['source']);matches=[]
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


def deployment(pair,reader=None):
    result={'confirmed':False,'reason':'complete_support_increment_unconfirmed','samples':[]}
    if pair['context']!='deploy' or not all(pair['reply'].get(k) is True for k in ('accepted','completed')):
        return dict(result,reason='no_completed_deploy_receipt')
    reader=reader or _SourceReader();error=validate_sources(pair,reader)
    if error:return dict(result,reason=error)
    def complete(obs):
        probe=obs.get('support_probe') or {}
        return bool(probe.get('coverage_candidate') is not False and probe.get('hq_box')
                    and not probe.get('unknown_rectangles')
                    and probe.get('unaccounted_edge_fraction',1)<.035)
    before=pair['observations'][0]
    if not complete(before):return dict(result,status='uncovered',reason='before_support_coverage_unconfirmed')
    count=(before.get('scene') or {}).get('support_observed');stable=[]
    if not isinstance(count,int) or count<0:return dict(result,status='uncovered',reason='before_support_count_unconfirmed')
    if count>=4:return dict(result,status='uncovered',reason='before_support_row_already_full')
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


def end_turn(pair,reader=None):
    result={'confirmed':False,'reason':'explicit_opponent_sequence_unconfirmed','samples':[]}
    if pair['context']!='end_turn' or not all(pair['reply'].get(k) is True for k in ('accepted','completed')):
        return dict(result,reason='no_completed_end_turn_receipt')
    reader=reader or _SourceReader();error=validate_sources(pair,reader)
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
    reader=_SourceReader()
    detectors={'move_front':movement,'attack_unit':attack_effect,'deploy':deployment,'end_turn':end_turn}
    if kind in detectors:
        try:effect=detectors[kind](pair,reader)
        except _SourceFailure as error:effect=dict(confirmed=False,reason=str(error),samples=[])
        return dict(effect,status='confirmed' if effect['confirmed'] else effect.get('status','unconfirmed'),scope='source_paired_sequence')
    error=validate_sources(pair,reader)
    return {'confirmed':False,'status':'uncovered','reason':error or 'effect_detector_not_covered','scope':'source_paired_sequence'}
