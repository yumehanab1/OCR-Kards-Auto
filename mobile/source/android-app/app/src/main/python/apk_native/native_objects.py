"""Native-resolution dark stat-plate candidates and local type verification.

Objects have no allegiance/card identity. This experiment never authorizes input.
Only candidate crops are resized, following the existing type-glyph comparison.
"""
import json
from pathlib import Path
import cv2,numpy as np
TYPES=('infantry','tank','artillery','fighter','bomber')

def normalized(crop):
    gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY) if crop.ndim==3 else crop
    return cv2.resize(gray[2:-2,2:-2],(32,32),interpolation=cv2.INTER_AREA)

class Objects:
    def __init__(self,bank):
        self.bank={name:normalized(bank[name]) for name in TYPES}

    def inspect(self,frame,features=None):
        h,w=frame.shape[:2];scale=h/720
        # Same dark-component idea as production. Detect complete components
        # on the entire source before evaluating footprint, never crop a plate.
        hsv=features.get('hsv') if features is not None else cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        mask=(hsv[:,:,2]<65).astype(np.uint8)
        _,_,stats,_=cv2.connectedComponentsWithStats(mask,8)
        result=[]
        for x,y,bw,bh,area in stats[1:]:
            if not (18*scale<=bw<=42*scale and 18*scale<=bh<=44*scale and area>=.55*bw*bh):continue
            glyph=normalized(frame[y:y+bh,x:x+bw])
            scores={name:float(cv2.matchTemplate(glyph,needle,cv2.TM_CCOEFF_NORMED)[0,0]) for name,needle in self.bank.items()}
            names=sorted(scores,key=scores.get,reverse=True)
            if scores[names[0]]>=.90 and scores[names[0]]-scores[names[1]]>=.12:
                result.append({'box':[int(x),int(y),int(bw),int(bh)],'type':names[0],
                    'score':scores[names[0]],'margin':scores[names[0]]-scores[names[1]],
                    'side':'unknown','input_authorized':False})
        return result
