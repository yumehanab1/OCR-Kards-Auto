"""Original-pixel menu evidence and bounded task-overlay dismissal targets.

Recognition uses a height-normalized view and restores measured source boxes.
MenuFlow selects the next currently visible control and owns dispatch receipts.
"""
import json
import re
import time
from pathlib import Path
import cv2
import numpy as np
from .page_detector import Detector
from .ocr_bridge import NativeOCR
from .generic_popup import inspect as generic_popup
from .login_popup import inspect as login_popup
from .layout_profiles import for_shape as layout_for_shape


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
    profile=layout_for_shape(frame.shape)
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    pale=np.uint8((hsv[:,:,2]>=brightness)&(hsv[:,:,1]<=105))
    contours,_=cv2.findContours(pale*255,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    boxes=[]
    band=max(3,round(h*10/720)); required=max(2,round(h*2/720))
    for contour in contours:
        x,y,cw,ch=cv2.boundingRect(contour)
        if not (x>menu_right and profile.first_deck_top[0]*h<y<profile.first_deck_top[1]*h
                and profile.first_deck_width[0]*h<cw<profile.first_deck_width[1]*h
                and profile.first_deck_height[0]*h<ch<profile.first_deck_height[1]*h
                and profile.deck_card_aspect[0]<cw/ch<profile.deck_card_aspect[1]):continue
        edges=(pale[y:y+band,x:x+cw].sum(axis=0),pale[y+ch-band:y+ch,x:x+cw].sum(axis=0),
               pale[y:y+ch,x:x+band].sum(axis=1),pale[y:y+ch,x+cw-band:x+cw].sum(axis=1))
        coverage=[float((edge>=required).mean()) for edge in edges]
        # Rounded corners and a partial highlight do not erase a visible card.
        # Thickness still distinguishes a real deck from an empty thin slot.
        if sum(value>=.65 for value in coverage)>=3 and np.mean(coverage)>=.70:
            boxes.append([x,y,cw,ch])
    if not boxes:return None
    top=min(box[1] for box in boxes)
    row=[box for box in boxes if abs(box[1]-top)<h*.015]
    return min(row,key=lambda box:box[0])


def menu_from_text(frame, items):
    """Locate the controls needed for this step from their current OCR boxes.

    Navigation does not depend on unrelated footer labels or on every menu
    caption being readable. Left navigation and right queue controls remain
    distinct even though both are named 开始.
    """
    h,w=frame.shape[:2]
    words={}
    for row in items:
        if row.get('score',0)<.90:continue
        points=np.asarray(row.get('box',[]),dtype=float)
        if points.ndim!=2 or points.shape[0]<3 or points.shape[1]!=2:continue
        if not np.isfinite(points).all():continue
        a,b=np.floor(points.min(axis=0)).astype(int)
        c,d=np.ceil(points.max(axis=0)).astype(int)
        if not (0<=a<c<=w and 0<=b<d<=h):continue
        text=row.get('text','').replace(' ','')
        words.setdefault(text,[]).append(dict(row,bounds=[int(a),int(b),int(c-a),int(d-b)]))
    def center(row):
        x,y,bw,bh=row['bounds'];return x+bw/2,y+bh/2
    def unique(text,predicate=lambda row:True):
        found=[row for row in words.get(text,[]) if predicate(row)]
        return found[0] if len(found)==1 else None
    casual=unique('休闲',lambda row:center(row)[0]>.60*w)
    ranked=unique('排位',lambda row:center(row)[0]>.60*w)
    battle=unique('对战模式',lambda row:center(row)[0]<.35*w)
    training=unique('训练模式',lambda row:center(row)[0]<.35*w)
    if casual and ranked:
        centers=[center(row) for row in (casual,ranked)]
        if abs(centers[0][1]-centers[1][1])<max(.06*h,2*max(casual['bounds'][3],ranked['bounds'][3])):
            selector_x=sum(point[0] for point in centers)/2
            selector_bottom=max(row['bounds'][1]+row['bounds'][3] for row in (casual,ranked))
            start=unique('开始',lambda row: center(row)[0]>.60*w
                         and abs(center(row)[0]-selector_x)<.18*w
                         and selector_bottom<center(row)[1]<selector_bottom+.30*h)
            if start:
                hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV);colors=[]
                for row in (casual,ranked):
                    x,y,bw,bh=row['bounds'];roi=hsv[y:y+bh,x:x+bw]
                    colors.append(int(((roi[:,:,0]>=5)&(roi[:,:,0]<=35)&(roi[:,:,1]>=100)&(roi[:,:,2]>=90)).sum()))
                if max(colors)>=max(4,h*.012) and max(colors)>min(colors)*1.8+3:
                    selected='casual' if colors[0]>colors[1] else 'ranked'
                    targets={'menu_select_casual':casual['bounds'],'menu_select_ranked':ranked['bounds'],
                             'menu_start_queue':start['bounds']}
                    # Closing a previously open deck still needs an actual card,
                    # while queue controls need only their own current labels.
                    anchors=[row for row in (battle,training) if row]
                    right=max((row['bounds'][0]+row['bounds'][2] for row in anchors),default=.15*w)
                    card=first_deck_target(frame,right,80)
                    if card:
                        x,y,bw,bh=card;size=max(8,round(h*24/720));cx=x+bw/2;cy=round(y+bh+h*.17)
                        if cy+size/2<h and cx+size/2<min(casual['bounds'][0],ranked['bounds'][0]) and not any(
                                min(cx+size/2,row['bounds'][0]+row['bounds'][2])>max(cx-size/2,row['bounds'][0])
                                and min(cy+size/2,row['bounds'][1]+row['bounds'][3])>max(cy-size/2,row['bounds'][1])
                                for rows in words.values() for row in rows):
                            targets['menu_close_deck']=[cx-size/2,cy-size/2,size,size]
                    return dict(state='deck_ready',targets=targets,selected_mode=selected)
    if battle and not (casual and ranked):
        right=battle['bounds'][0]+battle['bounds'][2]
        card=first_deck_target(frame,right)
        if card:return dict(state='deck_list',targets={'menu_select_deck':card},selected_mode='')
        if training:
            hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV);colors=[]
            for row in (battle,training):
                x,y,bw,bh=row['bounds'];roi=hsv[y:y+bh,x:x+bw]
                colors.append(int(((roi[:,:,0]>=5)&(roi[:,:,0]<=35)&(roi[:,:,1]>=100)&(roi[:,:,2]>=90)).sum()))
            if colors[1]>=max(4,h*.012) and colors[1]>colors[0]*1.8+3:
                return dict(state='mode_menu',targets={'menu_battle_mode':battle['bounds']},selected_mode='')
    # The navigation rail also exists on deck pages. A current mode/selector
    # caption takes precedence over the left-side start tab.
    if battle or training or casual or ranked:return None
    start=unique('开始',lambda row:center(row)[0]<.20*w)
    if start:
        sx,sy=center(start)
        neighbors=[row for name in ('卡牌','商店') for row in words.get(name,[])
                   if abs(center(row)[0]-sx)<.08*w and .01*h<center(row)[1]-sy<.55*h]
        if neighbors:return dict(state='home',targets={'menu_home_start':start['bounds']},selected_mode='')
    return None


