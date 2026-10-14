"""Narrow post-result diamond claim waits; no capture or input authority."""
import cv2
import numpy as np
import hashlib
import json
from pathlib import Path

PHASE_TIMEOUT_SECONDS=8.0
REWARD_NAMES=('diamond_label','tap_claim')
TASK_SUBTITLES=('task_subtitle','task_subtitle_pass_backdrop','task_subtitle_cards_backdrop')

def match(frame,template,bounds):
    x,y,w,h=bounds;left,top=max(0,x-3),max(0,y-3)
    roi=frame[top:min(720,y+h+3),left:min(1280,x+w+3)]
    scores=cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED)
    _,score,_,point=cv2.minMaxLoc(scores);bx,by=left+point[0],top+point[1]
    crop=frame[by:by+h,bx:bx+w]
    return {'score':float(score),'mad':float(cv2.absdiff(crop,template).mean()),
        'brightness':float(crop.mean())/max(1.,float(template.mean())),'bounds':[bx,by,w,h]}

def strong(row, *, release_only=False):
    # The release-only pair removes an already-established wait; it cannot
    # name a menu, mark return success, or authorize a named-control tap.
    return row['score']>=.98 and row['mad']<=13 and (.80 if release_only else .90)<=row['brightness']<=1.10

class RewardWaitGate:
    def __init__(self,templates,specs,*,session_epoch,result_verified,deadline):
        self.templates=templates
        self.specs=specs
        self.session_epoch=session_epoch
        self.result_verified=result_verified is True
        self.deadline=deadline
        self.phase=None
        self.phase_started=None
        self.last=None
        self.events=[]

    def clear(self):
        self.phase=self.phase_started=self.last=None

    def decide(self,frame,observation,now,*,session_epoch=None):
        state=observation.get('state','')
        if session_epoch is not None and session_epoch!=self.session_epoch:
            self.clear();self.result_verified=False
        row={'wait':False,'stop':False,'reason':'ordinary_original_observation','phase':self.phase}
        if not self.result_verified:
            row['reason']='no_verified_result_admission';self.last=row;return row
        if now>=self.deadline:
            row.update(stop=True,reason='settle_deadline');self.last=row;return row
        if state in ('home','mode_menu','deck_list','deck_ready','queueing','mulligan_ready',
                     'login_reward','card_collection','disconnected','menu_transition'):
            self.clear();row['reason']='original_known_state_priority';self.last=row;return row
        if not isinstance(frame,np.ndarray) or frame.shape!=(720,1280,3) or frame.dtype!=np.uint8:
            self.clear();row['reason']='invalid_frame_original_path';self.last=row;return row
        markers={name:match(frame,template,self.specs[name]['bounds']) for name,template in self.templates.items()}
        row['markers']=markers
        diamond=strong(markers['diamond_label'])
        claim=strong(markers['tap_claim'])
        task_pair=strong(markers['task_title'],release_only=True) and any(
            strong(markers[name],release_only=True) for name in TASK_SUBTITLES)
        black=int(frame.max())<8 and observation.get('reason')=='black_transition'
        # Two independent text anchors prove the previously seen reward phase
        # has ended. Raw state remains unknown; the original blind point window
        # still owns its admission/budget and never calls this a menu success.
        if self.phase is not None and task_pair:
            self.clear();row['reason']='new_task_text_pair_releases_wait';self.last=row;return row
        if self.phase is not None and now-self.phase_started>=PHASE_TIMEOUT_SECONDS:
            row.update(stop=True,reason='settle_reward_phase_timeout',phase=self.phase)
            self.last=row;return row
        if self.phase=='after_claim':
            row.update(wait=True,reason='claimed_diamond_exit_wait',phase=self.phase)
        elif diamond:
            if self.phase is None or self.phase=='black':
                self.phase='before_claim';self.phase_started=now
            if claim:
                row.update(reason='diamond_and_claim_text_ready',phase=self.phase,claim_ready=True)
            else:
                row.update(wait=True,reason='diamond_label_without_claim_wait',phase=self.phase)
        elif self.phase=='before_claim':
            row.update(wait=True,reason='diamond_marker_temporarily_missing_wait',phase=self.phase)
        elif black:
            if self.phase is None:self.phase='black';self.phase_started=now
            row.update(wait=True,reason='black_transition_readonly_wait',phase=self.phase)
        elif self.phase=='black':
            # An unarmed black transition ending on an ordinary unknown does
            # not manufacture a reward phase or reinterpret that page.
            self.clear();row['reason']='black_ended_original_path'
        self.events.append({'now':now,**row})
        self.last=row
        return row

    def note_dispatch(self,accepted,completed,now):
        if not accepted or not completed:
            self.clear();return
        if self.last and self.last.get('claim_ready'):
            self.phase='after_claim';self.phase_started=now
            self.events.append({'now':now,'event':'claim_dispatch_completed_arms_exit_wait'})


def load_gate(assets, *, session_epoch, result_verified, deadline):
    """Load optional word crops; missing/corrupt assets preserve the old loop."""
    if result_verified is not True:
        return None, 'not_admitted'
    if assets is None:
        return None, 'assets_absent'
    try:
        directory = Path(assets)
        manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        optional = manifest['reward_wait']
        if optional['schema'] != 1:
            raise ValueError('reward_schema')
        specs = dict(optional['markers'])
        if set(specs) != set(REWARD_NAMES):
            raise ValueError('reward_marker_names')
        specs.update({name:manifest['templates'][name] for name in ('task_title',*TASK_SUBTITLES)})
        templates = {}
        for name, spec in specs.items():
            filename = spec['file']
            if not isinstance(filename,str) or Path(filename).name != filename or '/' in filename or '\\' in filename:
                raise ValueError('reward_asset_path')
            raw = (directory/filename).read_bytes()
            if hashlib.sha256(raw).hexdigest() != spec['sha256']:
                raise ValueError('reward_asset_hash')
            template = cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
            x,y,w,h = spec['bounds']
            if (any(type(v) is not int for v in (x,y,w,h)) or min(x,y)<0 or min(w,h)<=0
                    or x+w>1280 or y+h>720 or template is None or template.shape!=(h,w,3)):
                raise ValueError('reward_asset_shape')
            templates[name]=template
        return RewardWaitGate(templates,specs,session_epoch=session_epoch,
                              result_verified=True,deadline=deadline), 'optional_text_assets_verified'
    except (OSError,ValueError,TypeError,KeyError,cv2.error) as error:
        return None, 'unavailable:'+type(error).__name__
