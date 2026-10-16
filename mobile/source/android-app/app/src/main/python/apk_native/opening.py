"""Source-pixel opening evidence; no capture or input dispatch."""
import cv2
import numpy as np
from pathlib import Path
from .page_detector import Detector

SOURCE_LABEL_FACTORS=(.80,.85,.90,.95,1.,1.05,1.10,1.15,1.20,1.25,1.30,1.35,1.40)

def opponent_mulligan_wait(frame,items):
    """A current central waiting caption is observation only, never a turn."""
    h,w=frame.shape[:2];matches=[]
    for row in items:
        text=row.get('text','');score=row.get('score',0)
        if not isinstance(text,str) or ''.join(text.split())!='敌方正在选择起始手牌':continue
        if not isinstance(score,(int,float,np.number)) or not np.isfinite(score) or score<.90:continue
        matches.append(row)
    if len(matches)!=1:return None
    row=matches[0]
    try:points=np.asarray(row.get('box',[]),dtype=float)
    except (TypeError,ValueError):return None
    if (points.ndim!=2 or points.shape[0]<3 or points.shape[1]!=2
            or not np.isfinite(points).all()):return None
    a,b=points.min(axis=0);c,d=points.max(axis=0)
    if (not (0<=a<c<=w and h*.25<=b<d<=h*.70)
            or abs((a+c)/2-w/2)>w*.15
            or cv2.contourArea(points.astype(np.float32))<=0):return None
    return dict(phase='WAITING_OPPONENT_MULLIGAN',score=float(row['score']),
                template_id='native_ocr_opponent_mulligan_wait',target_bounds=None,
                reason='current_centered_opponent_mulligan_wait',
                wait_label=dict(text=row['text'],score=float(row['score']),box=points.tolist(),
                                bounds=[float(a),float(b),float(c-a),float(d-b)]))

