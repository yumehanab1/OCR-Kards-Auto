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
        needles=np.stack([normalized(bank[name]).astype(np.float32).ravel() for name in TYPES])
        self.centered=needles-needles.mean(axis=1,keepdims=True)
        self.norms=np.sqrt(np.einsum('ij,ij->i',self.centered,self.centered))
        self.norms[self.norms<=0]=1.

    def inspect(self,frame,features=None):
        h,w=frame.shape[:2];scale=h/720
        hsv=features.get('hsv') if features is not None else cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        mask=(hsv[:,:,2]<65).astype(np.uint8)
        _,_,stats,_=cv2.connectedComponentsWithStats(mask,8)
        result=[]
        for x,y,bw,bh,area in stats[1:]:
            if not (18*scale<=bw<=42*scale and 18*scale<=bh<=44*scale and area>=.55*bw*bh):continue
            glyph=normalized(frame[y:y+bh,x:x+bw]).astype(np.float32).ravel()
            centered=glyph-glyph.mean()
            norm=float(np.sqrt(centered@centered))
            if norm<=0:continue
            scores=(self.centered@centered)/(self.norms*norm)
            names=sorted(range(len(TYPES)),key=lambda i:-scores[i])
            first,second=names[0],names[1]
            if scores[first]>=.90 and scores[first]-scores[second]>=.12:
                result.append({'box':[int(x),int(y),int(bw),int(bh)],'type':TYPES[first],
                    'score':float(scores[first]),'margin':float(scores[first]-scores[second]),
                    'side':'unknown','input_authorized':False})
        return result
