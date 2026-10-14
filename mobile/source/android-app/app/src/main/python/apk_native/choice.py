"""Three aligned large card frames; choose the middle card without name OCR."""
import itertools
import cv2
import numpy as np

def inspect(frame,features):
    h,w=frame.shape[:2];scale=h/720
    hsv=features.get('hsv');mask=np.uint8((hsv[:,:,2]>=110)&(hsv[:,:,1]<=110))*255
    horizontal=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((1,max(30,round(70*scale))),np.uint8))
    _,_,stats,_=cv2.connectedComponentsWithStats(horizontal,8)
    edges=features.get('edges');candidates=[]
    for x,y,cw,_,_ in stats[1:]:
        if not (.35*h<cw<.48*h and .12*h<y<.30*h):continue
        ch=round(cw*1.42)
        if y+ch>.86*h:continue
        band=max(2,round(8*scale));scores=[]
        for xx in (x,x+cw):
            roi=edges[y:y+ch,max(0,xx-band):min(w,xx+band+1)]
            scores.append(float((roi.max(axis=1)>0).mean()))
        for yy in (y,y+ch):
            roi=edges[max(0,yy-band):min(h,yy+band+1),x:x+cw]
            scores.append(float((roi.max(axis=0)>0).mean()))
        if min(scores)<.90:continue
        box=[int(x),int(y),int(cw),int(ch)]
        if any(abs(x-b[0])<12*scale and abs(y-b[1])<12*scale for b in candidates):continue
        candidates.append(box)
    groups=[]
    for group in itertools.combinations(sorted(candidates),3):
        if (max(b[1] for b in group)-min(b[1] for b in group)<.025*h
                and max(b[2] for b in group)/min(b[2] for b in group)<1.10
                and all(.015*w<b[0]-a[0]-a[2]<.08*w for a,b in zip(group,group[1:]))
                and abs(group[1][0]+group[1][2]/2-w/2)<.08*w):groups.append(group)
    if len(groups)!=1:return {'ready':False,'reason':'three_aligned_card_frames_unconfirmed'}
    return {'ready':True,'boxes':list(groups[0]),'selected_index':1,
            'basis':'three_large_card_frames_four_edges','coordinate_space':'source_pixels'}
