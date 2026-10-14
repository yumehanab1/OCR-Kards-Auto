"""Original-pixel menu evidence and bounded task-overlay dismissal targets.

No image resampling or input dispatch occurs here. Unverified deck geometry
stays a transition; the existing MenuFlow owns receipts and postconditions.
"""
import json
import time
from pathlib import Path
import cv2
import numpy as np
from .page_detector import Detector
from .ocr_bridge import NativeOCR
from .generic_popup import inspect as generic_popup
from .login_popup import inspect as login_popup


def popup_target(shape, items):
    h, w = shape[:2]
    words = {r['text'].replace(' ', '') for r in items if r['score'] >= .93}
    if '入伍任务' not in words or not any('完成所有入伍任务' in text for text in words):
        return None
    size = max(8, round(h * 24 / 720))
    cx, cy = w / 2, round(h * 665 / 720)
    # Reviewed lower blank point, never the reward card or its activation area.
    x, y = cx-size/2, cy-size/2
    for row in items:
        if row['score'] < .93:
            continue
        box = np.asarray(row['box'])
        a, b = box.min(axis=0); c, d = box.max(axis=0)
        if min(x+size,c)>max(x,a) and min(y+size,d)>max(y,b):
            return None
    return [x,y,size,size]


def first_deck_target(frame, menu_right, brightness=145):
    """Find full thick pale card borders; choose the first complete top row slot."""
    h,w = frame.shape[:2]
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    pale=np.uint8((hsv[:,:,2]>=brightness)&(hsv[:,:,1]<=105))
    contours,_=cv2.findContours(pale*255,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    boxes=[]
    band=max(3,round(h*10/720)); required=max(2,round(h*3/720))
    for contour in contours:
        x,y,cw,ch=cv2.boundingRect(contour)
        if not (x>menu_right and .07*h<y<.30*h and .20*h<cw<.35*h
                and .28*h<ch<.48*h and .65<cw/ch<.78):continue
        edges=(pale[y:y+band,x:x+cw].sum(axis=0),pale[y+ch-band:y+ch,x:x+cw].sum(axis=0),
               pale[y:y+ch,x:x+band].sum(axis=1),pale[y:y+ch,x+cw-band:x+cw].sum(axis=1))
        if all(float((edge>=required).mean())>=.90 for edge in edges):boxes.append([x,y,cw,ch])
    if not boxes:return None
    top=min(box[1] for box in boxes)
    row=[box for box in boxes if abs(box[1]-top)<h*.015]
    return min(row,key=lambda box:box[0])


def pass_popup_target(frame,items):
    words={r['text'].replace(' ',''):r for r in items if r['score']>=.93}
    titles=[r for text,r in words.items() if text.endswith('月战场通票')]
    subtitles=[r for text,r in words.items() if '现已上架商店' in text]
    if not titles:
        titles=[r for text,r in words.items() if text=='周末优惠']
        subtitles=[r for text,r in words.items() if text=='商店有售']
    if len(titles)!=1 or len(subtitles)!=1:return None
    h,w=frame.shape[:2];gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(gray,40,100)
    connected=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_=cv2.findContours(connected,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    panels=[]
    for contour in contours:
        x,y,cw,ch=cv2.boundingRect(contour)
        if not (.35*w<cw<.55*w and .3*h<ch<.6*h and .2*w<x<.4*w and .15*h<y<.4*h):continue
        if any(not (x<np.asarray(r['box'])[:,0].min()<np.asarray(r['box'])[:,0].max()<x+cw
                    and y<np.asarray(r['box'])[:,1].min()<np.asarray(r['box'])[:,1].max()<y+ch)
               for r in titles+subtitles):continue
        # Each side must contain current-frame edge pixels over 90% of its span.
        pad=max(3,round(h*7/720))
        strips=(edges[max(0,y-pad):y+pad+1,x:x+cw],edges[y+ch-pad:y+ch+pad+1,x:x+cw],
                edges[y:y+ch,max(0,x-pad):x+pad+1],edges[y:y+ch,x+cw-pad:x+cw+pad+1])
        if not all(float((strip>0).any(axis=0 if i<2 else 1).mean())>=.90
                   for i,strip in enumerate(strips)):continue
        if not any(max(abs(x-a),abs(y-b),abs(cw-c),abs(ch-d))<=8 for a,b,c,d in panels):
            panels.append([x,y,cw,ch])
    if len(panels)!=1:return None
    size=max(8,round(h*24/720));cx=w/2;cy=round(h*665/720)
    if cy-size/2<=panels[0][1]+panels[0][3]+h*.03:return None
    return [cx-size/2,cy-size/2,size,size]


class NativeMenuRecognizer:
    def __init__(self, assets, bridge, startup=False):
        self.startup = startup
        assets = Path(assets)
        specs = json.loads((assets/'manifest.json').read_text(encoding='utf8'))['templates']
        self.specs=specs
        self.promotions={name:cv2.imdecode(np.frombuffer((assets/spec['file']).read_bytes(),np.uint8),1)
                         for name,spec in specs.items() if name.startswith(('starter_','airdrop_','weekend_','pass_','box_','store_','native_daily_'))}
        names = ('home_play','home_play_selected','home_tasks','battle_selected',
                 'training_unselected','battle_unselected','training_selected',
                 'detail_start','queue_cancel','defeat_banner','card_tab',
                 'native_battle_label','native_training_label',
                 'native_casual_label','native_ranked_label','native_queue_start')
        bank = {name:cv2.imdecode(np.frombuffer((assets/specs[name]['file']).read_bytes(),np.uint8),1)
                for name in names}
        if any(value is None for value in bank.values()):
            raise ValueError('native_menu_template_missing')
        self.detector = Detector(bank,'filtered',refine=True)
        self.ocr = NativeOCR(bridge)
        self.shape = None
        self.relative_locations = {}
        self.relative_scaled = {}

    def promotion(self,frame,items):
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY);base=frame.shape[0]/720
        for popup,title in (('starter','新手特惠'),('airdrop','空投'),('weekend','周末优惠'),
                            ('pass','战场通票'),('box','军需箱'),('store','商店')):
            # Low-score OCR only proposes a search window. All six original
            # templates independently retain the .93 confirmation threshold.
            captions=[r for r in items if r['score']>=.80 and
                      (r['text'].replace(' ','')==title or popup=='pass' and r['text'].replace(' ','').endswith(title))]
            if len(captions)!=1:continue
            points=np.asarray(captions[0]['box']);a,b=points.min(axis=0);c,d=points.max(axis=0)
            name=popup+'_title';template=self.promotions[name];best=None
            for factor in np.arange(.8,1.401,.02):
                scale=base*float(factor);th,tw=template.shape[:2];nw,nh=round(tw*scale),round(th*scale)
                left,top=max(0,int(a-nw*.3)),max(0,int(b-nh*.3))
                right,bottom=min(gray.shape[1],int(c+nw*.3)),min(gray.shape[0],int(d+nh*.3))
                if right-left<nw or bottom-top<nh:continue
                needle=cv2.cvtColor(cv2.resize(template,(nw,nh)),cv2.COLOR_BGR2GRAY)
                _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(gray[top:bottom,left:right],needle,cv2.TM_CCOEFF_NORMED))
                if best is None or score>best[0]:best=(score,scale,left+point[0],top+point[1])
            if best is None or best[0]<.93:continue
            _,scale,tx,ty=best;bx,by,_,_=self.specs[name]['bounds'];anchors={}
            for suffix in ('title','close','edge_top','edge_bottom','edge_left','edge_right'):
                key=popup+'_'+suffix
                if key not in self.promotions and suffix.startswith('edge_'):key='starter_'+suffix
                x,y,_,_=self.specs[key]['bounds'];template=self.promotions[key]
                th,tw=template.shape[:2];nw,nh=max(2,round(tw*scale)),max(2,round(th*scale))
                px,py=round(tx+(x-bx)*scale),round(ty+(y-by)*scale);pad=3
                left,top=max(0,px-pad),max(0,py-pad);right,bottom=min(gray.shape[1],px+nw+pad),min(gray.shape[0],py+nh+pad)
                if right-left<nw or bottom-top<nh:break
                needle=cv2.cvtColor(cv2.resize(template,(nw,nh)),cv2.COLOR_BGR2GRAY)
                _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(gray[top:bottom,left:right],needle,cv2.TM_CCOEFF_NORMED))
                anchors[suffix]={'score':float(score),'bounds':[left+point[0],top+point[1],nw,nh],
                                 'offset':[left+point[0]-px,top+point[1]-py]}
            if len(anchors)!=6 or any(r['score']<.93 for r in anchors.values()):continue
            if any(max(r['offset'][axis] for r in anchors.values())-min(r['offset'][axis] for r in anchors.values())>3
                   for axis in (0,1)):continue
            return popup,anchors
        return None

    def observe(self, frame, packet):
        from .recognition_scale import shrink,restore
        if frame is None:return {'state':'unknown','targets':{}}
        if list(frame.shape[:2])!=[packet.get('source_height'),packet.get('source_width')]:
            return {'state':'unknown','reason':'native_menu_geometry_mismatch','targets':{}}
        scaled,factors=shrink(frame)
        if factors==(1.,1.):return self.observe_pixels(frame,packet)
        reduced=dict(packet,source_height=scaled.shape[0],source_width=scaled.shape[1],ocr_source_packet=packet)
        result=self.observe_pixels(scaled,reduced)
        result=restore(result,frame,scaled,factors)
        result['targets']={k:[round(v[0]*factors[0]),round(v[1]*factors[1]),round(v[2]*factors[0]),round(v[3]*factors[1])] for k,v in result.get('targets',{}).items()}
        # Exact reviewed blank target follows source height, avoiding rounding drift.
        for action in ('menu_clear_login_popup','menu_dismiss_blocking_popup','menu_dismiss_pass'):
            if action in result.get('targets',{}):
                h,w=frame.shape[:2];size=max(8,round(h*24/720));cx=w/2;cy=round(h*665/720)
                result['targets'][action]=[cx-size/2,cy-size/2,size,size]
        return result

    def observe_pixels(self, frame, packet):
        started=time.perf_counter()
        if frame is None or packet.get('coordinate_space') != 'source_pixels' or frame.shape[:2] != (
                packet.get('source_height'),packet.get('source_width')):
            return {'state':'unknown','reason':'native_menu_geometry_mismatch','targets':{}}
        if self.shape != frame.shape:
            self.detector.locations.clear(); self.relative_locations.clear(); self.shape = frame.shape
        login=None if self.startup else login_popup(frame,{n:cv2.cvtColor(v,cv2.COLOR_BGR2GRAY) for n,v in self.promotions.items() if n.startswith('native_daily_')},self.specs)
        if login:
            return dict(state='login_popup_cleanup',targets={'menu_clear_login_popup':login['target_bounds']},
                        login_popup_evidence=login,coordinate_space='source_pixels',selected_mode='',
                        action_ready=True,timings_ms={'total':(time.perf_counter()-started)*1000},ocr_metrics={},
                        start_control={'ok':False,'visible':False,'bounds':None,'score':0.})
        popup=None if self.startup else generic_popup(frame,{name:image for name,image in self.promotions.items() if name.endswith('_close')})
        if popup:
            return {'state':'generic_popup','targets':{'menu_dismiss_generic':popup['close']['bounds']},
                    'popup_id':popup['popup_id'],'generic_popup_evidence':popup,
                    'selected_mode':'','coordinate_space':'source_pixels','action_ready':True,
                    'timings_ms':{'total':(time.perf_counter()-started)*1000},'ocr_metrics':{},
                    'start_control':{'ok':False,'visible':False,'bounds':None,'score':0.}}
        gray = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        mask = cv2.morphologyEx(cv2.inRange(gray,165,255),cv2.MORPH_CLOSE,np.ones((3,11),np.uint8))
        contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        self.detector.text_boxes = [cv2.boundingRect(c) for c in contours if cv2.boundingRect(c)[2]>=12]
        hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        orange=cv2.morphologyEx(cv2.inRange(hsv,(5,80,80),(35,255,255)),cv2.MORPH_CLOSE,np.ones((3,11),np.uint8))
        contours,_=cv2.findContours(orange,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        self.detector.text_boxes.extend(cv2.boundingRect(c) for c in contours if cv2.boundingRect(c)[2]>=12)
        evidence = {}
        def match(name):
            if name not in evidence:
                evidence[name] = self.detector.match(gray,name)
            return evidence[name]
        def has(name):
            return match(name)['score'] >= .90
        def near(name,anchor,relative):
            x,y,cw,ch=anchor;h,w=gray.shape
            a,b,c,d=relative
            left,top=max(0,round(x+a*cw)),max(0,round(y+b*ch))
            right,bottom=min(w,round(x+c*cw)),min(h,round(y+d*ch))
            roi=gray[top:bottom,left:right];template=self.detector.bank[name];best={'score':-1.,'bounds':None}
            def needle_for(factor):
                key=(name,h,factor)
                if key not in self.relative_scaled:
                    th,tw=template.shape[:2];scale=h/720*factor
                    self.relative_scaled[key]=cv2.cvtColor(cv2.resize(template,
                        (max(8,round(tw*scale)),max(8,round(th*scale)))),cv2.COLOR_BGR2GRAY)
                return self.relative_scaled[key]
            previous=self.relative_locations.get(name)
            if previous:
                px,py,pw,ph=previous['bounds'];pad=12
                a,b=max(left,px-pad),max(top,py-pad)
                c,d=min(right,px+pw+pad),min(bottom,py+ph+pad)
                needle=needle_for(previous['factor'])
                if d-b>=needle.shape[0] and c-a>=needle.shape[1]:
                    _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(gray[b:d,a:c],needle,cv2.TM_CCOEFF_NORMED))
                    if score>=.90:
                        best=dict(previous,score=float(score),bounds=[a+point[0],b+point[1],pw,ph],
                                  search='relative_tracked_current_frame')
                        self.relative_locations[name]=best;evidence[name]=best
                        return True
            # Cached scale/position is only a proposal. A failed current-frame
            # check falls back to the complete relative search, never its verdict.
            for factor in np.arange(.8,1.401,.02):
                factor=round(float(factor),4);needle=needle_for(factor)
                if roi.shape[0]<needle.shape[0] or roi.shape[1]<needle.shape[1]:continue
                _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,needle,cv2.TM_CCOEFF_NORMED))
                if score>best['score']:best={'score':float(score),'bounds':[left+point[0],top+point[1],needle.shape[1],needle.shape[0]],'factor':factor,'search':'relative_current_frame'}
            if best['score']>=.90:self.relative_locations[name]=best
            else:self.relative_locations.pop(name,None)
            evidence[name]=best
            return best['score']>=.90
        state, targets, selected = 'unknown', {}, ''
        # Fast path for the stable home screen. Checking the two independent
        # fixed controls first avoids scanning unrelated popup templates and
        # avoids OCR on every unchanged menu frame.
        if has('home_play') and has('home_tasks'):
            state,targets='home',{'menu_home_start':match('home_play')['bounds']}
        if state=='unknown' and has('native_casual_label') and near('native_ranked_label',match('native_casual_label')['bounds'],(-3.5,-.5,-.5,1.5)) and near('native_queue_start',match('native_casual_label')['bounds'],(-3,1,2,4)):
            casual=match('native_casual_label')['bounds'];ranked=match('native_ranked_label')['bounds']
            queue=match('native_queue_start')['bounds'];h,w=frame.shape[:2]
            if (min(casual[0],ranked[0],queue[0])>w*.8 and
                    abs(casual[1]-ranked[1])<h*.035 and
                    queue[1]>max(casual[1]+casual[3],ranked[1]+ranked[3])):
                counts=[]
                for x,y,cw,ch in (casual,ranked):
                    roi=hsv[y:y+ch,x:x+cw]
                    counts.append(int(((roi[:,:,0]>=5)&(roi[:,:,0]<=35)&(roi[:,:,1]>=120)&(roi[:,:,2]>=100)).sum()))
                if max(counts)>=max(8,h*.04) and min(counts)<=max(8,max(counts)*.08):
                    selected='casual' if counts[0]>counts[1] else 'ranked'
                    state='deck_ready'
                    targets={'menu_select_casual':casual,'menu_select_ranked':ranked,'menu_start_queue':queue}
                    # A session may start with an old deck detail already open.
                    # The template fast path must expose the same blank close
                    # target as the OCR path, before first-deck verification.
                    if has('native_battle_label') and has('native_training_label'):
                        b=match('native_battle_label')['bounds'];t=match('native_training_label')['bounds']
                        card=first_deck_target(frame,max(b[0]+b[2],t[0]+t[2]),80)
                        if card:
                            x,y,cw,ch=card;size=max(8,round(h*24/720))
                            cx=x+cw/2;cy=round(y+ch+h*.17)
                            if cy+size/2<h and cx+size/2<min(casual[0],ranked[0],queue[0]):
                                targets['menu_close_deck']=[cx-size/2,cy-size/2,size,size]
        if state=='unknown' and has('native_battle_label') and has('native_training_label'):
            b=match('native_battle_label')['bounds'];t=match('native_training_label')['bounds']
            if (abs(b[0]-t[0])<frame.shape[0]*.03 and b[1]+b[3]<t[1]
                    and b[0]+b[2]<frame.shape[1]*.25):
                card=first_deck_target(frame,max(b[0]+b[2],t[0]+t[2]))
                if card:
                    state,targets='deck_list',{'menu_select_deck':card}
        # OCR is only used where the template path has no confirmed menu state.
        if state in ('deck_list','deck_ready','home'):
            pass
        elif has('queue_cancel'):
            state = 'queueing'
        elif has('card_tab'):
            state = 'card_collection'
        elif has('home_play') and has('home_tasks'):
            state,targets = 'home',{'menu_home_start':match('home_play')['bounds']}
        elif has('battle_unselected') and has('training_selected'):
            state,targets = 'mode_menu',{'menu_battle_mode':match('battle_unselected')['bounds']}
        elif has('battle_selected') and has('training_unselected'):
            state = 'menu_transition'  # Deck/selector structure is not yet authorized.
        self.ocr.bind(packet.get("ocr_source_packet",packet))
        templates_done=time.perf_counter()
        self.ocr.last_metrics={}
        items = []
        promotion_evidence=None
        if state in ('unknown','menu_transition'):
            found,_ = self.ocr(frame)
            items = [{'box':np.asarray(b).tolist(),'text':s,'score':float(c)} for b,s,c in found or []]
            target = None if self.startup else popup_target(frame.shape,items)
            basis='task_title_and_subtitle'
            if target is None and not self.startup:
                target=pass_popup_target(frame,items)
                basis=('weekend_title_subtitle_and_panel' if any(
                    r['text'].replace(' ','')=='周末优惠' and r['score']>=.93 for r in items)
                    else 'pass_title_subtitle_and_panel')
            if target:
                state={'pass_title_subtitle_and_panel':'pass_popup',
                       'weekend_title_subtitle_and_panel':'weekend_popup'}.get(basis,'blocking_popup')
                action={'pass_popup':'menu_dismiss_pass','weekend_popup':'menu_dismiss_weekend'}.get(state,'menu_dismiss_blocking_popup')
                targets={action:target}
            else:
                offer=None if self.startup else self.promotion(frame,items)
                if offer:
                    popup,promotion_evidence=offer
                    state,targets=popup+'_popup',{'menu_dismiss_'+popup:promotion_evidence['close']['bounds']}
                words={r['text'].replace(' ',''):r for r in items if r['score']>=.93}
                if all(name in words for name in ('开始','卡牌','商店','任务','模式')) and '对战模式' not in words:
                    starts=[r for r in items if r['text'].replace(' ','')=='开始' and r['score']>=.98
                            and np.asarray(r['box']).mean(axis=0)[0]<frame.shape[1]*.10]
                    if len(starts)==1:
                        points=np.asarray(starts[0]['box']);a,b=np.floor(points.min(axis=0)).astype(int)
                        c,d=np.ceil(points.max(axis=0)).astype(int)
                        state,targets='home',{'menu_home_start':[int(a),int(b),int(c-a),int(d-b)]}
                if all(name in words for name in ('对战模式','训练模式','休闲','排位')):
                    h,w=frame.shape[:2]
                    selector=[words[name] for name in ('休闲','排位')]
                    centers=[np.asarray(r['box']).mean(axis=0) for r in selector]
                    starts=[r for r in items if r['text'].replace(' ','')=='开始' and r['score']>=.98
                            and np.asarray(r['box']).mean(axis=0)[0]>.8*w]
                    if len(starts)==1 and all(c[0]>.8*w for c in centers) and abs(centers[0][1]-centers[1][1])<h*.035:
                        hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
                        colors=[]
                        def bounds(row):
                            a,b=np.floor(np.asarray(row['box']).min(axis=0)).astype(int)
                            c,d=np.ceil(np.asarray(row['box']).max(axis=0)).astype(int)
                            return [int(a),int(b),int(c-a),int(d-b)]
                        for row in selector:
                            x,y,cw,ch=bounds(row);roi=hsv[y:y+ch,x:x+cw]
                            colors.append(int(((roi[:,:,0]>=5)&(roi[:,:,0]<=35)&(roi[:,:,1]>=120)&(roi[:,:,2]>=100)).sum()))
                        if max(colors)>=max(8,h*.04) and min(colors)<=max(8,max(colors)*.08):
                            selected='casual' if colors[0]>colors[1] else 'ranked'
                            state='deck_ready'
                            targets={'menu_select_casual':bounds(selector[0]),'menu_select_ranked':bounds(selector[1]),
                                     'menu_start_queue':bounds(starts[0])}
                            right=max(np.asarray(words[name]['box'])[:,0].max() for name in ('对战模式','训练模式'))
                            card=first_deck_target(frame,right,80)
                            if card:
                                x,y,cw,ch=card;size=max(8,round(h*24/720));cx=x+cw/2;cy=round(y+ch+h*.17)
                                blank=[cx-size/2,cy-size/2,size,size]
                                if cy+size/2<h and not any(
                                    min(cx+size/2,np.asarray(r['box'])[:,0].max())>max(cx-size/2,np.asarray(r['box'])[:,0].min())
                                    and min(cy+size/2,np.asarray(r['box'])[:,1].max())>max(cy-size/2,np.asarray(r['box'])[:,1].min())
                                    for r in items if r['score']>=.93):
                                    targets['menu_close_deck']=blank
                # Both independent menu labels are required before card borders
                # become a selection target; card art alone cannot authorize.
                if '对战模式' in words and '训练模式' in words and not ('休闲' in words and '排位' in words):
                    right=max(np.asarray(words[name]['box'])[:,0].max() for name in ('对战模式','训练模式'))
                    card=first_deck_target(frame,right)
                    if card:
                        state,targets='deck_list',{'menu_select_deck':card}
        start=targets.get('menu_home_start')
        if start is None and state in ('home','deck_list','deck_ready','card_collection','mode_menu'):
            plain=match('home_play');highlight=match('home_play_selected')
            if max(plain['score'],highlight['score'])>=.93:
                start=(plain if plain['score']>=highlight['score'] else highlight)['bounds']
        return {'state':state,'targets':targets,'selected_mode':selected,'evidence':evidence,
                'timings_ms':{'template_path':(templates_done-started)*1000,
                              'total':(time.perf_counter()-started)*1000},
                'ocr_metrics':self.ocr.last_metrics,
                'start_control':{'ok':start is not None,'visible':start is not None,'bounds':start,
                                 'score':1. if start is not None else 0.,'variant':'native_current_frame'},
                'action_ready':bool(targets),'coordinate_space':'source_pixels','ocr_items':items,
                'popup_basis':basis if state in ('blocking_popup','pass_popup','weekend_popup') else '',
                'promotion_evidence':promotion_evidence,
                'reason':'native_deck_structure_pending' if state=='menu_transition' else ''}
