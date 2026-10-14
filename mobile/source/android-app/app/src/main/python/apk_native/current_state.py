"""Current-state identity for local retry limits, never turn-success proof."""
import hashlib,json
import cv2
import numpy as np

def identity(frame,hand):
    h,w=frame.shape[:2];scale=h/720
    # Current resource plate and current hand, excluding timer/chat animation.
    roi=frame[round(h*.69):round(h*.83),round(w*.015):round(w*.08)]
    gray=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
    hud=(cv2.resize(gray,(32,40),interpolation=cv2.INTER_AREA)//32).astype(np.uint8)
    badges=[(round(b['box'][0]/scale/4),round(b['box'][1]/scale/4),b.get('orange'),b.get('kind')) for b in hand]
    return hashlib.sha256(hud.tobytes()+json.dumps(badges,separators=(',',':')).encode()).hexdigest()
