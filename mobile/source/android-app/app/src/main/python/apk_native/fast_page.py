"""Experimental local turn-label reuse with current-frame result checks."""
import cv2
import numpy as np
import time
from .page_detector import Detector
from .text_semantics import classify_text
from .result import ResultRecognizer
from .turn_ui import end_control,structural_end,current_turn_control


class FastPage:
    def __init__(self,engine,bank,clock=None):
        self.engine=engine
        self.clock=clock or time.monotonic
        self.last_result_probe=self.clock()
        self.pending_result_state=None
        self.detector=Detector(bank,'filtered',refine=True)
        self.labels={}
        self.results=ResultRecognizer(bank.get('result_continue_label'))
        self.shape=None
        self.count=0
        self.stats={'local_hits':0,'full_fallbacks':0,'ocr_calls':0,'overlay_checks':0}

    def inspect_result(self,frame,result):
        result['result_proof']=self.results.inspect(frame,result,self.engine)
        metrics=result.get('result_ocr')
        if metrics:
            result['ocr_used']=True
            self.last_ocr_ms=metrics['elapsed_ms']
            self.stats['ocr_calls']+=1

    def probe_turn_result(self,frame,result):
        """Bounded semantic discovery even when an old turn glyph stays visible."""
        if result.get('state') not in ('battle','opponent_turn'):return result
        now=self.clock()
        if 'ocr_items' not in result and now-self.last_result_probe<5.:return result
        self.last_result_probe=now
        candidate=dict(result)
        if 'ocr_items' not in candidate:
            candidate['ocr_items']=self.results.current_text(frame,candidate,self.engine)
            candidate['ocr_used']=True
            self.last_ocr_ms=candidate['result_ocr']['elapsed_ms']
            self.stats['ocr_calls']+=1
        words={row.get('text','').replace(' ','') for row in candidate['ocr_items'] if row.get('score',0)>=.90}
        titles=words&{'胜利','失败'}
        if len(titles)==1 and any(text.startswith('继续') for text in words):
            candidate['state']='result_victory' if '胜利' in titles else 'result_defeat'
            candidate['result_proof']=self.results.inspect(frame,candidate,self.engine)
            if candidate['result_proof']['ready']:
                self.pending_result_state=candidate['state']
                candidate['path']='current_scoped_result_probe'
                return candidate
        # Negative probes preserve this capture's turn observation and plan.
        result['ocr_used']=candidate.get('ocr_used',False)
        if 'result_ocr' in candidate:result['result_ocr']=candidate['result_ocr']
        result['result_probe']=dict(ready=False,reason=candidate.get('result_proof',{}).get('reason','no_current_result_controls'))
        return result

    def cache(self,frame,state,box):
        x,y,w,h=map(int,box)
        if w<8 or h<8:return
        self.labels[state]=(x,y,w,h,cv2.cvtColor(frame[y:y+h,x:x+w].copy(),cv2.COLOR_BGR2GRAY))

    def inspect_turn_control(self,frame,result):
        regional=getattr(self.engine,'regions',None)
        if regional is None or not getattr(self.engine,'supports_turn_controls',False):return False
        h,w=frame.shape[:2];left,top=round(w*.60),round(h*.32)
        regions=[[left,top,w-left,round(h*.92)-top]]
        started=time.perf_counter()
        found,_=regional(frame,regions,scope='turn_controls')
        elapsed=(time.perf_counter()-started)*1000
        items=[dict(box=np.asarray(b).tolist(),text=s,score=float(c)) for b,s,c in found or []]
        # Partial right-side text cannot replace the full result-label search.
        result['turn_ocr_items']=items
        result['turn_ocr']=dict(scope='turn_controls',regions=regions,elapsed_ms=elapsed,
                               capture_metrics=dict(getattr(self.engine,'last_metrics',{})))
        self.last_ocr_ms+=elapsed;self.stats['ocr_calls']+=1
        result['ocr_used']=True
        control=current_turn_control(frame,items)
        if control is None:return False
        result['state']=control['state']
        result['plan']={'action':None,'dispatch':'offline_only'}
        key='ocr_turn_control' if control['state']=='battle' else 'ocr_opponent_control'
        result[key]=control
        self.cache(frame,control['state'],control['bounds'])
        return True

    def local(self,gray):
        for state,(x,y,w,h,needle) in self.labels.items():
            if y+h>gray.shape[0] or x+w>gray.shape[1]:continue
            left,top=max(0,x-12),max(0,y-12)
            roi=gray[top:min(gray.shape[0],y+h+12),left:min(gray.shape[1],x+w+12)]
            _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,needle,cv2.TM_CCOEFF_NORMED))
            if score>=.97:
                return state,[left+point[0],top+point[1],w,h],float(score)
        return None

    def inspect_result_overlays(self,frame,gray,features):
        hsv=features.get('hsv') if features is not None else cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        boxes={}
        for key,text_mask in [('white',cv2.inRange(gray,165,255)),
                              ('orange',cv2.inRange(hsv,(5,80,80),(35,255,255)))]:
            text_mask=cv2.morphologyEx(text_mask,cv2.MORPH_CLOSE,np.ones((3,11),np.uint8))
            contours,_=cv2.findContours(text_mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            boxes[key]=[cv2.boundingRect(c) for c in contours
                if cv2.boundingRect(c)[2]>=12 and cv2.boundingRect(c)[3]>=8]
        evidence={}
        for name in ('defeat_banner','defeat_btn','victory_btn'):
            self.detector.text_boxes=boxes['orange' if name=='victory_btn' else 'white']
            self.detector.mode='filtered'
            evidence[name]=self.detector.match(gray,name)
            self.stats['overlay_checks']+=1
            if evidence[name]['ok']:
                state='result_victory' if name=='victory_btn' else 'result_defeat'
                result={'state':state,'plan':{'action':None,'dispatch':'offline_only'},
                        'path':'local_label_result_override','ocr_used':False,'evidence':evidence}
                self.inspect_result(frame,result)
                if (result['result_proof']['ready']
                        and result['result_proof'].get('basis')!='current_strong_result_template'):
                    self.pending_result_state=state
                return evidence,result
        return evidence,None

    def observe(self,frame,features=None):
        self.count+=1;ocr_used=False
        self.last_ocr_ms=0.
        pending_miss=None
        if self.shape!=frame.shape:
            self.labels.clear()
            self.detector.locations.clear()
            self.pending_result_state=None
            self.last_result_probe=self.clock()
            self.shape=frame.shape
        if self.pending_result_state is not None:
            # Discovery cadence must not delay the second independent frame.
            # ResultRecognizer checks the two current local crops first, then
            # requests fresh scoped OCR if either crop changed.
            pending=dict(state=self.pending_result_state,evidence={},
                         plan={'action':None,'dispatch':'offline_only'},
                         path='current_pending_result_probe',ocr_used=False)
            self.last_result_probe=self.clock()
            self.inspect_result(frame,pending)
            if pending['result_proof']['ready']:return pending
            self.pending_result_state=None
            pending_miss=pending
        gray=features.get('gray') if features is not None else cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        hit=self.local(gray)
        scoped={'state':'unknown'}
        if hit is None and self.inspect_turn_control(frame,scoped):
            # Current controls precede unrelated full-page template searches.
            # Result overlays retain their existing priority over the board.
            evidence,override=self.inspect_result_overlays(frame,gray,features)
            if override is not None:return override
            scoped.update(path='current_scoped_turn_control',evidence=evidence)
            if pending_miss is not None and 'result_ocr' in pending_miss:
                scoped['result_ocr']=pending_miss['result_ocr']
            return self.probe_turn_result(frame,scoped)
        # Recompute full-screen text candidates before every result check.
        # Use the same result evidence as the baseline; never reuse negatives.
        if hit:
            evidence,override=self.inspect_result_overlays(frame,gray,features)
            if override is not None:return override
            self.stats['local_hits']+=1
            result={'state':hit[0],'plan':{'action':None,'dispatch':'offline_only'},
                    'path':'current_frame_local_label','label_score':hit[2],
                    'label_bounds':hit[1], 'ocr_used':False,'evidence':evidence}
            if pending_miss is not None:
                result['ocr_used']=pending_miss.get('ocr_used',False)
                if 'result_ocr' in pending_miss:result['result_ocr']=pending_miss['result_ocr']
            return self.probe_turn_result(frame,result)
        self.stats['full_fallbacks']+=1
        result=self.detector.observe(frame,features)
        for key in ('turn_ocr','turn_ocr_items','ocr_used'):
            if key in scoped:result[key]=scoped[key]
        if result['state']=='battle':
            found=next((e for n,e in result['evidence'].items()
                        if n in ('end_turn_btn','end_turn_btn_white') and e['ok']),None)
            if found and found.get('score',0)>=.93:self.cache(frame,'battle',found['bounds'])
        elif result['state']=='opponent_turn':
            found=next((e for n,e in result['evidence'].items() if n.startswith('opponent_') and e['ok']),None)
            if found:self.cache(frame,'opponent_turn',found['bounds'])
        needs_control=result['state']=='unknown' or (result['state']=='battle' and end_control(result) is None)
        ocr_used=bool(result.get('ocr_used',False))
        if needs_control:
            started=time.perf_counter()
            found,_=self.engine(frame);ocr_used=True;self.stats['ocr_calls']+=1
            self.last_ocr_ms=(time.perf_counter()-started)*1000
            items=[{'box':np.asarray(b).tolist(),'text':s,'score':float(c)} for b,s,c in found or []]
            result['state'],result['plan']=classify_text(items)
            result['ocr_items']=items
            control=structural_end(frame,items)
            if control and result['state'] in ('battle','unknown'):
                result['state']='battle'
                result['ocr_turn_control']=control
                self.cache(frame,'battle',control['bounds'])
            if result['state']=='unknown':
                strong={r['text'].replace(' ','') for r in items if r['score']>=.90}
                titles=strong&{'胜利','失败'}
                if len(titles)==1 and any(text.startswith('继续') for text in strong):
                    proposed='result_victory' if '胜利' in titles else 'result_defeat'
                    candidate=dict(result,state=proposed)
                    proof=self.results.inspect(frame,candidate,self.engine)
                    if proof['ready']:
                        result['state']=proposed;result['result_proof']=proof
            label=next((r for r in items if r['score']>=.98 and
                        r['text'].replace(' ','') in ('敌方','结束回合')),None)
            if label and (result['state']=='opponent_turn' or result['state']=='unknown'):
                state='opponent_turn' if label['text'].replace(' ','')=='敌方' else 'battle'
                result['state']=state
                pts=np.asarray(label['box']);x,y=np.floor(pts.min(axis=0)).astype(int)
                x1,y1=np.ceil(pts.max(axis=0)).astype(int)
                self.cache(frame,state,[x,y,x1-x,y1-y])
        result.update(path='full_fallback',ocr_used=ocr_used)
        if result['state'] in ('result_victory','result_defeat'):
            self.inspect_result(frame,result)
            if (result['result_proof']['ready']
                    and result['result_proof'].get('basis')!='current_strong_result_template'):
                self.pending_result_state=result['state']
        if pending_miss is not None:
            result['ocr_used']=bool(result.get('ocr_used') or pending_miss.get('ocr_used'))
            if 'result_ocr' in pending_miss and 'result_ocr' not in result:result['result_ocr']=pending_miss['result_ocr']
        return self.probe_turn_result(frame,result)

