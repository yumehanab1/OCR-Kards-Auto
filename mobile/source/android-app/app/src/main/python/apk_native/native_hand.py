"""Native hand fee-plate candidates; local operation numeral, never card names."""
import cv2,numpy as np

def inspect(frame,features=None):
    h,w=frame.shape[:2];scale=h/720
    hsv=features.get('hsv') if features is not None else cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    value=hsv[:,:,2]
    result=[]
    for threshold in (75,85,95):
        _,labels,stats,_=cv2.connectedComponentsWithStats((value<threshold).astype(np.uint8),8)
        for idx,(x,y,bw,bh,area) in enumerate(stats[1:],1):
            if not (y>h*.80 and .12*w<x<w*.88 and y+bh<h and
                    19*scale<=bw<=38*scale and 19*scale<=bh<=38*scale and
                    .8<=bw/bh<=1.25 and .35<=area/(bw*bh)<=.90):continue
            component=(labels[y:y+bh,x:x+bw]==idx).astype(np.uint8)
            contours,_=cv2.findContours(component,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            contour=max(contours,key=cv2.contourArea);rect=cv2.minAreaRect(contour)
            rect_area=rect[1][0]*rect[1][1]
            if not rect_area or cv2.contourArea(contour)/rect_area<.88:continue
            cx,cy=x+bw/2,y+bh/2
            if any(abs(cx-r['center'][0])<12*scale and abs(cy-r['center'][1])<12*scale for r in result):continue
            crop=frame[y:y+bh,x:x+bw].copy();angle=(rect[2]+45)%90-45
            if angle:
                crop=cv2.warpAffine(crop,cv2.getRotationMatrix2D((bw/2,bh/2),angle,1),
                                   (bw,bh),borderMode=cv2.BORDER_REPLICATE)
            # Normalize only the confirmed small fee plate, never the screen.
            local=cv2.resize(crop,(28,28),interpolation=cv2.INTER_AREA)[3:-3,3:-3]
            lhsv=cv2.cvtColor(local,cv2.COLOR_BGR2HSV);v=lhsv[:,:,2].astype(int)
            base=np.percentile(v,25);ink=(v>base+35).astype(np.uint8)
            _,_,glyphs,_=cv2.connectedComponentsWithStats(ink,8)
            operation=[]
            for gx,gy,gw,gh,ga in glyphs[1:]:
                rx,ry=(gx+gw/2)/22,(gy+gh/2)/22
                if (.55<rx<.95 and .55<ry<.95 and 2<=gw<=7 and 2<=gh<=10
                    and 4<=ga<=45 and gx>0 and gy>0 and gx+gw<22 and gy+gh<22):
                    operation.append([int(gx),int(gy),int(gw),int(gh)])
            primary=ink[:,:13].astype(bool)
            orange=(lhsv[:,:13,0]>=8)&(lhsv[:,:13,0]<=32)&(lhsv[:,:13,1]>=140)&(lhsv[:,:13,2]>=80)
            fraction=float(orange[primary].mean()) if primary.sum()>=10 else 0.
            source_hsv=hsv[y:y+bh,x:x+bw]
            source_orange=(source_hsv[:,:,0]>=8)&(source_hsv[:,:,0]<=32)&(source_hsv[:,:,1]>=140)&(source_hsv[:,:,2]>=80)
            source_orange[:,round(bw*.58):]=False
            yy,xx=np.where(source_orange)
            digit_center=[float(x+np.mean(xx)),float(y+np.mean(yy))] if len(xx)>=10 else None
            result.append({'box':[int(x),int(y),int(bw),int(bh)],'center':[cx,cy],
                'kind':'unit' if operation else 'unknown','operation_numeral':operation,
                'suspected_order':not bool(operation),
                'suspected_order_basis':'complete_fee_plate_without_operation_component' if not operation else None,
                'orange':fraction>=.8,'orange_fraction':fraction,'angle':float(angle),
                'digit_center_source':digit_center,
                'grab_source':[digit_center[0]+25*scale,digit_center[1]+25*scale] if digit_center else None,
                'card_name':None,'input_authorized':False})
    return sorted(result,key=lambda r:r['center'][0])

def blind_blockers(badges,height,width):
    """Visible fan spans of suspect orders and explicitly unavailable cards.

    A card continues right of its fee plate until the next overlapping card.
    The old short fee-column exclusion left the rest of that same card usable.
    Account for the tilted edge down to the blind grab row as well.
    """
    scale=height/720;ordered=sorted(badges,key=lambda b:b['box'][0]);blocked=[]
    for i,b in enumerate(ordered):
        if not (b.get('suspected_order') or b.get('orange') is False):continue
        x,y,bw,bh=b['box']
        shift=abs(height*.91-(y+bh/2))*abs(np.tan(np.deg2rad(b.get('angle',0))))
        pad=20*scale+shift
        right=ordered[i+1]['box'][0] if i+1<len(ordered) else x+max(140*scale,bw+65*scale)
        blocked.append(dict(left=max(0,x-pad),right=min(width,right+pad),
                            suspected_order=bool(b.get('suspected_order')),
                            unavailable=b.get('orange') is False))
    return blocked

def blind_allowed(point,badges,height,width):
    return not any(b['left']<=point[0]<=b['right'] for b in blind_blockers(badges,height,width))

def blind_point(frame,badges):
    """Keep authorized unknown-card fallback outside known blocked fan spans."""
    h,w=frame.shape[:2]
    blocked=blind_blockers(badges,h,w)
    suspected=sum(b['suspected_order'] for b in blocked)
    unavailable=sum(b['unavailable'] for b in blocked)
    candidates=[w*f for f in (.50,.45,.55,.40,.60,.35,.65)]
    for x in candidates:
        if not any(b['left']<=x<=b['right'] for b in blocked):
            return {'point':[x,h*.91],'avoided_suspected':suspected,
                    'avoided_unavailable':unavailable,'blocked_spans':blocked,
                    'basis':'centre_near_point_outside_known_blocked_card_spans'}
    return {'point':None,'avoided_suspected':suspected,'avoided_unavailable':unavailable,
            'blocked_spans':blocked,'basis':'all_blind_candidates_overlap_suspected_orders'}
