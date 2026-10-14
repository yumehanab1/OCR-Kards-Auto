"""Current-frame rectangular promotion panel and visible close-X evidence."""
import cv2
import numpy as np
import hashlib


def inspect(frame, close_templates):
    h,w=frame.shape[:2];gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(gray,40,100)
    joined=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_=cv2.findContours(joined,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    # Decorative art can join the border to background edges. Long straight
    # top/bottom segments still propose a rectangle, verified on all four sides.
    horizontal=cv2.morphologyEx(edges,cv2.MORPH_OPEN,np.ones((1,max(20,round(w*.25))),np.uint8))
    lines,_=cv2.findContours(horizontal,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    line_boxes=[cv2.boundingRect(c) for c in lines]
    proposals=[cv2.boundingRect(c) for c in contours]
    for x,y,cw,_ in line_boxes:
        # A complete horizontal side can propose its opposite height even if
        # that side was split by decoration; four-side coverage decides.
        if .30*w<cw<.70*w:
            for opposite in range(max(0,round(y-h*.75)),max(0,round(y-h*.25)),max(1,round(h/720))):
                proposals.append((x,opposite,cw,y-opposite+1))
        for bx,by,bw,_ in line_boxes:
            if by<=y or abs(bx-x)>8 or abs(bw-cw)>16:continue
            proposals.append((min(x,bx),y,max(x+cw,bx+bw)-min(x,bx),by-y+1))
    # Artwork can hide the start of a horizontal border (the starter offer
    # loses its leftmost 12 pixels at height 720). Extend proposals only; the
    # original four-side coverage and close-X tests still decide authority.
    proposals += [(x-round(extra*h/720),y,cw+round(extra*h/720),ch)
                  for x,y,cw,ch in list(proposals) for extra in (4,8,12,16)
                  if .30*w<cw<.70*w and .25*h<ch<.75*h]
    panels=[];pad=max(3,round(h*7/720))
    for x,y,cw,ch in proposals:
        if not (.30*w<cw<.70*w and .25*h<ch<.75*h and .12*w<x<.45*w and .08*h<y<.45*h):continue
        if abs(x+cw/2-w/2)>.08*w:continue
        strips=(edges[max(0,y-pad):y+pad+1,x:x+cw],edges[y+ch-pad:y+ch+pad+1,x:x+cw],
                edges[y:y+ch,max(0,x-pad):x+pad+1],edges[y:y+ch,x+cw-pad:x+cw+pad+1])
        coverage=[float((strip>0).any(axis=0 if i<2 else 1).mean()) for i,strip in enumerate(strips)]
        if min(coverage)<.93:continue
        if any(max(abs(x-a),abs(y-b),abs(cw-c),abs(ch-d))<=pad*2+8 for a,b,c,d,_ in panels):continue
        panels.append((x,y,cw,ch,coverage))
    confirmed=[]
    for x,y,cw,ch,coverage in panels:
        left,top=round(x+cw*.88),y
        roi=gray[top:round(y+ch*.18),left:x+cw]
        best=None
        for name,template in close_templates.items():
            for factor in np.arange(.8,1.401,.02):
                scale=h/720*factor;th,tw=template.shape[:2]
                needle=cv2.cvtColor(cv2.resize(template,(max(8,round(tw*scale)),max(8,round(th*scale)))),cv2.COLOR_BGR2GRAY)
                if needle.shape[0]>roi.shape[0] or needle.shape[1]>roi.shape[1]:continue
                _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,needle,cv2.TM_CCOEFF_NORMED))
                if best is None or score>best['score']:
                    best={'score':float(score),'bounds':[left+point[0],top+point[1],needle.shape[1],needle.shape[0]],'template':name}
        if not best or best['score']<.93:continue
        # Popup identity includes content, not its fixed rectangle or title.
        body=gray[y+round(ch*.2):y+round(ch*.8),x+round(cw*.1):x+round(cw*.85)]
        identity=hashlib.sha256((cv2.resize(body,(8,8),interpolation=cv2.INTER_AREA)//32).tobytes()).hexdigest()
        confirmed.append({'panel_bounds':[x,y,cw,ch],'edge_coverage':coverage,'close':best,'popup_id':identity})
    return confirmed[0] if len(confirmed)==1 else None
