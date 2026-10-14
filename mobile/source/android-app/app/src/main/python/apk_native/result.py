"""Strict result proof: strong template or three current verified text labels."""
import cv2,numpy as np

class ResultRecognizer:
    def __init__(self,continue_template=None):
        self.shape=None;self.labels={};self.continue_template=continue_template

    def merged_continue(self,frame,page,name,words):
        if self.continue_template is None:return None
        if any(len(words.get(text,[]))!=1 for text in (name,'查看战场')):return None
        if words.get('继续'):return None
        h,w=frame.shape[:2]
        cues=[r for r in page.get('ocr_items',[]) if r.get('score',0)>=.93
              and r['text'].replace(' ','').startswith('继续') and r['text'].replace(' ','')!='继续']
        if len(cues)!=1:return None
        center=np.asarray(cues[0]['box']).mean(axis=0)
        if not (abs(center[0]-w/2)<.15*w and .86*h<center[1]<.98*h):return None
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        left,top=round(w*.40),round(h*.86);right,bottom=round(w*.60),round(h*.98)
        roi=np.uint8(gray[top:bottom,left:right]>=185)*255
        template=cv2.cvtColor(self.continue_template,cv2.COLOR_BGR2GRAY)
        hits=[]
        for ratio in (.9,.95,1.,1.05,1.1):
            factor=h/720*ratio;tw,th=round(template.shape[1]*factor),round(template.shape[0]*factor)
            if tw<8 or th<8 or tw>roi.shape[1] or th>roi.shape[0]:continue
            needle=np.uint8(cv2.resize(template,(tw,th),interpolation=cv2.INTER_AREA)>=185)*255
            if np.count_nonzero(needle)<20:continue
            scores=cv2.matchTemplate(roi,needle,cv2.TM_CCORR_NORMED)
            _,score,_,point=cv2.minMaxLoc(scores)
            if score<.93:continue
            x,y=point;other=scores.copy()
            other[max(0,y-th//2):y+th//2+1,max(0,x-tw//2):x+tw//2+1]=0
            if other.max()>=.90:return None
            hits.append((float(score),[left+x,top+y,tw,th]))
        if not hits:return None
        score,(x,y,tw,th)=max(hits,key=lambda r:r[0])
        return dict(box=[[x,y],[x+tw,y],[x+tw,y+th],[x,y+th]],score=score,
                    basis='current_continue_glyph_pixels_despite_merged_ocr')
    @staticmethod
    def geometry(shape,rows,banner):
        h,w=shape[:2];label=rows['result'];continuation=rows['继续'];view=rows['查看战场']
        def center(row):
            pts=np.asarray(row['box']);return pts.mean(axis=0)
        x,y=center(label);cx,cy=center(continuation);vx,vy=center(view)
        bx,by,bw,bh=banner['bounds']
        return (.35*w<x<.65*w and .35*h<y<.85*h and abs(cx-w/2)<.12*w and cy>y+.15*h
                and vx>.75*w and vy<.20*h and bx<=x<=bx+bw and by<=y<=by+bh)
    def inspect(self,frame,page,ocr):
        state=page.get('state');name='胜利' if state=='result_victory' else '失败'
        names=('victory_btn',) if state=='result_victory' else ('defeat_banner','defeat_btn')
        candidates=[page.get('evidence',{}).get(n,{}) for n in names]
        banner=max(candidates,key=lambda r:r.get('score',-1))
        if banner.get('score',0)>=.93:return dict(ready=True,basis='current_strong_result_template')
        if banner.get('score',0)<.86 or not banner.get('bounds'):
            # Country emblems and table skins vary. Three unique current OCR
            # labels with the established result layout provide an independent
            # proposal; no historical banner or negative cache is reused.
            words={}
            for item in page.get('ocr_items',[]):
                text=item['text'].replace(' ','')
                if text in (name,'继续','查看战场') and item['score']>=.98:
                    words.setdefault(text,[]).append(item)
            opposite='失败' if name=='胜利' else '胜利'
            if any(r['text'].replace(' ','')==opposite and r.get('score',0)>=.98 for r in page.get('ocr_items',[])):
                return dict(ready=False,reason='conflicting_current_result_labels')
            continuation=self.merged_continue(frame,page,name,words)
            if continuation is not None:
                words['继续']=[continuation]
            if any(len(words.get(text,[]))!=1 for text in (name,'继续','查看战场')):
                return dict(ready=False,reason='result_template_or_three_labels_unconfirmed')
            rows={'result':words[name][0],'继续':words['继续'][0],'查看战场':words['查看战场'][0]}
            pts=np.asarray(rows['result']['box']);left,top=pts.min(axis=0);right,bottom=pts.max(axis=0)
            proposal={'bounds':[left,top,right-left,bottom-top]}
            if not self.geometry(frame.shape,rows,proposal):
                return dict(ready=False,reason='result_label_geometry_unconfirmed')
            return dict(ready=True,basis='current_result_labels_and_continue_pixels' if continuation is not None
                        else 'current_ocr_three_result_labels',labels=rows)
        if self.shape!=frame.shape:self.labels.clear();self.shape=frame.shape
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY);rows={}
        if state in self.labels:
            for text,(x,y,w,h,needle) in self.labels[state].items():
                left,top=max(0,x-12),max(0,y-12);roi=gray[top:min(gray.shape[0],y+h+12),left:min(gray.shape[1],x+w+12)]
                _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,needle,cv2.TM_CCOEFF_NORMED))
                if score<.97:break
                a,b=left+point[0],top+point[1]
                rows[text]=dict(box=[[a,b],[a+w,b],[a+w,b+h],[a,b+h]],score=float(score))
            if len(rows)==3 and self.geometry(frame.shape,rows,banner):
                return dict(ready=True,basis='three_current_local_result_labels',labels=rows)
        found,_=ocr(frame);words={}
        for box,text,score in found or []:
            text=text.replace(' ','')
            if text in (name,'继续','查看战场') and score>=.98:
                words.setdefault(text,[]).append(dict(box=np.asarray(box).tolist(),score=float(score)))
        if any(len(words.get(text,[]))!=1 for text in (name,'继续','查看战场')):
            return dict(ready=False,reason='three_result_labels_unconfirmed')
        rows={'result':words[name][0],'继续':words['继续'][0],'查看战场':words['查看战场'][0]}
        if not self.geometry(frame.shape,rows,banner):return dict(ready=False,reason='result_label_geometry_unconfirmed')
        cache={}
        for text,row in rows.items():
            pts=np.asarray(row['box']);x,y=np.floor(pts.min(axis=0)).astype(int);a,b=np.ceil(pts.max(axis=0)).astype(int)
            if not (0<=x<a<=frame.shape[1] and 0<=y<b<=frame.shape[0]):return dict(ready=False,reason='result_label_outside_source')
            cache[text]=(x,y,a-x,b-y,gray[y:b,x:a].copy())
        self.labels[state]=cache
        return dict(ready=True,basis='current_ocr_three_result_labels_and_banner',labels=rows)
