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
        result=[]
        # A one-pixel dark-component boundary change moved a real infantry
        # glyph from .8994 to .971 in code173. Re-propose geometry, not scores.
        for threshold in (65,75,85,55):
            _,_,stats,_=cv2.connectedComponentsWithStats((hsv[:,:,2]<threshold).astype(np.uint8),8)
            for x,y,bw,bh,area in stats[1:]:
                if not (18*scale<=bw<=42*scale and 18*scale<=bh<=44*scale and area>=.55*bw*bh):continue
                glyph=normalized(frame[y:y+bh,x:x+bw])
                scores={name:float(cv2.matchTemplate(glyph,needle,cv2.TM_CCOEFF_NORMED)[0,0]) for name,needle in self.bank.items()}
                names=sorted(scores,key=scores.get,reverse=True)
                if scores[names[0]]<.90 or scores[names[0]]-scores[names[1]]<.12:continue
                prior=next((r for r in result if abs(x-r['box'][0])<8*scale and abs(y-r['box'][1])<8*scale),None)
                if prior is not None:
                    if prior['type']!=names[0]:prior['conflicting_type']=True
                    continue
                result.append({'box':[int(x),int(y),int(bw),int(bh)],'type':names[0],
                    'score':scores[names[0]],'margin':scores[names[0]]-scores[names[1]],
                    'plate_threshold':threshold,'side':'unknown','input_authorized':False})
        return [r for r in result if not r.get('conflicting_type')]
