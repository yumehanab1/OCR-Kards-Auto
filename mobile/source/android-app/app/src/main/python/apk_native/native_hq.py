"""HQ structural candidates, independent of country artwork. No vacancy authority."""
import cv2
import numpy as np


def inspect(frame,features=None,row='our_support'):
    found=[]
    for threshold in (70,85):
        for candidate in _inspect_dark(frame,features,row,threshold):
            x,y,w,h=candidate['shield_box']
            old=next((c for c in found if abs(c['shield_box'][0]+c['shield_box'][2]/2-x-w/2)<frame.shape[0]*8/720
                      and abs(c['shield_box'][1]-y)<frame.shape[0]*8/720),None)
            if old is None:found.append(candidate)
            elif candidate['edge_score']>old['edge_score']:found[found.index(old)]=candidate
    return found


def _inspect_dark(frame,features,row,threshold):
    h,w=frame.shape[:2];scale=h/720
    gray=features.get('gray') if features is not None else cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    mask=(gray<threshold).astype(np.uint8)
    low,high=(.61,.83) if row=='our_support' else (.20,.35)
    mask[:round(low*h)]=0;mask[round(high*h):]=0
    mask[:,:round(.25*w)]=0;mask[:,round(.75*w):]=0
    _,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
    edges=features.get('edges') if features is not None else cv2.Canny(frame,40,100)
    found=[]
    for component,(x,y,bw,bh,area) in enumerate(stats[1:],1):
        if not (40*scale<bw<70*scale and 42*scale<bh<75*scale
                and .58<area/(bw*bh)<.98 and .75<bw/bh<1.1):continue
        # A shield has a broad upper body and tapers at its foot. Stat plates
        # are rectangles and must not be reinterpreted as HQ merely by darkness.
        # Only this connected shield belongs to the outline. Dark camouflage
        # beside its tapered foot must not turn the shield into a rectangle.
        patch=(labels[y:y+bh,x:x+bw]==component).astype(np.uint8)
        widths=[]
        for a,b in ((0,round(bh*.25)),(round(bh*.4),round(bh*.65)),(round(bh*.85),bh)):
            occupied=np.where(patch[a:b].sum(axis=0)>=(b-a)*.5)[0]
            widths.append(int(occupied[-1]-occupied[0]+1) if len(occupied) else 0)
        if not (widths[0]>.8*bw and widths[1]>.7*bw and .15*bw<widths[2]<.80*bw):continue
        # Search card sides/top around the shield, rather than copying artwork.
        center=x+bw/2
        best=None
        for cw in range(round(80*scale),round(125*scale)+1,2):
            left=round(center-cw/2);right=left+cw
            # HQ shields have country-dependent placement and foot curvature.
            # Keep the positive taper + independent card edges, but search
            # the current frame rather than fix its top 95 px above a shield.
            for ty in range(round(y-125*scale),round(y-55*scale)+1,4):
                bottom=min(h,y+bh+round(12*scale))
                if left<5 or right+5>=w or ty<5:continue
                scores=[float((edges[ty:bottom,xx-4:xx+5].max(axis=1)>0).mean()) for xx in (left,right)]
                scores.append(float((edges[ty-4:ty+5,left:right].max(axis=0)>0).mean()))
                quality=min(scores)
                if best is None or quality>best[0]:best=(quality,[int(v) for v in (left,ty,cw,bottom-ty)],scores)
        found.append({'shield_box':[int(x),int(y),int(bw),int(bh)],'shield_widths':widths,
            'shield_threshold':threshold,
            'card_box':best[1] if best else None,'edge_score':best[0] if best else 0,
            'structural_candidate':bool(best and best[0]>=.85),
            'production_authority':False,'country_artwork_used':False})
    return found
