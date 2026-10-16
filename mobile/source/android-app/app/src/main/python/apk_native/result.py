"""Result proof from a strong template or current result title and continue."""
import cv2,numpy as np
import time

class ResultRecognizer:
    def __init__(self,continue_template=None):
        self.shape=None;self.labels={};self.continue_template=continue_template

    @staticmethod
    def current_text(frame,page,ocr):
        """Read result controls using the existing capture-bound region API.

        The third region is retained for the Java request contract; its text
        is optional observation evidence and never a result prerequisite.
        """
        h,w=frame.shape[:2]
        regions=[[round(w*.35),round(h*.35),round(w*.30),round(h*.48)],
                 [round(w*.35),round(h*.84),round(w*.30),round(h*.14)],
                 [round(w*.75),0,w-round(w*.75),round(h*.20)]]
        started=time.perf_counter()
        regional=getattr(ocr,'regions',None)
        result=regional(frame,regions,scope='result_controls') if regional is not None else ocr(frame)
        found=(result[0] if result is not None else None) or []
        page['result_ocr']=dict(scope='result_controls' if regional is not None else 'full_frame',
            regions=regions,elapsed_ms=(time.perf_counter()-started)*1000,
            capture_metrics=dict(getattr(ocr,'last_metrics',{})))
        return [dict(box=np.asarray(box).tolist(),text=text,score=float(score)) for box,text,score in found]

    def merged_continue(self,frame,page,name,words):
        if len(words.get(name,[]))!=1:return None
        if words.get('继续'):return None
        cues=[r for r in page.get('ocr_items',[]) if r.get('score',0)>=.90
              and r['text'].replace(' ','').startswith('继续') and r['text'].replace(' ','')!='继续']
        if len(cues)!=1:return None
        # OCR may join a continuation caption to adjacent text. Its current
        # box is still the control proposal; no saved glyph must reconfirm it.
        return dict(cues[0],basis='current_continue_text_prefix')
    @staticmethod
    def geometry(shape,rows,banner=None):
        h,w=shape[:2];label=rows['result'];continuation=rows['继续']
        def center(row):
            pts=np.asarray(row.get('box',[]),dtype=float)
            if (pts.ndim!=2 or pts.shape[0]<3 or pts.shape[1]!=2
                    or not np.isfinite(pts).all()):return None
            if not (pts[:,0].min()>=0 and pts[:,1].min()>=0
                    and pts[:,0].max()<=w and pts[:,1].max()<=h
                    and np.ptp(pts[:,0])>0 and np.ptp(pts[:,1])>0):return None
            return pts.mean(axis=0)
        title=center(label);button=center(continuation)
        if title is None or button is None:return False
        x,y=title;cx,cy=button
        return (.25*w<x<.75*w and .25*h<y<.85*h and abs(cx-w/2)<.20*w
                and .72*h<cy<.99*h and cy>y+.08*h)
    def inspect(self,frame,page,ocr):
        state=page.get('state')
        if state not in ('result_victory','result_defeat'):
            return dict(ready=False,reason='not_result_page')
        name='胜利' if state=='result_victory' else '失败'
        opposite='失败' if name=='胜利' else '胜利'
        if any(r.get('text','').replace(' ','')==opposite and r.get('score',0)>=.90
               for r in page.get('ocr_items',[])):
            return dict(ready=False,reason='conflicting_current_result_labels')
        names=('victory_btn',) if state=='result_victory' else ('defeat_banner','defeat_btn')
        candidates=[page.get('evidence',{}).get(n,{}) for n in names]
        banner=max(candidates,key=lambda r:r.get('score',-1))
        if banner.get('score',0)>=.93:return dict(ready=True,basis='current_strong_result_template')
        if self.shape!=frame.shape:self.labels.clear();self.shape=frame.shape
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY);rows={}
        # Cached text only proposes current local pixel checks. A supplied
        # current OCR result always takes precedence over those proposals.
        if 'ocr_items' not in page and state in self.labels:
            for text,(x,y,w,h,needle) in self.labels[state].items():
                left,top=max(0,x-12),max(0,y-12);roi=gray[top:min(gray.shape[0],y+h+12),left:min(gray.shape[1],x+w+12)]
                _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,needle,cv2.TM_CCOEFF_NORMED))
                if score<.97:break
                a,b=left+point[0],top+point[1]
                rows[text]=dict(box=[[a,b],[a+w,b],[a+w,b+h],[a,b+h]],score=float(score))
            if len(rows)==2 and self.geometry(frame.shape,rows):
                return dict(ready=True,basis='two_current_local_result_labels',labels=rows)
        # Every weak template candidate reaches current OCR, including a
        # candidate too weak to supply reliable banner geometry.
        if 'ocr_items' not in page:page['ocr_items']=self.current_text(frame,page,ocr)
        if any(r.get('text','').replace(' ','')==opposite and r.get('score',0)>=.90
               for r in page['ocr_items']):
            return dict(ready=False,reason='conflicting_current_result_labels')
        words={}
        for item in page['ocr_items']:
            box,text,score=item['box'],item['text'].replace(' ',''),item['score']
            if text in (name,'继续') and score>=.90:
                words.setdefault(text,[]).append(dict(item,box=np.asarray(box).tolist(),score=float(score)))
        continuation=self.merged_continue(frame,page,name,words)
        if continuation is not None:words['继续']=[continuation]
        if any(len(words.get(text,[]))!=1 for text in (name,'继续')):
            return dict(ready=False,reason='result_title_or_continue_unconfirmed')
        rows={'result':words[name][0],'继续':words['继续'][0]}
        if not self.geometry(frame.shape,rows):return dict(ready=False,reason='result_label_geometry_unconfirmed')
        cache={}
        for text,row in rows.items():
            pts=np.asarray(row['box']);x,y=np.floor(pts.min(axis=0)).astype(int);a,b=np.ceil(pts.max(axis=0)).astype(int)
            if not (0<=x<a<=frame.shape[1] and 0<=y<b<=frame.shape[0]):return dict(ready=False,reason='result_label_outside_source')
            cache[text]=(x,y,a-x,b-y,gray[y:b,x:a].copy())
        self.labels[state]=cache
        return dict(ready=True,basis='current_result_title_and_continue_prefix' if continuation is not None
                    else 'current_result_title_and_continue',labels=rows)
