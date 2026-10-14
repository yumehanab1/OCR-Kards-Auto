"""Wait once per own turn for draw/hand motion, without delaying every action."""
import cv2
import numpy as np

def card_display(frame,features):
    h,w=frame.shape[:2];scale=h/720;hsv=features.get('hsv')
    pale=np.uint8((hsv[:,:,2]>=110)&(hsv[:,:,1]<=110))*255
    strips=cv2.morphologyEx(cv2.morphologyEx(pale,cv2.MORPH_CLOSE,np.ones((1,5),np.uint8)),
                           cv2.MORPH_OPEN,np.ones((1,max(30,round(60*scale))),np.uint8))
    stats=cv2.connectedComponentsWithStats(strips,8)[2];edges=features.get('edges')
    for x,y,cw,_,_ in stats[1:]:
        if not (.23*h<cw<.35*h and .15*h<y<.40*h and abs(x+cw/2-w/2)<.07*w):continue
        band=max(3,round(7*scale))
        for ratio in (1.34,1.36,1.38,1.40,1.42,1.44):
            ch=round(cw*ratio)
            if y+ch>=.82*h:continue
            coverage=[float((edges[y:y+ch,max(0,xx-band):min(w,xx+band+1)].max(axis=1)>0).mean()) for xx in (x,x+cw)]
            coverage += [float((edges[max(0,yy-band):min(h,yy+band+1),x:x+cw].max(axis=0)>0).mean()) for yy in (y,y+ch)]
            pale_sides=[float((pale[y:y+ch,max(0,xx-band):min(w,xx+band+1)]>0).any(axis=1).mean()) for xx in (x,x+cw)]
            if min(coverage)>=.93 and min(pale_sides)>=.90:
                return dict(ready=True,box=[int(x),int(y),int(cw),int(ch)],basis='central_large_single_card_four_edges')
    return dict(ready=False)

class TurnPreparation:
    def __init__(self):
        self.started=None;self.previous=None;self.opponent_hand=None
        self.ready=False;self.draw_seen=False;self.unknown_since=None

    def after_completed_end(self,observed):
        self.opponent_hand=self.hand(observed);self.started=None;self.previous=None
        self.ready=False;self.draw_seen=False;self.unknown_since=None

    @staticmethod
    def hand(observed):
        return sorted([(b['box'][0]+b['box'][2]/2,b['box'][1]+b['box'][3]/2) for b in observed.get('hand') or []])

    @staticmethod
    def same(a,b,tolerance):
        return a is not None and b is not None and len(a)==len(b) and all(
            max(abs(x-u),abs(y-v))<=tolerance for (x,y),(u,v) in zip(a,b))

    def observe(self,observed,packet):
        state=observed.get('state');hand=self.hand(observed);now=packet['captured_elapsed_ms']
        tolerance=packet['source_height']*4/720
        if state=='opponent_turn':
            if observed.get('hand_scanned',True):self.opponent_hand=hand
            self.started=None;self.previous=None
            self.ready=False;self.draw_seen=False;self.unknown_since=None
            return dict(ready=False,reason='opponent_turn')
        if state!='battle':
            self.previous=None
            return dict(ready=False,reason='not_current_own_turn')
        if self.started is None:self.started=now
        preview=observed.get('card_display',{}).get('ready',False)
        if preview:
            self.draw_seen=True;self.ready=False;self.previous=None
            self.unknown_since=None
            return dict(ready=False,reason='central_card_display',elapsed_ms=now-self.started)
        if observed.get('choice_modal'):
            self.previous=None
            return dict(ready=False,reason='choice_modal')
        if self.opponent_hand is not None and not self.same(hand,self.opponent_hand,tolerance):self.draw_seen=True
        prior=self.previous;self.previous=(hand,dict(packet))
        if not self.ready:
            # Full hand / empty deck may not change its count. A bounded grace
            # remains necessary when the actual draw occurred between captures.
            minimum=2500 if self.draw_seen else 4500
            stable=(prior is not None and self.same(hand,prior[0],tolerance)
                    and packet['frame_id']>prior[1]['frame_id']
                    and all(packet.get(k)==prior[1].get(k) for k in ('foreground_generation','source_width','source_height'))
                    and 500<=now-prior[1]['captured_elapsed_ms']<=5000)
            self.ready=stable and now-self.started>=minimum
        probe=observed.get('support_probe') or {}
        if probe.get('vacancy_candidate') or observed.get('scene',{}).get('support_full_confirmed'):
            self.unknown_since=None
        elif self.unknown_since is None:self.unknown_since=now
        return dict(ready=self.ready,reason='draw_and_hand_settled' if self.ready else 'waiting_for_draw_and_stable_hand',
                    elapsed_ms=now-self.started,draw_observed=self.draw_seen,
                    local_vacancy_skip_ready=self.unknown_since is None or now-self.unknown_since>=1800)