def semantic_login_reward(frame,items):
    """Current title plus an explicit press-anywhere prompt; no reward claim."""
    h,w=frame.shape[:2];titles=[];prompts=[]
    for item in items:
        score=item.get('score')
        if type(score) not in (int,float) or not np.isfinite(score) or not .90<=score<=1:continue
        text=re.sub(r'\s+','',str(item.get('text',''))).rstrip('。.!！')
        if text not in ('每日登录奖励','轻触任意位置进入主屏幕'):continue
        try:points=np.asarray(item.get('box',[]),dtype=float)
        except (TypeError,ValueError):continue
        if points.shape!=(4,2) or not np.isfinite(points).all():continue
        a,b=np.floor(points.min(axis=0)).astype(int);c,d=np.ceil(points.max(axis=0)).astype(int)
        if not (0<=a<c<=w and 0<=b<d<=h):continue
        row=dict(score=float(score),bounds=[int(a),int(b),int(c-a),int(d-b)])
        (titles if text=='每日登录奖励' else prompts).append(row)
    if len(titles)!=1 or len(prompts)!=1:return None
    title,prompt=titles[0],prompts[0]
    x,y,bw,bh=title['bounds'];px,py,pw,ph=prompt['bounds']
    if not (.20*w<x+bw/2<.80*w and .05*h<y<.43*h and .012*h<bh<.14*h
            and .20*w<px+pw/2<.80*w and .60*h<py<.94*h and .012*h<ph<.14*h
            and y+bh+.20*h<py and abs(x+bw/2-px-pw/2)<.25*w):return None
    return dict(basis='current_daily_login_title_and_continue_prompt',title=title,prompt=prompt,
                target_bounds=list(prompt['bounds']))


