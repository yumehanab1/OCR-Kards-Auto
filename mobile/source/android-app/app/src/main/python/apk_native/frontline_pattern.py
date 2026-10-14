"""Positive repeated stair marker geometry, independent of tabletop colour/artwork."""
import cv2
import numpy as np


def _template(scale):
    # One period of the marker: two uprights, upper ledges, lower gap and base rail.
    # Channels retain edge direction, so diagonal weave is not interchangeable.
    t=np.zeros((18,29,2),np.float32)
    t[6:13,8:12,0]=1;t[6:13,19:23,0]=1
    t[4:7,:11,1]=1;t[4:7,20:,1]=1;t[11:14,11:20,1]=1;t[15:18,:,1]=1
    return cv2.resize(t,(max(8,round(29*scale)),max(6,round(18*scale))),interpolation=cv2.INTER_NEAREST)


def inspect(frame,verified_card_boxes=(),*,triangular=False,_gradients=None):
    h,w=frame.shape[:2];scale=h/720;left,right=round(w*.25),round(w*.75)
    top,bottom=round(h*.27),round(h*.64);t=_template(scale)
    if triangular:
        t=np.zeros((14,29,2),np.float32)
        for y in range(9):
            t[y,max(0,14-y-1):14-y+2,0]=1
            t[y,14+y-1:14+y+2,0]=1
        t[9:12,:,1]=1
        t=cv2.resize(t,(round(29*scale),round(14*scale)),interpolation=cv2.INTER_NEAREST)
    if _gradients is None:
        dx=np.abs(cv2.Sobel(frame,cv2.CV_32F,1,0));dy=np.abs(cv2.Sobel(frame,cv2.CV_32F,0,1))
    else:dx,dy=_gradients
    groups=[]
    for threshold in (80,40,20):
        vertical=(((dx>threshold)&(dy>threshold)&(dx>.35*dy)&(dy>.35*dx))
                  if triangular else ((dx>threshold)&(dx>2*dy))).any(axis=2).astype(np.uint8)
        horizontal=((dy>threshold)&(dy>2*dx)).any(axis=2).astype(np.uint8)
        kernel=np.ones((max(2,round(2*scale)),max(2,round(2*scale))),np.uint8)
        q=np.stack([cv2.dilate(vertical,kernel),cv2.dilate(horizontal,kernel)],axis=2).astype(np.float32)
        # Card edges/artwork cannot contribute as marker evidence.
        for x,y,cw,ch in verified_card_boxes:
            q[max(0,y):min(h,y+ch+(0 if triangular else round(4*scale))),max(0,x):min(w,x+cw)]=0
        area=q[top:bottom,left:right]
        if area.shape[0]<t.shape[0] or area.shape[1]<t.shape[1]:continue
        response=cv2.matchTemplate(area,t,cv2.TM_CCORR)/float(t.sum())
        tolerant=cv2.dilate(response,np.ones((max(3,round(7*scale)),1),np.uint8))
        hist=(tolerant>=.82).sum(axis=1)
        candidates=[];blocked=np.zeros(len(hist),bool)
        for y in np.argsort(hist)[::-1]:
            if hist[y]<16:break
            if blocked[y]:continue
            blocked[max(0,y-round(9*scale)):y+round(9*scale)+1]=True;candidates.append(int(y))
        for y in candidates:
            r=tolerant[y].copy();points=[]
            for _ in range(40):
                x=int(np.argmax(r));score=float(r[x])
                if score<.82:break
                local=response[max(0,y-round(3*scale)):y+round(3*scale)+1,x]
                actual_y=max(0,y-round(3*scale))+int(np.argmax(local))
                points.append((x,score,actual_y));radius=round(22*scale)
                r[max(0,x-radius):x+radius+1]=0
            points.sort()
            if len(points)<8:continue
            xs=np.array([p[0] for p in points]);gaps=np.diff(xs);period=29*scale
            fit=float(np.mean(np.abs(gaps/period-np.round(gaps/period))<.20))
            span=float((xs[-1]-xs[0])/w)
            bins=[sum(a<=x<b for x in xs) for a,b in zip(np.linspace(0,right-left,4)[:-1],np.linspace(0,right-left,4)[1:])]
            if span<.30 or not 22*scale<float(np.median(gaps))<37*scale or fit<.85 or min(bins)<2:continue
            line=int(round(np.median([p[2] for p in points])+top+(10 if triangular else 16)*scale))
            evidence=dict(line_y=line,steps=len(points),period_fit=fit,span=span,
                          direction_coverage=float(np.mean([p[1] for p in points])),gradient_threshold=threshold,
                          basis='distributed_diagonal_triangle_marker' if triangular else 'distributed_two_direction_stair_marker')
            prior=next((g for g in groups if abs(g['line_y']-line)<round(h*.035)),None)
            if prior is None:groups.append(evidence)
            elif evidence['steps']>prior['steps']:groups[groups.index(prior)]=evidence
    if not triangular:
        for candidate in inspect(frame,verified_card_boxes,triangular=True,_gradients=(dx,dy)):
            prior=next((g for g in groups if abs(g['line_y']-candidate['line_y'])<round(h*.035)),None)
            if prior is None:groups.append(candidate)
    return groups
