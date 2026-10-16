"""Native-frame board prototype; relative row calibration remains experimental."""
import cv2,numpy as np

def _inverted_triangle_markers(frame,verified_card_boxes):
    """Use the existing triangle shape in the opposite vertical direction."""
    from .frontline_pattern import inspect as inspect_marker
    h=frame.shape[0]
    mirrored=np.ascontiguousarray(frame[::-1])
    boxes=[[x,h-y-ch,cw,ch] for x,y,cw,ch in verified_card_boxes]
    result=[]
    for proof in inspect_marker(mirrored,boxes,triangular=True,phase_consensus=True,
                                search_y_fraction=(.36,.73)):
        line=h-1-proof['line_y']
        if 0<=line<h:
            result.append(dict(proof,line_y=line,mirrored_line_y=proof['line_y'],
                               basis='distributed_inverted_triangle_phase_marker'))
    return result


def _repeated_frontline_ticks(gray,y,x0,x1,dy):
    """Distinguish a repeated frontline marker from a straight table seam."""
    h=gray.shape[0];reference=(gray[y-dy,x0:x1]+gray[y+dy,x0:x1])//2
    for offset in range(-max(3,round(h*12/720)),max(3,round(h*12/720))+1):
        row=np.uint8(reference-gray[y+offset,x0:x1]>25)
        row=cv2.morphologyEx(row[None,:],cv2.MORPH_CLOSE,np.ones((1,3),np.uint8))[0]
        delta=np.diff(np.r_[0,row.astype(int),0]);starts=np.where(delta==1)[0];ends=np.where(delta==-1)[0]
        if not 8<=len(starts)<=40 or not .35<=float(row.mean())<=.75:continue
        lengths=(ends-starts)[1:-1];gaps=(starts[1:]-ends[:-1])[1:-1]
        if not len(gaps) or not .015*h<=float(np.median(lengths)+np.median(gaps))<=.06*h:continue
        if (np.std(lengths)/np.mean(lengths)<=.25 and np.std(gaps)/np.mean(gaps)<=.25
                and all(.25<float(part.mean())<.85 for part in np.array_split(row,3))):return True
    return False

def frontline(frame,features=None,verified_card_boxes=()):
    h,w=frame.shape[:2]
    gray=(features.get('gray') if features is not None else cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)).astype(np.int16)
    # Adapt the production reference-row contrast test without resizing pixels.
    x0,x1=round(w*.30),round(w*.70)
    y0,y1=round(h*.27),round(h*.64);dy=max(1,round(h*16/720))
    center=gray[y0:y1,x0:x1]
    reference=(gray[y0-dy:y1-dy,x0:x1]+gray[y0+dy:y1+dy,x0:x1])//2
    contrast=(reference-center)>25
    # Current type plates inside complete card contours identify card bottoms.
    # Mask only their local pixels, rather than discard an entire image row.
    pad=max(2,round(h*3/720))
    for x,cy,cw,ch in verified_card_boxes:
        bottom=cy+ch
        a,b=max(0,bottom-pad-y0),min(y1-y0,bottom+pad+1-y0)
        left,right=max(0,x-x0),min(x1-x0,x+cw-x0)
        if a<b and left<right:contrast[a:b,left:right]=False
    scores=contrast.mean(axis=1)
    peak=int(np.argmax(scores));score=float(scores[peak]);other=scores.copy()
    other[max(0,peak-round(h*.025)):peak+round(h*.025)+1]=0
    rival=float(other.max());y=y0+peak
    owner='unknown'
    segments=[float(part.mean()) for part in np.array_split(contrast[peak],3)]
    # PC uses the widest dark structural peak, rather than absolute darkness.
    # A textured table can lose a few contrast pixels without losing the line:
    # require independent coverage in all three thirds plus a unique peak.
    distributed=score>=.75 and min(segments)>=.50 and score-rival>=.2
    repeated=False
    if not ((score>=.8 and score-rival>=.2) or distributed) and score>=.75:
        # A board seam can be almost as dark as the marker. Accept only one
        # independently repeated tick band among the separated strong peaks.
        candidates=[]
        for p in np.argsort(scores)[::-1]:
            if scores[p]<.75:break
            if all(abs(int(p)-prior)>round(h*.025) for prior in candidates):candidates.append(int(p))
        marked=[p for p in candidates if _repeated_frontline_ticks(gray,y0+p,x0,x1,dy)]
        repeated=len(marked)==1 and marked[0]==peak
    if (score>=.8 and score-rival>=.2) or distributed or repeated:
        # Relative positions are inherited from the existing observed layouts,
        # not evidence of arbitrary game UI scaling support.
        r=y/h
        if .34<=r<=.39:owner='our'
        elif .56<=r<=.62:owner='enemy'
        elif .46<=r<=.51:owner='empty'
    marker_proof=None
    # A perfectly continuous dark plank joint can become the unique maximum
    # when the real marker is hidden. Demand marker shape in this ambiguous
    # special case, rather than reinterpret the joint as ownership.
    uniform_stroke=score>=.995 and min(segments)>=.995 and not repeated
    if owner=='unknown' or uniform_stroke:
        if uniform_stroke:owner='unknown'
        from .frontline_pattern import inspect as inspect_marker
        patterns=[p for p in inspect_marker(frame,verified_card_boxes)
                  if any(a<=p['line_y']/h<=b for a,b in ((.34,.39),(.46,.51),(.56,.62)))]
        # A downward marker can have a strong rail but rival card/table structure.
        # Demand its own shape proof, without lowering the global peak margin.
        if not uniform_stroke and score>=.93 and min(segments)>=.90:
            inverted=[p for p in _inverted_triangle_markers(frame,verified_card_boxes)
                      if any(a<=p['line_y']/h<=b for a,b in ((.34,.39),(.46,.51),(.56,.62)))]
            for proof in inverted:
                if not any(abs(proof['line_y']-prior['line_y'])<=h*.025 for prior in patterns):
                    patterns.append(proof)
        if len(patterns)==1:
            candidate=patterns[0];r=candidate['line_y']/h
            near_peak=(candidate['basis']!='distributed_inverted_triangle_phase_marker'
                       or abs(candidate['line_y']-y)<=h*.015)
            if near_peak and .34<=r<=.39:owner='our'
            elif near_peak and .56<=r<=.62:owner='enemy'
            elif near_peak and .46<=r<=.51:owner='empty'
            if owner!='unknown':y=candidate['line_y'];marker_proof=candidate
    return {'owner':owner,'line_y':y,'score':score,'rival_score':rival,
            'excluded_card_count':len(verified_card_boxes),
            'rival_basis':'current_verified_card_bottom_pixels_excluded' if verified_card_boxes else 'all_structural_pixels',
            'segment_coverage':segments,'marker_proof':marker_proof,
            'basis':marker_proof['basis'] if marker_proof else 'unique_repeated_frontline_ticks' if repeated else 'pc_distributed_structural_peak' if score<.8 and distributed else 'original_unique_structural_peak',
            'calibration':'relative_existing_mobile_rows','input_authorized':False}

