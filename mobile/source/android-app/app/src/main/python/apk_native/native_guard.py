"""Local Guard/Protected template verification on source card geometry."""
import json
import cv2
import numpy as np


class Guards:
    def __init__(self,bank):
        self.bank={name:cv2.cvtColor(bank[name],cv2.COLOR_BGR2GRAY)
                   for name in ('guard_unit','guard_hq')}

    def inspect(self,frame,box,features,geometry_verified=False):
        x,y,w,h=box;scale=frame.shape[0]/720
        x0,x1=max(0,round(x+w-5*scale)),min(frame.shape[1],round(x+w+32*scale))
        y0,y1=max(0,y),min(frame.shape[0],round(y+48*scale))
        win=features.get('gray')[y0:y1,x0:x1]
        if win.size==0 or float(win.std())<5:return {'state':'unknown','scores':{}}
        scores={};locations={}
        for name,template in self.bank.items():
            best=(-1.,None)
            for factor in (.9,1.,1.1):
                needle=cv2.resize(template,(round(template.shape[1]*scale*factor),round(template.shape[0]*scale*factor)))
                for variant in (needle,cv2.flip(needle,1)) if name=='guard_hq' else (needle,):
                    if variant.shape[0]>win.shape[0] or variant.shape[1]>win.shape[1]:continue
                    _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(win,variant,cv2.TM_CCOEFF_NORMED))
                    if score>best[0]:best=(float(score),[x0+point[0],y0+point[1]])
            scores[name]=best[0];locations[name]=best[1]
        names=sorted(scores,key=scores.get,reverse=True)
        state='unknown'
        if scores[names[0]]>=.90 and scores[names[0]]-scores[names[1]]>=.065:
            state='guard' if names[0]=='guard_unit' else 'protected'
        empty_evidence=None
        if state=='unknown' and geometry_verified:
            # A clear result requires the interior of the expected tab to
            # contain no enclosed bright glyph and to match its continuation
            # below the first marker. Unfamiliar plus/gear/shield variants stay
            # unknown, including numerals inside protected shields.
            left,right=round(x+w+5*scale),round(x+w+24*scale)
            top,bottom=round(y+8*scale),round(y+30*scale)
            if 0<=left<right<frame.shape[1] and 0<=top<bottom+round(24*scale)<frame.shape[0]:
                gray=features.get('gray');inside=gray[top:bottom,left:right]
                below=gray[bottom:bottom+round(22*scale),left:right]
                bright=inside>float(np.percentile(inside,30))+18
                delta=abs(float(np.median(inside))-float(np.median(below)))
                empty_evidence={'bright_fraction':float(bright.mean()),'background_delta':delta}
                if bright.mean()<.015 and delta<15 and scores[names[0]]<.75:
                    state='clear'
        return {'state':state,'scores':scores,'at':locations[names[0]],
                'empty_tab_evidence':empty_evidence,
                'geometry_verified':geometry_verified,'input_authorized':False}