def text_button(frame,items,resources=False,label_threshold=.90):
    """The current opening title and confirm label locate the clickable target."""
    h,w=frame.shape[:2]
    def rows(text):
        return [r for r in items if r.get('score',0)>=label_threshold and r.get('text','').replace(' ','')==text]
    titles,confirms=rows('选择要替换的卡牌'),rows('确认')
    if len(titles)!=1 or len(confirms)!=1:return None
    title=np.asarray(titles[0]['box']);label=np.asarray(confirms[0]['box'])
    if any(points.ndim!=2 or points.shape[1]!=2 or len(points)<3 or not np.isfinite(points).all()
           or points[:,0].min()<0 or points[:,0].max()>w or points[:,1].min()<0 or points[:,1].max()>h
           for points in (title,label)):return None
    if (title[:,1].max()>h*.22 or abs(title[:,0].mean()-w/2)>w*.12
            or label[:,1].min()<h*.72 or abs(label[:,0].mean()-w/2)>w*.12):return None
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    pale=np.uint8((hsv[:,:,2]>=145)&(hsv[:,:,1]<=105))
    contours,_=cv2.findContours(pale*255,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    found=[];pad=max(2,round(h*3/720))
    for contour in contours:
        x,y,bw,bh=cv2.boundingRect(contour)
        if not (.25*h<bw<.6*h and .055*h<bh<.15*h and y>h*.72):continue
        if not (x<label[:,0].min()<label[:,0].max()<x+bw and y<label[:,1].min()<label[:,1].max()<y+bh):continue
        label_height=label[:,1].max()-label[:,1].min()
        if min(label[:,1].min()-y,y+bh-label[:,1].max())<label_height*.18:continue
        strips=(pale[y:y+pad,x:x+bw],pale[y+bh-pad:y+bh,x:x+bw],
                pale[y:y+bh,x:x+pad],pale[y:y+bh,x+bw-pad:x+bw])
        coverage=[float(strip.any(axis=0 if i<2 else 1).mean()) for i,strip in enumerate(strips)]
        if min(coverage)>=.94:found.append(dict(bounds=[x,y,bw,bh],edge_coverage=coverage))
    a,b=np.floor(label.min(axis=0)).astype(int);c,d=np.ceil(label.max(axis=0)).astype(int)
    if c<=a or d<=b:return None
    target=found[0] if len(found)==1 else dict(bounds=[int(a),int(b),int(c-a),int(d-b)],
                                            basis='current_confirm_text')
    return dict(target,score=min(titles[0]['score'],confirms[0]['score']),title=titles[0],confirm=confirms[0])

class OpeningRecognizer:
    def __init__(self,assets):
        names=('mulligan_title','mulligan_title_compact','mulligan_ok_btn','mulligan_ok_btn_compact',
               'end_turn_btn','end_turn_btn_white')
        bank={name:cv2.imdecode(np.frombuffer((Path(assets)/(name+'.png')).read_bytes(),np.uint8),1) for name in names}
        from apk_enemy_turn import _template
        for layout in ('compact','standard'):
            bank['opponent_'+layout]=cv2.cvtColor(_template(layout),cv2.COLOR_GRAY2BGR)
        if any(value is None for value in bank.values()):raise ValueError('native_opening_template_missing')
        self.detector=Detector(bank,'filtered',refine=True);self.shape=None;self.opening_labels=[]
        import json
        spec=Path(assets)/'native_turn_source.json'
        self.source_turn=None
        self.source_opening=None
        source=Path(assets)/'native_opening_source.json'
        if source.is_file():
            meta=json.loads(source.read_text(encoding='utf8'))
            self.source_opening=(meta['source_height'],[(row['text'],cv2.imdecode(np.frombuffer((Path(assets)/row['file']).read_bytes(),np.uint8),0)) for row in meta['labels']])
        if spec.is_file():
            meta=json.loads(spec.read_text(encoding='utf8'))
            self.source_turn=(cv2.imdecode(np.frombuffer((Path(assets)/meta['file']).read_bytes(),np.uint8),0),meta['source_height'])

    def observe(self,frame,packet,ocr=None):
        from .recognition_scale import shrink,restore
        if frame is None:return self.observe_pixels(frame,packet,ocr)
        if list(frame.shape[:2])!=[packet.get('source_height'),packet.get('source_width')]:
            return dict(phase='UNKNOWN',score=0.,template_id='',target_bounds=None,reason='native_opening_geometry_mismatch')
        scaled,factors=shrink(frame)
        if factors==(1.,1.):return self.observe_pixels(frame,packet,ocr)
        reduced=dict(packet,source_height=scaled.shape[0],source_width=scaled.shape[1])
        return restore(self.observe_pixels(scaled,reduced,ocr),frame,scaled,factors)

    def observe_pixels(self,frame,packet,ocr=None):
        unknown=dict(phase='UNKNOWN',score=0.,template_id='',target_bounds=None,coordinate_space='source_pixels')
        if (frame is None or frame.ndim!=3 or packet.get('coordinate_space')!='source_pixels'
                or list(frame.shape[:2])!=[packet.get('source_height'),packet.get('source_width')]):
            return dict(unknown,reason='native_opening_geometry_mismatch')
        h,w=frame.shape[:2]
        if not 1.70<=w/h<=2.30:return dict(unknown,reason='unsupported_native_opening_aspect')
        if self.shape!=frame.shape:self.detector.locations.clear();self.opening_labels=[];self.shape=frame.shape
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY);hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        full_items=None
        from .resource_anchors import inspect as inspect_resources
        resource_anchors=inspect_resources(frame,hsv)
        resources=resource_anchors['ok']
        unknown['resource_anchors']=resource_anchors
        # Current right-side control is independent of opening text. Search
        # the source pixels directly before unrelated whole-page templates.
        if self.source_turn:
            template,source_height=self.source_turn
            left,top=round(w*.75),round(h*.45)
            roi=gray[top:round(h*.82),left:w];best=None
            for factor in np.arange(.90,1.101,.01):
                size=h/source_height*factor
                needle=cv2.resize(template,(round(template.shape[1]*size),round(template.shape[0]*size)))
                if needle.shape[0]>roi.shape[0] or needle.shape[1]>roi.shape[1]:continue
                _,value,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,needle,cv2.TM_CCOEFF_NORMED))
                if best is None or value>best['score']:
                    best=dict(score=float(value),bounds=[left+point[0],top+point[1],needle.shape[1],needle.shape[0]])
            board=gray[round(h*.125):round(h*.855),round(w*.15):round(w*.85)]
            if best and best['score']>=.94:
                # Current opening-title absence, never a cached negative.
                absent=True;absence={}
                labels=self.source_opening[1] if self.source_opening else []
                for text,label in labels:
                    if text=='确认':continue
                    region=gray[:round(h*.22),round(w*.30):round(w*.70)];highest=-1.
                    for factor in SOURCE_LABEL_FACTORS:
                        size=h/self.source_opening[0]*factor
                        target=cv2.resize(label,(round(label.shape[1]*size),round(label.shape[0]*size)))
                        if target.shape[0]>region.shape[0] or target.shape[1]>region.shape[1]:continue
                        highest=max(highest,float(cv2.minMaxLoc(cv2.matchTemplate(region,target,cv2.TM_CCOEFF_NORMED))[1]))
                    absence[text]=highest
                    if highest>=.70:absent=False
                if labels and absent:
                    return dict(unknown,phase='CONFIRMED_MY_TURN',score=best['score'],
                                template_id='native_source_end_control',target_bounds=best['bounds'],
                                reason='current_source_end_opening_title_absent',resources=resources,
                                evidence={'end_turn_btn':best},opening_title_absence=absence)
        if ocr is not None:
            from .opening_dynamic import inspect as dynamic_opening
            dynamic=dynamic_opening(frame,ocr,resources)
            unknown['dynamic_opening']=dynamic
            if dynamic['ready']:
                structural=dynamic['structure']
                return dict(unknown,phase='MULLIGAN_CONFIRM',score=structural['score'],
                            template_id='native_dynamic_opening_controls',target_bounds=structural['bounds'],
                            reason='current_scoped_ocr_title_confirm',structure=structural,resources=resources)
        current=[]
        for text,(x,y,bw,bh,needle) in self.opening_labels:
            left,top=max(0,x-12),max(0,y-12);roi=gray[top:min(h,y+bh+12),left:min(w,x+bw+12)]
            _,score,_,position=cv2.minMaxLoc(cv2.matchTemplate(roi,needle,cv2.TM_CCOEFF_NORMED))
            if score<.98:break
            a,b=left+position[0],top+position[1]
            current.append(dict(text=text,score=float(score),box=[[a,b],[a+bw,b],[a+bw,b+bh],[a,b+bh]]))
        structural=text_button(frame,current,resources) if len(current)==2 else None
        if structural:
            return dict(unknown,phase='MULLIGAN_CONFIRM',score=structural['score'],
                        template_id='native_current_opening_labels',target_bounds=structural['bounds'],
                        reason='current_two_opening_labels',structure=structural,resources=resources)
        if self.source_opening:
            source_height,labels=self.source_opening;current=[]
            unknown['source_opening_label_proposals']=[]
            for text,template in labels:
                # Search current original pixels about the screen centre;
                # source template dimensions follow height only.
                left,right=round(w*.30),round(w*.70)
                top,bottom=(0,round(h*.22)) if text!='确认' else (round(h*.72),h)
                roi=gray[top:bottom,left:right];best=None
                factors=list(SOURCE_LABEL_FACTORS)
                for index,factor in enumerate(factors):
                    scale=h/source_height*factor;th,tw=template.shape
                    needle=cv2.resize(template,(round(tw*scale),round(th*scale)))
                    if needle.shape[0]>roi.shape[0] or needle.shape[1]>roi.shape[1]:continue
                    _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,needle,cv2.TM_CCOEFF_NORMED))
                    if best is None or score>best['score']:
                        x,y=left+point[0],top+point[1];bh,bw=needle.shape
                        best=dict(text=text,score=float(score),factor=float(factor),box=[[x,y],[x+bw,y],[x+bw,y+bh],[x,y+bh]])
                    if index==len(SOURCE_LABEL_FACTORS)-1 and best and .75<=best['score']<.94:
                        factors.extend(float(v) for v in np.arange(max(.75,best['factor']-.05),
                                      min(1.45,best['factor']+.05)+.001,.01))
                unknown['source_opening_label_proposals'].append(best)
                if best is None or best['score']<.94:break
                current.append(best)
            structural=text_button(frame,current,resources,label_threshold=.94) if len(current)==2 else None
            if structural:
                return dict(unknown,phase='MULLIGAN_CONFIRM',score=structural['score'],
                            template_id='native_source_opening_labels',target_bounds=structural['bounds'],
                            reason='current_two_source_opening_labels',structure=structural,resources=resources)
        masks=(cv2.inRange(gray,165,255),cv2.inRange(hsv,(5,80,80),(35,255,255)))
        boxes=[]
        for mask in masks:
            mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,11),np.uint8))
            contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            boxes.extend(cv2.boundingRect(c) for c in contours if cv2.boundingRect(c)[2]>=12)
        self.detector.text_boxes=boxes
        evidence={name:self.detector.match(gray,name) for name in self.detector.bank}
        for name,found in evidence.items():
            if not .75 <= found['score'] < .94 or not found.get('bounds'):continue
            x,y,bw,bh=found['bounds'];pad=max(12,round(h*.03))
            left,top=max(0,x-pad),max(0,y-pad)
            roi=gray[top:min(h,y+bh+pad),left:min(w,x+bw+pad)]
            template=self.detector.bank[name];th,tw=template.shape[:2]
            factor0=found['factor']
            for factor in np.arange(factor0-.10,factor0+.101,.01):
                scale=h/720*factor
                needle=cv2.cvtColor(cv2.resize(template,(max(8,round(tw*scale)),max(8,round(th*scale)))),cv2.COLOR_BGR2GRAY)
                if roi.shape[0]<needle.shape[0] or roi.shape[1]<needle.shape[1]:continue
                _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,needle,cv2.TM_CCOEFF_NORMED))
                if score>found['score']:
                    found=dict(found,score=float(score),bounds=[left+point[0],top+point[1],needle.shape[1],needle.shape[0]],search='opening_refined_current_frame')
            evidence[name]=found
        # The two visible opening labels locate the action independently of HQs.
        for suffix in ('','_compact'):
            title=evidence['mulligan_title'+suffix];button=evidence['mulligan_ok_btn'+suffix]
            if min(title['score'],button['score'])<.94:continue
            tx,ty,tw,th=title['bounds'];bx,by,bw,bh=button['bounds']
            if (ty+th<h*.22 and by>h*.72
                    and abs(tx+tw/2-w/2)<w*.12 and abs(bx+bw/2-w/2)<w*.12):
                return dict(unknown,phase='MULLIGAN_CONFIRM',score=min(title['score'],button['score']),
                    template_id='mulligan_ok_btn'+suffix,target_bounds=button['bounds'],
                    reason='native_title_confirm',evidence=evidence,resources=resources)
        opening_proposed=any(min(evidence['mulligan_title'+suffix]['score'],
                                 evidence['mulligan_ok_btn'+suffix]['score'])>=.75
                             for suffix in ('','_compact'))
        if ocr is not None and opening_proposed:
            found,_=ocr(frame)
            items=[dict(box=np.asarray(box).tolist(),text=text,score=float(score)) for box,text,score in found or []]
            full_items=items
            waiting=opponent_mulligan_wait(frame,full_items)
            if waiting:return dict(unknown,**waiting,evidence=evidence,resources=resources)
            structural=text_button(frame,items,resources)
            if structural:
                self.opening_labels=[]
                for label in (structural['title'],structural['confirm']):
                    pts=np.asarray(label['box']);x,y=map(int,np.floor(pts.min(axis=0)));a,b=map(int,np.ceil(pts.max(axis=0)))
                    if 0<=x<a<=w and 0<=y<b<=h:
                        self.opening_labels.append((label['text'],(x,y,a-x,b-y,gray[y:b,x:a].copy())))
                return dict(unknown,phase='MULLIGAN_CONFIRM',score=structural['score'],
                    template_id='native_ocr_confirm_structure',target_bounds=structural['bounds'],
                    reason='current_ocr_title_confirm',evidence=evidence,structure=structural,resources=resources)
        end=max((evidence[name] for name in ('end_turn_btn','end_turn_btn_white')),key=lambda e:e['score'])
        if self.source_turn is not None and end['score']>=.75:
            needle,source_height=self.source_turn
            x,y,bw,bh=end['bounds'];pad=round(h*.05);left,top=max(0,x-pad),max(0,y-pad)
            roi=gray[top:min(h,y+bh+pad),left:min(w,x+bw+pad)]
            for factor in np.arange(.90,1.101,.01):
                scale=h/source_height*factor
                target=cv2.resize(needle,(round(needle.shape[1]*scale),round(needle.shape[0]*scale)))
                if target.shape[0]>roi.shape[0] or target.shape[1]>roi.shape[1]:continue
                _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,target,cv2.TM_CCOEFF_NORMED))
                if score>end['score']:end=dict(score=float(score),bounds=[left+point[0],top+point[1],target.shape[1],target.shape[0]],basis='source_template_current_frame')
        opening_absent=max(evidence[n]['score'] for n in evidence if n.startswith('mulligan_'))<.70
        opponent=max((evidence[name] for name in ('opponent_compact','opponent_standard')),key=lambda e:e['score'])
        if opening_absent and end['score']<.82:
            # Grey enemy text is absent from the white/orange candidate mask.
            left,top=round(w*.75),round(h*.45)
            region=gray[top:round(h*.82),left:w]
            for name in ('opponent_compact','opponent_standard'):
                template=cv2.cvtColor(self.detector.bank[name],cv2.COLOR_BGR2GRAY)
                for factor in np.arange(.75,1.451,.025):
                    size=h/720*float(factor)
                    needle=cv2.resize(template,(round(template.shape[1]*size),round(template.shape[0]*size)))
                    if needle.shape[0]>region.shape[0] or needle.shape[1]>region.shape[1]:continue
                    _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(region,needle,cv2.TM_CCOEFF_NORMED))
                    if score>opponent['score']:
                        opponent=dict(score=float(score),bounds=[left+point[0],top+point[1],needle.shape[1],needle.shape[0]])
            evidence['opponent_local']=opponent
        if opponent['score']>=.94 and opening_absent and end['score']<.82:
            x,y,bw,bh=opponent['bounds']
            if x>w*.75 and .45*h<y<.82*h:
                return dict(unknown,phase='CONFIRMED_OPPONENT_TURN',score=opponent['score'],
                    template_id='native_opponent_turn',target_bounds=opponent['bounds'],
                    reason='current_enemy_label_opening_and_own_control_absent',evidence=evidence)
        if end['score']>=.94 and opening_absent:
            x,y,bw,bh=end['bounds']
            if x>w*.75 and .45*h<y<.82*h:
                return dict(unknown,phase='CONFIRMED_MY_TURN',score=end['score'],template_id='native_end_turn',
                    target_bounds=end['bounds'],reason='native_end_turn',evidence=evidence,resources=resources)
        # A new device may render every saved turn glyph differently. Current
        # semantic turn controls are an independent handoff, not a refinement
        # which first needs a near-match to an old template or HQ geometry.
        if ocr is not None:
            if full_items is None:
                found,_=ocr(frame)
                full_items=[dict(box=np.asarray(box).tolist(),text=text,score=float(score)) for box,text,score in found or []]
            waiting=opponent_mulligan_wait(frame,full_items)
            if waiting:return dict(unknown,**waiting,evidence=evidence,resources=resources)
            structural=text_button(frame,full_items,resources)
            if structural:
                return dict(unknown,phase='MULLIGAN_CONFIRM',score=structural['score'],
                    template_id='native_ocr_opening_controls',target_bounds=structural['bounds'],
                    reason='current_ocr_title_confirm',structure=structural,resources=resources)
            words={row.get('text','').replace(' ','') for row in full_items if row.get('score',0)>=.90}
            if {'选择要替换的卡牌','确认'}<=words:
                return dict(unknown,reason='current_opening_controls_still_present',evidence=evidence,resources=resources)
            from .turn_ui import structural_end
            control=structural_end(frame,full_items)
            if control:
                return dict(unknown,phase='CONFIRMED_MY_TURN',score=control['score'],template_id='native_ocr_end_structure',
                    target_bounds=control['bounds'],reason='current_end_text',evidence=evidence,structure=control,resources=resources)
            labels={'敌方':[],'结束回合':[]}
            for row in full_items:
                text=row.get('text','').replace(' ','')
                if text not in labels or row.get('score',0)<.93:continue
                points=np.asarray(row.get('box',[]),dtype=float)
                if points.ndim!=2 or points.shape[0]<3 or points.shape[1]!=2 or not np.isfinite(points).all():continue
                a,b=points.min(axis=0);c,d=points.max(axis=0)
                if not (.60*w<a<c<=w and .35*h<b<d<.90*h):continue
                labels[text].append(dict(row,bounds=[float(a),float(b),float(c-a),float(d-b)]))
            if len(labels['敌方'])==1 and not labels['结束回合']:
                label=labels['敌方'][0]
                return dict(unknown,phase='CONFIRMED_OPPONENT_TURN',score=label['score'],
                    template_id='native_ocr_opponent_turn',target_bounds=label['bounds'],
                    reason='current_enemy_text_without_own_control',evidence=evidence,resources=resources)
        return dict(unknown,reason='native_opening_unconfirmed',evidence=evidence,resources=resources)

_recognizers={}
def observe(path,assets,packet_json,bridge=None):
    import json
    packet=json.loads(str(packet_json));key=str(assets)
    recognizer=_recognizers.get(key)
    if recognizer is None:
        recognizer=OpeningRecognizer(assets);_recognizers[key]=recognizer
    frame=cv2.imdecode(np.frombuffer(Path(path).read_bytes(),np.uint8),1)
    ocr=None
    if bridge is not None:
        from .ocr_bridge import NativeOCR
        ocr=NativeOCR(bridge);ocr.bind(packet)
    return json.dumps(recognizer.observe(frame,packet,ocr),ensure_ascii=False)
