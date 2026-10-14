"""Experimental local turn-label reuse with current-frame result checks."""
import cv2
import numpy as np
import time
from .page_detector import Detector
from .text_semantics import classify_text
from .result import ResultRecognizer


class FastPage:
    def __init__(self,engine,bank):
        self.engine=engine
        self.detector=Detector(bank,'filtered',refine=True)
        self.labels={}
        self.results=ResultRecognizer(bank.get('result_continue_label'))
        self.shape=None
        self.count=0
        self.stats={'local_hits':0,'full_fallbacks':0,'ocr_calls':0,'overlay_checks':0}

    def cache(self,frame,state,box):
        x,y,w,h=map(int,box)
        if w<8 or h<8:return
        self.labels[state]=(x,y,w,h,cv2.cvtColor(frame[y:y+h,x:x+w].copy(),cv2.COLOR_BGR2GRAY))

    def local(self,gray):
        for state,(x,y,w,h,needle) in self.labels.items():
            if y+h>gray.shape[0] or x+w>gray.shape[1]:continue
            left,top=max(0,x-12),max(0,y-12)
            roi=gray[top:min(gray.shape[0],y+h+12),left:min(gray.shape[1],x+w+12)]
            _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,needle,cv2.TM_CCOEFF_NORMED))
            if score>=.97:
                return state,[left+point[0],top+point[1],w,h],float(score)
        return None

    def observe(self,frame,features=None):
        self.count+=1;ocr_used=False
        self.last_ocr_ms=0.
        if self.shape!=frame.shape:
            self.labels.clear()
            self.detector.locations.clear()
            self.shape=frame.shape
        gray=features.get('gray') if features is not None else cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        hit=self.local(gray)
        # Recompute full-screen text candidates before every result check.
        # Use the same result evidence as the baseline; never reuse negatives.
        if hit:
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
                self.detector.mode='filtered'
                self.stats['overlay_checks']+=1
                if evidence[name]['ok']:
                    state='result_victory' if name=='victory_btn' else 'result_defeat'
                    result={'state':state,'plan':{'action':None,'dispatch':'offline_only'},
                            'path':'local_label_result_override','ocr_used':False,'evidence':evidence}
                    result['result_proof']=self.results.inspect(frame,result,self.engine)
                    return result
            self.stats['local_hits']+=1
            return {'state':hit[0],'plan':{'action':None,'dispatch':'offline_only'},
                    'path':'current_frame_local_label','label_score':hit[2],
                    'label_bounds':hit[1], 'ocr_used':False,'evidence':evidence}
        self.stats['full_fallbacks']+=1
        result=self.detector.observe(frame,features)
        if result['state']=='battle':
            found=next((e for n,e in result['evidence'].items()
                        if n in ('end_turn_btn','end_turn_btn_white') and e['ok']),None)
            if found:self.cache(frame,'battle',found['bounds'])
        elif result['state']=='opponent_turn':
            found=next((e for n,e in result['evidence'].items() if n.startswith('opponent_') and e['ok']),None)
            if found:self.cache(frame,'opponent_turn',found['bounds'])
        if result['state']=='unknown':
            started=time.perf_counter()
            found,_=self.engine(frame);ocr_used=True;self.stats['ocr_calls']+=1
            self.last_ocr_ms=(time.perf_counter()-started)*1000
            items=[{'box':np.asarray(b).tolist(),'text':s,'score':float(c)} for b,s,c in found or []]
            result['state'],result['plan']=classify_text(items)
            result['ocr_items']=items
            if result['state']=='unknown':
                strong={r['text'].replace(' ','') for r in items if r['score']>=.98}
                titles=strong&{'胜利','失败'}
                if len(titles)==1 and '查看战场' in strong:
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
            result['result_proof']=self.results.inspect(frame,result,self.engine)
        return result