def board(frame,objects,features=None,*,frontline_result=None):
    h,w=frame.shape[:2];cards=[]
    # Multi-channel gradients retain card borders which share grayscale value
    # with the table (green paint is a common case).
    edges=features.get('edges') if features is not None else cv2.Canny(frame,40,100)
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    rectangles=[];scale=h/720
    for contour in contours:
        rx,ry,rw,rh=cv2.boundingRect(contour)
        if not (85*scale<rw<130*scale and 120*scale<rh<185*scale
                and cv2.contourArea(contour)>.85*rw*rh):continue
        if any(abs(rx-r[0])<12*scale and abs(ry-r[1])<14*scale for r in rectangles):continue
        rectangles.append([rx,ry,rw,rh])
    verified_card_boxes=[]
    for obj in objects:
        x,y,bw,bh=obj['box']
        matches=[r for r in rectangles if r[0]<=x<x+bw<=r[0]+r[2]
                 and r[1]<=y<y+bh<=r[1]+r[3] and y>r[1]+r[3]*.65]
        if len(matches)==1 and matches[0] not in verified_card_boxes:verified_card_boxes.append(matches[0])
    line=frontline(frame,features,verified_card_boxes) if frontline_result is None else frontline_result
    for obj in objects:
        x,y,bw,bh=obj['box']
        # Geometry is inferred from type plate dimensions and must be checked
        # against card edges before production use.
        cw,ch=round(bw*3.8),round(bh*5.2)
        left=round(x+bw/2-cw/2);top=round(y+bh-ch-4)
        matches=[r for r in rectangles if r[0]<=x<x+bw<=r[0]+r[2]
                 and r[1]<=y<y+bh<=r[1]+r[3] and y>r[1]+r[3]*.65]
        contour_verified=len(matches)==1
        if contour_verified:left,top,cw,ch=matches[0]
        valid=0<=left<left+cw<=w and 0<=top<top+ch<=h
        edge_scores=[]
        if valid:
            for xx in (left,left+cw):
                patch=edges[top:min(h,top+ch),max(0,xx-8):min(w,xx+9)]
                edge_scores.append(float((patch.max(axis=1)>0).mean()))
            patch=edges[max(0,top-8):min(h,top+9),left:left+cw]
            edge_scores.append(float((patch.max(axis=0)>0).mean()))
        verified=valid and min(edge_scores,default=0)>=.90
        cy=top+ch/2;row='unknown';side='unknown'
        if valid:
            if cy<h*.28:row,side='enemy_support','enemy'
            elif cy>h*.60:row,side='our_support','our'
            elif h*.32<cy<h*.56:
                row='front'
                if line['owner'] in ('our','enemy'):side=line['owner']
        cards.append({**obj,'card_box_estimate':[left,top,cw,ch],
                      'card_edges_verified':verified,'edge_coverage':edge_scores,'side':side,'row':row})
    support=[c for c in cards if c['row']=='our_support' and c['card_edges_verified']]
    # Four observed units can prove full without assuming detection complete.
    full=len(support)>=4
    support_rectangles=[r for r in rectangles if .60*h<r[1]+r[3]/2<.84*h]
    unknown_support=[r for r in support_rectangles if not any(
        c['card_box_estimate']==r for c in support)]
    return {'frontline':line,'cards':cards,'support_count_complete':False,
            'rectangles':rectangles,'support_rectangles':support_rectangles,
            'unclassified_support_rectangles':unknown_support,
            'support_observed':len(support),'support_full_confirmed':full,
            'plan':{'action':'wait','reason':'card_edges_or_action_color_unverified',
                    'dispatch':'offline_only'}}
