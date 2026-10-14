"""Current daily-task overlay; cleanup only targets reviewed blank background."""
import cv2
import numpy as np


def inspect(frame, templates, specs):
    h,w=frame.shape[:2]
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    title=templates.get('native_daily_title');refuse=templates.get('native_daily_refuse')
    if title is None or refuse is None:return None
    best=None
    for factor in np.arange(.90,1.101,.01):
        scale=h/1240*factor
        needle=cv2.resize(title,(round(title.shape[1]*scale),round(title.shape[0]*scale)),interpolation=cv2.INTER_AREA)
        roi=gray[round(h*.14):round(h*.32),round(w*.38):round(w*.62)]
        if roi.shape[0]<needle.shape[0] or roi.shape[1]<needle.shape[1]:continue
        _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,needle,cv2.TM_CCOEFF_NORMED))
        if best is None or score>best[0]:best=(float(score),scale,point[0]+round(w*.38),point[1]+round(h*.14))
    if best is None or best[0]<.94:return None
    score,scale,tx,ty=best
    sx,sy,_,_=specs['native_daily_title']['bounds']
    rx,ry,rw,rh=specs['native_daily_refuse']['bounds']
    needle=cv2.resize(refuse,(round(rw*scale),round(rh*scale)),interpolation=cv2.INTER_AREA)
    buttons=[]
    for index,offset in enumerate((0,297,594)):
        name='native_daily_refuse'+str(index)
        if name in templates:
            refuse=templates[name];rx,ry,rw,rh=specs[name]['bounds'];offset=0
            needle=cv2.resize(refuse,(round(rw*scale),round(rh*scale)),interpolation=cv2.INTER_AREA)
        x,y=round(tx+(rx+offset-sx)*scale),round(ty+(ry-sy)*scale)
        pad=max(4,round(h*.01));left,top=max(0,x-pad),max(0,y-pad)
        roi=gray[top:min(h,y+needle.shape[0]+pad),left:min(w,x+needle.shape[1]+pad)]
        if roi.shape[0]<needle.shape[0] or roi.shape[1]<needle.shape[1]:continue
        matched=None
        for adjustment in (.98,.99,1.,1.01,1.02):
            candidate=cv2.resize(refuse,(round(rw*scale*adjustment),round(rh*scale*adjustment)),interpolation=cv2.INTER_AREA)
            if candidate.shape[0]>roi.shape[0] or candidate.shape[1]>roi.shape[1]:continue
            _,value,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,candidate,cv2.TM_CCOEFF_NORMED))
            if matched is None or value>matched[0]:matched=(value,point,candidate)
        if matched is None or matched[0]<.94:continue
        value,point,needle=matched
        buttons.append(dict(score=float(value),bounds=[left+point[0],top+point[1],needle.shape[1],needle.shape[0]]))
    if not buttons:return None
    size=max(8,round(h*24/720));cx=w/2;cy=round(h*665/720)
    x,y=round(cx-size/2),round(cy-size/2)
    # Completed task slots have no refuse button. A current title plus at least
    # one visible task control proves this overlay; only blank background is tapped.
    region=frame[y:y+size,x:x+size];hsv=cv2.cvtColor(region,cv2.COLOR_BGR2HSV)
    blank=float(((hsv[:,:,2]<145)&(hsv[:,:,1]<150)).mean())
    if blank<.94 or cy<max(b['bounds'][1]+b['bounds'][3] for b in buttons)+h*.08:return None
    return dict(title_score=score,buttons=buttons,blank_score=blank,
                target_bounds=[cx-size/2,cy-size/2,size,size])


def saved_check(path, assets):
    import json,time
    from pathlib import Path
    assets=Path(assets)
    specs=json.loads((assets/'manifest.json').read_text(encoding='utf-8'))['templates']
    templates={n:cv2.imread(str(assets/specs[n]['file']),0) for n in ('native_daily_title','native_daily_refuse','native_daily_refuse0','native_daily_refuse1','native_daily_refuse2')}
    frame=cv2.imread(str(path));start=time.perf_counter()
    proof=inspect(frame,templates,specs)
    if proof is None:raise ValueError('daily_fixture_unrecognized')
    for erase_title in (True,False):
        boxes=[specs['native_daily_title']['bounds']] if erase_title else [b['bounds'] for b in proof['buttons']]
        changed=frame.copy()
        for box in boxes:
            x,y,w,h=map(round,box);changed[y:y+h,x:x+w]=0
        if inspect(changed,templates,specs) is not None:raise ValueError('daily_fixture_negative')
    return json.dumps(dict(passed=True,ms=(time.perf_counter()-start)*1000,proof=proof,device_inputs=0))
