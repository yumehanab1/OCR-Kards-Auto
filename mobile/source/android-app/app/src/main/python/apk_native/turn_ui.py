"""Current source-pixel turn controls; observation scores do not grant inputs."""
import cv2,numpy as np

def structural_end(frame,items):
    h,w=frame.shape[:2]
    labels=[r for r in items if r.get('score',0)>=.93 and r.get('text','').replace(' ','')=='结束回合']
    if len(labels)!=1:return None
    label=labels[0];points=np.asarray(label.get('box',[]),dtype=float)
    if points.ndim!=2 or points.shape[0]<3 or points.shape[1]!=2 or not np.isfinite(points).all():return None
    a,b=points.min(axis=0);c,d=points.max(axis=0)
    if not (.60*w<a<c<=w and h*.35<b<d<h*.90):return None
    for row in items:
        if row.get('score',0)<.93 or row.get('text','').replace(' ','')!='敌方':continue
        p=np.asarray(row.get('box',[]),dtype=float)
        if p.ndim!=2 or p.shape[0]<3 or p.shape[1]!=2 or not np.isfinite(p).all():continue
        if p[:,0].mean()>.60*w and h*.35<p[:,1].mean()<h*.90:return None
    return dict(bounds=[float(a),float(b),float(c-a),float(d-b)],score=float(label['score']),
                basis='current_ocr_end_control')


def current_turn_control(frame,items):
    """A bounded OCR read provides its current control, never a full page."""
    own=structural_end(frame,items)
    if own:return dict(own,state='battle')
    h,w=frame.shape[:2];labels={'敌方':[],'结束回合':[]}
    for row in items:
        text=row.get('text','').replace(' ','')
        if text not in labels or row.get('score',0)<.93:continue
        points=np.asarray(row.get('box',[]),dtype=float)
        if points.ndim!=2 or points.shape[0]<3 or points.shape[1]!=2 or not np.isfinite(points).all():continue
        a,b=points.min(axis=0);c,d=points.max(axis=0)
        if .60*w<a<c<=w and .35*h<b<d<.90*h:
            labels[text].append(dict(bounds=[float(a),float(b),float(c-a),float(d-b)],score=float(row['score'])))
    if len(labels['敌方'])==1 and not labels['结束回合']:
        return dict(labels['敌方'][0],state='opponent_turn',basis='current_ocr_opponent_control')
    return None

def end_control(page,threshold=.93):
    if page.get('state')!='battle':return None
    semantic=page.get('ocr_turn_control') or {}
    if semantic.get('score',0)>=threshold and semantic.get('bounds'):
        return dict(semantic)
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
        semantic=page.get('ocr_opponent_control') or {}
        if semantic.get('score',0)>=.93:label=semantic.get('bounds')
        for name in ('opponent_compact','opponent_standard'):
            hit=page.get('evidence',{}).get(name,{})
            if label is None and hit.get('score',0)>=.93:label=hit.get('bounds');break
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
