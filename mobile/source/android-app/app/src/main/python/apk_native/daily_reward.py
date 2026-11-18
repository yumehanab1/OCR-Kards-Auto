"""Current daily-login claim geometry. No store, pack-opening or generic continue."""
import re
import cv2
import numpy as np

ACTIONS={'daily_reward_available':'menu_claim_daily',
         'daily_reward_claim':'menu_collect_daily',
         'daily_reward_continue':'menu_continue_daily'}


def recognize(frame,items):
    h,w=frame.shape[:2];rows=[]
    for item in items:
        score=item.get('score')
        if type(score) not in (int,float) or not np.isfinite(score) or not .90<=score<=1:continue
        try:p=np.asarray(item.get('box'),dtype=float)
        except (TypeError,ValueError):continue
        if p.shape!=(4,2) or not np.isfinite(p).all():continue
        a,b=np.floor(p.min(axis=0)).astype(int);c,d=np.ceil(p.max(axis=0)).astype(int)
        if not (0<=a<c<=w and 0<=b<d<=h):continue
        text=re.sub(r'\s+','',str(item.get('text',''))).rstrip('。.!！')
        rows.append(dict(text=text,score=float(score),bounds=[int(a),int(b),int(c-a),int(d-b)]))
    # A price/purchase/open-pack caption in this frame vetoes new claim authority.
    if any(re.search(r'购买|商店|开包|打开卡包|开启卡包|支付|充值|[¥￥$€]',r['text']) for r in rows):return None
    def center(r):
        x,y,bh,bv=r['bounds'];return x+bh/2,y+bv/2
    def unique(text):
        found=[r for r in rows if r['text']==text]
        return found[0] if len(found)==1 else None
    title=unique('每日登录奖励');available=unique('奖励现可领取');claim=unique('领取')
    if title and available and claim:
        tx,ty=center(title);ax,ay=center(available);cx,cy=center(claim)
        if not (.20*w<tx<.80*w and .06*h<ty<.30*h and .20*w<ax<.80*w
                and .70*h<ay<.96*h and .20*w<cx<.80*w and .18*h<cy<.62*h):return None
        edges=cv2.Canny(frame,40,100)
        hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        orange=cv2.inRange(hsv,(5,80,100),(40,255,255))
        contours=list(cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0])
        contours+=list(cv2.findContours(orange,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0])
        boxes=[]
        for contour in contours:
            x,y,bw,bh=cv2.boundingRect(contour)
            if not (.075*h<bw<.18*h and .11*h<bh<.26*h and .60<bw/bh<.85
                    and cy<y<cy+.12*h and y+bh<available['bounds'][1]
                    and x<cx<x+bw and cv2.contourArea(contour)>.75*bw*bh):continue
            if any(max(abs(v-u) for v,u in zip([x,y,bw,bh],box))<=8 for box in boxes):continue
            boxes.append([x,y,bw,bh])
        if len(boxes)==1:
            return dict(state='daily_reward_available',basis='current_daily_title_available_unique_claim_card',
                        title=title,available=available,claim=claim,target_bounds=boxes[0],day=None)
        if boxes:return None
        # The ticket is a rotated orange item, not a vertical card frame.
        # Its exact caption and unique claim must bracket the measured item.
        captions=[r for r in rows if re.fullmatch(r'1[x×]?竞技场门票',r['text'])]
        if len(captions)!=1:return None
        caption=captions[0];qx,qy=center(caption)
        if not (abs(qx-cx)<.025*w and cy+.12*h<qy<cy+.32*h):return None
        tickets=[]
        for box in ticket_boxes(frame):
            x,y,bw,bh=box
            if not (x<cx<x+bw and cy+.03*h<y<cy+.12*h
                    and y+bh<caption['bounds'][1] and y+bh>caption['bounds'][1]-.08*h):continue
            tickets.append(box)
        if len(tickets)!=1:return None
        return dict(state='daily_reward_available',basis='current_daily_title_available_unique_claim_ticket',
                    title=title,available=available,claim=claim,caption=caption,
                    target_bounds=tickets[0],day=None)
    days=[r for r in rows if re.fullmatch(r'第([1-9]|[12][0-9]|3[01])天',r['text'])
          and .30*w<center(r)[0]<.70*w and center(r)[1]<.12*h]
    prompts=[r for r in rows if r['text'] in ('轻触领取','轻触继续')
             and .30*w<center(r)[0]<.70*w and .88*h<center(r)[1]<.995*h]
    if len(days)!=1 or len(prompts)!=1:return None
    day=int(re.search(r'\d+',days[0]['text'])[0]);prompt=prompts[0]
    # This evidence alone is NOT dispatch authority: MenuFlow requires the
    # corresponding prior completed daily receipt and a new capture.
    return dict(state='daily_reward_claim' if prompt['text']=='轻触领取' else 'daily_reward_continue',
                basis='current_daily_day_and_exact_prompt',day=day,day_label=days[0],prompt=prompt,
                target_bounds=prompt['bounds'])


def ticket_boxes(frame):
    """Current orange silhouette proposals only, never claim authority."""
    h,w=frame.shape[:2]
    orange=cv2.inRange(cv2.cvtColor(frame,cv2.COLOR_BGR2HSV),(5,80,100),(40,255,255))
    boxes=[]
    for c in cv2.findContours(orange,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
        x,y,bw,bh=cv2.boundingRect(c);area=cv2.contourArea(c)
        hull=cv2.contourArea(cv2.convexHull(c))
        if (.10*h<bw<.17*h and .11*h<bh<.18*h and .80<bw/bh<1.20
                and .20*h<y<.68*h and area>.50*bw*bh and hull>0 and area/hull>.90):
            boxes.append([x,y,bw,bh])
    return boxes


def regions(frame):
    """Only text/control bands; skip expensive reward artwork during OCR."""
    h,w=frame.shape[:2]
    return [[round(w*.26),0,round(w*.48),round(h*.57)],
            [round(w*.30),round(h*.79),round(w*.40),h-round(h*.79)]]


def ticket_return_evidence(observation,items,packet,now,ocr_ok):
    """No-input postcondition only; never infer completion from unknown/absence.

    The collect receipt and ticket identity are owned by MenuFlow. A recognized
    normal destination AND current scoped absence of daily/purchase text are
    needed on two fresh independent captures before that flow is released.
    """
    state=observation.get('state')
    destination=(state in ('home','mode_menu','deck_list','deck_ready') or
                 state=='blocking_popup' and observation.get('popup_basis')=='task_title_and_subtitle')
    age=now-packet.get('captured_elapsed_ms',-100000)
    if not destination or not ocr_ok or not 0<=age<=3000:return None
    for row in items:
        text=re.sub(r'\s+','',str(row.get('text','')))
        # Even a weak OCR proposal of a reward/purchase is not a safe absence.
        if re.search(r'轻触|每日登录奖励|奖励现可领取|竞技场|领取|继续|购买|商店|开包|卡包|支付|充值|[¥￥$€]',text):return None
    keys=('frame_id','captured_elapsed_ms','foreground_generation','source_width','source_height')
    if any(type(packet.get(k)) is not int for k in keys):return None
    return dict(basis='current_ticket_collected_normal_destination_no_daily_prompt',
                destination=state,**{k:packet[k] for k in keys})
