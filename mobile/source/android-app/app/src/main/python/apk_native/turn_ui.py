"""Current source-pixel turn controls; observation scores do not grant inputs."""
import cv2,numpy as np

def structural_end(frame,items):
    h,w=frame.shape[:2]
    labels=[r for r in items if r.get('score',0)>=.98 and r.get('text','').replace(' ','')=='结束回合']
    if len(labels)!=1:return None
    label=labels[0];points=np.asarray(label['box']);a,b=points.min(axis=0);c,d=points.max(axis=0)
    if a<w*.75 or not h*.45<b<d<h*.82:return None
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY);white=np.uint8(gray>=145)
    contours,_=cv2.findContours(white*255,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    hits=[];pad=max(2,round(h*2/720))
    for contour in contours:
        x,y,bw,bh=cv2.boundingRect(contour)
        if not (.12*h<bw<.40*h and .035*h<bh<.11*h and x>w*.75 and .45*h<y<.82*h):continue
        if not (x<=a<c<=x+bw and y<=b<d<=y+bh):continue
        strips=(white[y:y+pad,x:x+bw],white[y+bh-pad:y+bh,x:x+bw],white[y:y+bh,x:x+pad],white[y:y+bh,x+bw-pad:x+bw])
        coverage=[float(strip.any(axis=0 if i<2 else 1).mean()) for i,strip in enumerate(strips)]
        if min(coverage)>=.94 and not any(max(abs(v-z) for v,z in zip([x,y,bw,bh],p['bounds']))<pad*2 for p in hits):
            hits.append(dict(bounds=[x,y,bw,bh],score=float(label['score']),edge_coverage=coverage,basis='current_ocr_and_four_control_sides'))
    return hits[0] if len(hits)==1 else None

def end_control(page,threshold=.93):
    if page.get('state')!='battle':return None
    if page.get('path')=='current_frame_local_label' and page.get('label_score',0)>=.97 and page.get('label_bounds'):
        return dict(bounds=page['label_bounds'],score=page['label_score'],basis='current_local_label')
    for name in ('end_turn_btn','end_turn_btn_white'):
        candidate=page.get('evidence',{}).get(name,{})
        if candidate.get('score',0)>=threshold and candidate.get('bounds'):
            return dict(bounds=candidate['bounds'],score=candidate['score'],basis='current_template')
    return None

def opponent_evidence(frame,page,detector):
    """Positive current label plus independent current end-button absence."""
    if page.get('state')!='opponent_turn':return None
    label=None
    if page.get('path')=='current_frame_local_label' and page.get('label_score',0)>=.97:
        label=page.get('label_bounds')
    else:
        for name in ('opponent_compact','opponent_standard'):
            hit=page.get('evidence',{}).get(name,{})
            if hit.get('score',0)>=.93:label=hit.get('bounds');break
        if label is None:
            for item in page.get('ocr_items',[]):
                if item.get('score',0)>=.98 and item.get('text','').replace(' ','')=='敌方':
                    pts=np.asarray(item['box']);a,b=pts.min(axis=0);c,d=pts.max(axis=0)
                    label=[float(a),float(b),float(c-a),float(d-b)];break
    if label is None:return None
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    # Full current-pixel search: filtered text candidates cannot establish absence.
    old=detector.mode;detector.mode='full'
    try:
        buttons={name:detector.match(gray,name) for name in ('end_turn_btn','end_turn_btn_white')}
    finally:detector.mode=old
    if any(hit.get('score',1)>=.82 for hit in buttons.values()):return None
    return dict(state='in_game',opponent_turn_label=dict(present=True,box=label),
                button=None,button_present=False,choice_modal=False,button_evidence=buttons)
