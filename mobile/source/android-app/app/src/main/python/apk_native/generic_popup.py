"""Current-frame rectangular promotion panel and visible close-X evidence."""
import cv2
import numpy as np
import hashlib


def _inspect_templates(frame, close_templates):
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


def _cross_shape(component):
    """Measure two complete diagonal strokes; scores are geometric ratios."""
    bh,bw=component.shape
    yy,xx=np.nonzero(component)
    if not len(xx):return None
    u=xx/max(1,bw-1);v=yy/max(1,bh-1)
    purity=float(((abs(u-v)<=.19)|(abs(u+v-1)<=.19)).mean())
    fill=float(len(xx)/(bw*bh))
    arms=[];radius=max(1,round(min(bw,bh)*.12))
    for reverse in (False,True):
        for start,end in ((.05,.45),(.55,.95)):
            samples=[]
            for t in np.linspace(start,end,12):
                x=round(t*(bw-1));y=round((1-t if reverse else t)*(bh-1))
                samples.append(bool(component[max(0,y-radius):min(bh,y+radius+1),
                                              max(0,x-radius):min(bw,x+radius+1)].any()))
            arms.append(float(np.mean(samples)))
    diagonals=[min(arms[:2]),min(arms[2:])]
    if min(diagonals)<.70 or purity<.68 or not .10<=fill<=.70:return None
    score=float(min(diagonals)*purity)
    return dict(diagonal_coverage=diagonals,arm_coverage=arms,diagonal_purity=purity,
                fill_ratio=fill,shape_score=score,score=score,basis='current_close_x_geometry')


def inspect_geometry(frame):
    h,w=frame.shape[:2];gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV);edges=cv2.Canny(gray,40,100)
    joined=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_=cv2.findContours(joined,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    proposals=[cv2.boundingRect(c) for c in contours]
    horizontal=cv2.morphologyEx(edges,cv2.MORPH_OPEN,np.ones((1,max(20,round(w*.22))),np.uint8))
    lines,_=cv2.findContours(horizontal,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    measured=[cv2.boundingRect(c) for c in lines]
    for x,y,bw,_ in measured:
        for bx,by,cw,_ in measured:
            if by>y and abs(x-bx)<h*.025 and abs(bw-cw)<h*.05:
                proposals.append((min(x,bx),y,max(x+bw,bx+cw)-min(x,bx),by-y+1))
    panels=[];pad=max(2,round(h*.01))
    for x,y,bw,bh in proposals:
        if not (.25*w<bw<.80*w and .20*h<bh<.85*h and x>=0 and y>=h*.05
                and x+bw<=w and y+bh<=h and abs(x+bw/2-w/2)<w*.15):continue
        strips=(edges[max(0,y-pad):y+pad+1,x:x+bw],edges[max(0,y+bh-pad):min(h,y+bh+pad+1),x:x+bw],
                edges[y:y+bh,max(0,x-pad):x+pad+1],edges[y:y+bh,max(0,x+bw-pad):min(w,x+bw+pad+1)])
        coverage=[float((strip>0).any(axis=0 if i<2 else 1).mean()) for i,strip in enumerate(strips)]
        if sum(value>=.65 for value in coverage)<2:continue
        if any(max(abs(a-b) for a,b in zip((x,y,bw,bh),panel[:4]))<=pad*2 for panel in panels):continue
        panels.append((x,y,bw,bh,coverage))
    if not panels:return None
    crosses=[]
    for saturation,value in ((45,130),(45,175),(90,130),(90,175)):
        mask=cv2.inRange(hsv,(0,0,value),(179,saturation,255))
        mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((2,2),np.uint8))
        _,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
        for index,(x,y,bw,bh,area) in enumerate(stats[1:],1):
            if not (max(6,h*.008)<=min(bw,bh) and max(bw,bh)<=h*.07 and .65<bw/bh<1.5):continue
            component=np.uint8(labels[y:y+bh,x:x+bw]==index)
            shape=_cross_shape(component)
            if shape is None:continue
            # A close glyph is isolated from adjacent caption letters. This
            # excludes a printed X inside a word without reading that word.
            gap=max(2,round(bw*.70))
            neighboring=int(np.count_nonzero(mask[y:y+bh,max(0,x-gap):x]))
            neighboring+=int(np.count_nonzero(mask[y:y+bh,x+bw:min(w,x+bw+gap)]))
            if neighboring>area*.45:continue
            shape['bounds']=[int(x),int(y),int(bw),int(bh)]
            if any(max(abs(a-b) for a,b in zip(shape['bounds'],old['bounds']))<=max(3,h*.006) for old in crosses):continue
            crosses.append(shape)
    confirmed=[]
    for close in crosses:
        x,y,bw,bh=close['bounds']
        options=[]
        for px,py,pw,ph,coverage in panels:
            if not (px+pw*.75<=x and x+bw<=px+pw+1 and py<=y and y+bh<=py+ph*.25):continue
            options.append((sum(coverage),px,py,pw,ph,coverage))
        if not options:continue
        _,px,py,pw,ph,coverage=max(options,key=lambda row:row[0])
        body=gray[py+round(ph*.2):py+round(ph*.8),px+round(pw*.1):px+round(pw*.85)]
        identity=hashlib.sha256((cv2.resize(body,(8,8),interpolation=cv2.INTER_AREA)//32).tobytes()).hexdigest()
        confirmed.append(dict(basis='current_close_x_geometry',panel_bounds=[int(px),int(py),int(pw),int(ph)],
                              edge_coverage=coverage,close=close,popup_id=identity))
    return confirmed[0] if len(confirmed)==1 else None


def inspect(frame, close_templates):
    strict=_inspect_templates(frame,close_templates) if close_templates else None
    return strict or inspect_geometry(frame)