def login_reward_regions(frame):
    """Cheap current text-line proposals; words from both ROIs still decide."""
    h,w=frame.shape[:2];gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    kernel=np.ones((max(1,round(h*3/720)),max(3,round(h*11/720))),np.uint8)
    candidates=[]
    for top,bottom in ((.05,.43),(.60,.94)):
        oy=round(top*h);limit=round(bottom*h)
        bright=cv2.inRange(gray[oy:limit],155,255)
        joined=cv2.morphologyEx(bright,cv2.MORPH_CLOSE,kernel)
        contours,_=cv2.findContours(joined,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        found=[]
        for contour in contours:
            x,y,bw,bh=cv2.boundingRect(contour);y+=oy
            if .14*h<bw<1.2*h and .012*h<bh<.14*h and .24*w<x+bw/2<.76*w:
                found.append([x,y,bw,bh])
        if not found:return None
        candidates.append(found)
    footer=max(candidates[1],key=lambda box:box[1]);center=footer[0]+footer[2]/2
    upper=[box for box in candidates[0] if abs(box[0]+box[2]/2-center)<.25*w]
    if not upper:return None
    left=min(box[0] for box in upper);top=min(box[1] for box in upper)
    right=max(box[0]+box[2] for box in upper);bottom=max(box[1]+box[3] for box in upper)
    # An unrelated brighter line may sit above the title. Keep every plausible
    # upper line aligned with this frame's footer, rather than choose by y.
    lines=[[left,top,right-left,bottom-top],footer]
    regions=[]
    for x,y,bw,bh in lines:
        pad_x=max(8,round(h*.08));pad_y=max(5,round(h*.025))
        a,b=max(0,x-pad_x),max(0,y-pad_y);c,d=min(w,x+bw+pad_x),min(h,y+bh+pad_y)
        regions.append([a,b,c-a,d-b])
    return regions


def semantic_offer_target(frame,items):
    """A current pass offer's title, caption and price authorize a blank tap."""
    h,w=frame.shape[:2];rows=[]
    for row in items:
        if row.get('score',0)<.90:continue
        points=np.asarray(row.get('box',[]),dtype=float)
        if points.ndim!=2 or points.shape[0]<3 or points.shape[1]!=2 or not np.isfinite(points).all():continue
        a,b=points.min(axis=0);c,d=points.max(axis=0)
        if not (0<=a<c<=w and 0<=b<d<=h):continue
        rows.append(dict(row,text=row.get('text','').replace(' ',''),bounds=[float(a),float(b),float(c-a),float(d-b)]))
    titles=[row for row in rows if row['text'].endswith('月战场通票')]
    subtitles=[row for row in rows if '现已上架商店' in row['text']]
    prices=[row for row in rows if re.search(r'\d+[.,]\d{2}(?!\d)',row['text'])]
    if len(titles)!=1 or len(subtitles)!=1 or len(prices)!=1:return None
    title,subtitle,price=titles[0],subtitles[0],prices[0]
    tx,ty,tw,th=title['bounds'];sx,sy,sw,sh=subtitle['bounds'];px,py,pw,ph=price['bounds']
    if not (.20*w<tx+tw/2<.80*w and .12*h<ty<.50*h
            and ty+th*.75<=sy<ty+th+.18*h
            and sy+sh+.04*h<py<.85*h
            and max(abs(tx-sx),abs(tx-px))<.15*w
            and .20*w<px+pw/2<.80*w):return None
    size=max(8,round(h*24/720));cx=w/2;cy=round(h*665/720)
    x,y=cx-size/2,cy-size/2
    if py+ph+h*.03>=y:return None
    if any(min(x+size,row['bounds'][0]+row['bounds'][2])>max(x,row['bounds'][0])
           and min(y+size,row['bounds'][1]+row['bounds'][3])>max(y,row['bounds'][1]) for row in rows):return None
    return [x,y,size,size]


def semantic_daily_popup(frame,items):
    """Current daily-task title and refuse controls locate the blank dismissal."""
    h,w=frame.shape[:2];rows=[]
    for row in items:
        if row.get('score',0)<.90:continue
        points=np.asarray(row.get('box',[]),dtype=float)
        if points.ndim!=2 or points.shape[0]<3 or points.shape[1]!=2 or not np.isfinite(points).all():continue
        a,b=points.min(axis=0);c,d=points.max(axis=0)
        if not (0<=a<c<=w and 0<=b<d<=h):continue
        rows.append(dict(row,text=row.get('text','').replace(' ',''),bounds=[float(a),float(b),float(c-a),float(d-b)]))
    titles=[row for row in rows if row['text']=='每日任务']
    buttons=[row for row in rows if row['text']=='拒绝']
    if len(titles)!=1 or not 1<=len(buttons)<=3:return None
    title=titles[0];tx,ty,tw,th=title['bounds']
    if not (.25*w<tx+tw/2<.75*w and .08*h<ty+th/2<.45*h):return None
    if any(not (.10*w<x+bw/2<.90*w and ty+th+h*.03<y<.82*h)
           for x,y,bw,bh in (row['bounds'] for row in buttons)):return None
    centers=[row['bounds'][1]+row['bounds'][3]/2 for row in buttons]
    if max(centers)-min(centers)>max(h*.06,max(row['bounds'][3] for row in buttons)*1.5):return None
    buttons.sort(key=lambda row:row['bounds'][0])
    if any(left['bounds'][0]+left['bounds'][2]>=right['bounds'][0]
           for left,right in zip(buttons,buttons[1:])):return None
    size=max(8,round(h*24/720));cx=w/2;cy=round(h*665/720);x,y=cx-size/2,cy-size/2
    if max(row['bounds'][1]+row['bounds'][3] for row in buttons)+h*.03>=y:return None
    if any(min(x+size,row['bounds'][0]+row['bounds'][2])>max(x,row['bounds'][0])
           and min(y+size,row['bounds'][1]+row['bounds'][3])>max(y,row['bounds'][1]) for row in rows):return None
    return dict(basis='current_daily_title_and_buttons',title_score=float(title['score']),title_bounds=title['bounds'],
                buttons=[dict(score=float(row['score']),bounds=row['bounds']) for row in buttons],
                target_bounds=[x,y,size,size])


def pass_popup_target(frame,items):
    words={r['text'].replace(' ',''):r for r in items if r['score']>=.93}
    titles=[r for text,r in words.items() if text.endswith('月战场通票')]
    subtitles=[r for text,r in words.items() if '现已上架商店' in text]
    if not titles:
        titles=[r for text,r in words.items() if text=='周末优惠']
        subtitles=[r for text,r in words.items() if text=='商店有售']
    if len(titles)!=1 or len(subtitles)!=1:return None
    h,w=frame.shape[:2];gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    profile=layout_for_shape(frame.shape)
    edges=cv2.Canny(gray,40,100)
    connected=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_=cv2.findContours(connected,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    panels=[]
    for contour in contours:
        x,y,cw,ch=cv2.boundingRect(contour)
        if not (profile.promotion_width[0]*w<cw<profile.promotion_width[1]*w
                and profile.promotion_height[0]*h<ch<profile.promotion_height[1]*h
                and .2*w<x<.4*w and .15*h<y<.4*h):continue
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
    def __init__(self, assets, bridge, startup=False,settlement=False):
        self.startup = startup
        self.settlement=settlement
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
        if factors==(1.,1.):
            result=self.observe_pixels(frame,packet)
            result['layout_profile']=layout_for_shape(frame.shape).name
            return result
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
        login=None if self.startup or self.settlement else login_popup(frame,{n:cv2.cvtColor(v,cv2.COLOR_BGR2GRAY) for n,v in self.promotions.items() if n.startswith('native_daily_')},self.specs)
        if login:
            return dict(state='login_popup_cleanup',targets={'menu_clear_login_popup':login['target_bounds']},
                        login_popup_evidence=login,coordinate_space='source_pixels',selected_mode='',
                        action_ready=True,timings_ms={'total':(time.perf_counter()-started)*1000},ocr_metrics={},
                        start_control={'ok':False,'visible':False,'bounds':None,'score':0.})
        popup=None if self.startup or self.settlement else generic_popup(frame,{name:image for name,image in self.promotions.items() if name.endswith('_close')})
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
        login_probe_ms=0.;login_probe_metrics={};login_probe_regions=None
        def reward_result(proof,items,template_ms):
            return dict(state='login_reward',targets={'menu_dismiss_reward':proof['target_bounds']},
                login_reward_evidence=proof,coordinate_space='source_pixels',selected_mode='',action_ready=True,
                timings_ms=dict(template_path=template_ms,login_reward_probe=login_probe_ms,
                                total=(time.perf_counter()-started)*1000),
                ocr_metrics=self.ocr.last_metrics,login_reward_probe_metrics=login_probe_metrics,
                login_reward_probe=dict(regions=login_probe_regions),ocr_items=items,
                start_control={'ok':False,'visible':False,'bounds':None,'score':0.})
        # Fast path for the stable home screen. Checking the two independent
        # fixed controls first avoids scanning unrelated popup templates and
        # avoids OCR on every unchanged menu frame.
        if has('home_play') and has('home_tasks'):
            state,targets='home',{'menu_home_start':match('home_play')['bounds']}
        if (state=='unknown' and not self.settlement and hasattr(self.ocr,'regions')
                and getattr(self.ocr,'bridge',True) is not None):
            probe_started=time.perf_counter();login_probe_regions=login_reward_regions(frame)
            if login_probe_regions:
                self.ocr.bind(packet.get('ocr_source_packet',packet))
                found,_=self.ocr.regions(frame,login_probe_regions,scope='menu_controls')
                login_probe_metrics=dict(self.ocr.last_metrics)
                current=[dict(box=np.asarray(box).tolist(),text=text,score=float(score)) for box,text,score in found or []]
                proof=semantic_login_reward(frame,current)
                login_probe_ms=(time.perf_counter()-probe_started)*1000
                if proof:return reward_result(proof,current,(probe_started-started)*1000)
            login_probe_ms=(time.perf_counter()-probe_started)*1000
        # Either highlighted selector can anchor the other label. An inactive
        # grey casual label may be absent from the white/orange proposal mask.
        selector_pair=False
        if state=='unknown':
            selector_pair=(has('native_casual_label') and near('native_ranked_label',
                           match('native_casual_label')['bounds'],(-3.5,-.5,-.5,1.5)))
            if not selector_pair:
                selector_pair=(has('native_ranked_label') and near('native_casual_label',
                               match('native_ranked_label')['bounds'],(.5,-.5,3.5,1.5)))
        if state=='unknown' and selector_pair and near('native_queue_start',match('native_casual_label')['bounds'],(-3,1,2,4)):
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
        elif layout_for_shape(frame.shape).name == 'standard_16_9' and (
                (has('battle_unselected') and has('training_selected')) or
                (has('battle_selected') and has('training_unselected'))):
            # Legacy 16:9 text templates correlate in both gray and orange.
            # Selection comes from current color, and a list requires full cards.
            battle=max((match('battle_unselected'),match('battle_selected')),key=lambda v:v['score'])
            training=max((match('training_unselected'),match('training_selected')),key=lambda v:v['score'])
            b,t=battle['bounds'],training['bounds'];h,w=frame.shape[:2]
            if (abs(b[0]-t[0])<h*.03 and b[1]+b[3]<t[1] and max(b[0]+b[2],t[0]+t[2])<w*.25):
                counts=[]
                for x,y,cw,ch in (b,t):
                    roi=hsv[y:y+ch,x:x+cw]
                    counts.append(int(((roi[:,:,0]>=5)&(roi[:,:,0]<=35)&(roi[:,:,1]>=120)&(roi[:,:,2]>=100)).sum()))
                selected_tab=None
                if max(counts)>=max(8,h*.04) and min(counts)<=max(8,max(counts)*.08):
                    selected_tab='battle' if counts[0]>counts[1] else 'training'
                evidence['standard_mode_color']={'battle':{'bounds':b,'orange_pixels':counts[0]},
                    'training':{'bounds':t,'orange_pixels':counts[1]},'selected_tab':selected_tab}
                if selected_tab=='training':
                    state,targets='mode_menu',{'menu_battle_mode':b}
                elif selected_tab=='battle':
                    card=first_deck_target(frame,max(b[0]+b[2],t[0]+t[2]))
                    if card:state,targets='deck_list',{'menu_select_deck':card}
                    else:state='menu_transition'
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
            # Offline template-only callers deliberately provide no bridge.
            # Missing OCR remains unavailable evidence, never a prior result.
            if getattr(self.ocr,'bridge',True) is None:
                found=[]
            elif self.settlement and hasattr(self.ocr,'regions'):
                # Read current navigation and queue controls, excluding the
                # expensive central reward/card artwork during result cleanup.
                h,w=frame.shape[:2]
                regions=[[0,0,round(w*.36),h],[round(w*.60),0,w-round(w*.60),h]]
                found,_=self.ocr.regions(frame,regions,scope='menu_controls')
            else:
                found,_=self.ocr(frame)
            items = [{'box':np.asarray(b).tolist(),'text':s,'score':float(c)} for b,s,c in found or []]
            reward=semantic_login_reward(frame,items)
            if reward:return reward_result(reward,items,(templates_done-started)*1000-login_probe_ms)
            daily=semantic_daily_popup(frame,items)
            if daily:
                return dict(state='login_popup_cleanup',targets={'menu_clear_login_popup':daily['target_bounds']},
                            login_popup_evidence=daily,coordinate_space='source_pixels',selected_mode='',
                            action_ready=True,timings_ms={'total':(time.perf_counter()-started)*1000,
                                'login_reward_probe':login_probe_ms},
                            ocr_metrics=self.ocr.last_metrics,login_reward_probe_metrics=login_probe_metrics,ocr_items=items,
                            start_control={'ok':False,'visible':False,'bounds':None,'score':0.})
            target = popup_target(frame.shape,items)
            basis='task_title_and_subtitle'
            if target is None:
                target=semantic_offer_target(frame,items)
                basis='current_offer_title_subtitle_price'
            if target is None:
                target=pass_popup_target(frame,items)
                basis=('weekend_title_subtitle_and_panel' if any(
                    r['text'].replace(' ','')=='周末优惠' and r['score']>=.93 for r in items)
                    else 'pass_title_subtitle_and_panel')
            if target:
                state={'pass_title_subtitle_and_panel':'pass_popup',
                       'current_offer_title_subtitle_price':'pass_popup',
                       'weekend_title_subtitle_and_panel':'weekend_popup'}.get(basis,'blocking_popup')
                action={'pass_popup':'menu_dismiss_pass','weekend_popup':'menu_dismiss_weekend'}.get(state,'menu_dismiss_blocking_popup')
                targets={action:target}
            else:
                offer=self.promotion(frame,items)
                if offer:
                    popup,promotion_evidence=offer
                    state,targets=popup+'_popup',{'menu_dismiss_'+popup:promotion_evidence['close']['bounds']}
                if not offer:
                    semantic=menu_from_text(frame,items)
                    if semantic:
                        state,targets,selected=semantic['state'],semantic['targets'],semantic['selected_mode']
        start=targets.get('menu_home_start')
        if start is None and state in ('deck_list','deck_ready','card_collection','mode_menu'):
            rail=[r for r in items if r.get('score',0)>=.90 and r.get('text','').replace(' ','')=='开始'
                  and np.asarray(r['box'])[:,0].mean()<frame.shape[1]*.20]
            if len(rail)==1:
                a,b=np.floor(np.asarray(rail[0]['box']).min(axis=0)).astype(int)
                c,d=np.ceil(np.asarray(rail[0]['box']).max(axis=0)).astype(int)
                start=[int(a),int(b),int(c-a),int(d-b)]
        if start is None and state in ('home','deck_list','deck_ready','card_collection','mode_menu'):
            plain=match('home_play');highlight=match('home_play_selected')
            if max(plain['score'],highlight['score'])>=.93:
                start=(plain if plain['score']>=highlight['score'] else highlight)['bounds']
        return {'state':state,'targets':targets,'selected_mode':selected,'evidence':evidence,
                'timings_ms':{'template_path':(templates_done-started)*1000-login_probe_ms,
                              'login_reward_probe':login_probe_ms,
                              'total':(time.perf_counter()-started)*1000},
                'ocr_metrics':self.ocr.last_metrics,
                'login_reward_probe_metrics':login_probe_metrics,
                'start_control':{'ok':start is not None,'visible':start is not None,'bounds':start,
                                 'score':1. if start is not None else 0.,'variant':'native_current_frame'},
                'action_ready':bool(targets),'coordinate_space':'source_pixels','ocr_items':items,
                'popup_basis':basis if state in ('blocking_popup','pass_popup','weekend_popup') else '',
                'promotion_evidence':promotion_evidence,
                'reason':'native_deck_structure_pending' if state=='menu_transition' else ''}
