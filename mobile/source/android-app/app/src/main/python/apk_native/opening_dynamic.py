"""Current pale button geometry plus scoped semantic OCR; no glyph templates."""
import time
import cv2
import numpy as np


def buttons(frame):
    h,w=frame.shape[:2];hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    pale=np.uint8((hsv[:,:,2]>=145)&(hsv[:,:,1]<=105))
    contours,_=cv2.findContours(pale*255,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    found=[];pad=max(2,round(h*3/720))
    for contour in contours:
        x,y,bw,bh=cv2.boundingRect(contour)
        if not (.25*h<bw<.6*h and .055*h<bh<.15*h and y>h*.72
                and abs(x+bw/2-w/2)<w*.12):continue
        strips=(pale[y:y+pad,x:x+bw],pale[y+bh-pad:y+bh,x:x+bw],
                pale[y:y+bh,x:x+pad],pale[y:y+bh,x+bw-pad:x+bw])
        coverage=[float(s.any(axis=0 if i<2 else 1).mean()) for i,s in enumerate(strips)]
        if min(coverage)>=.94:found.append(dict(bounds=[x,y,bw,bh],edge_coverage=coverage))
    return found


def inspect(frame,ocr,resources=False):
    candidates=buttons(frame)
    evidence=dict(ready=False,button_candidates=candidates,ocr_used=False)
    if ocr is None or not hasattr(ocr,'regions'):return evidence
    h,w=frame.shape[:2];pad=max(4,round(h*8/720))
    if len(candidates)==1:
        x,y,bw,bh=candidates[0]['bounds'];left,top=max(0,x-pad),max(0,y-pad)
        bottom=[left,top,min(w,x+bw+pad)-left,min(h,y+bh+pad)-top]
    else:
        bottom=[round(w*.20),round(h*.70),round(w*.60),h-round(h*.70)]
    regions=[[round(w*.30),0,round(w*.40),round(h*.22)],
             bottom]
    started=time.perf_counter();found,_=ocr.regions(frame,regions)
    evidence.update(ocr_used=True,ocr_ms=(time.perf_counter()-started)*1000,regions=regions)
    items=[dict(box=np.asarray(box).tolist(),text=text,score=float(score)) for box,text,score in found or []]
    from .opening import text_button
    structural=text_button(frame,items,resources,label_threshold=.90)
    evidence.update(items=items,ready=structural is not None,structure=structural)
    return evidence
