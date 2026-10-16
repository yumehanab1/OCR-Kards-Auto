"""Real five-card phone opening and generated four-card/control-size replay."""
import json
from pathlib import Path
import cv2
import numpy as np
from .opening import OpeningRecognizer
from .resource_anchors import inspect


def run(source,assets,ocr=None):
    frame=cv2.imdecode(np.frombuffer(Path(source).read_bytes(),np.uint8),1)
    h,w=frame.shape[:2];checks=[]
    def observe(image):
        return OpeningRecognizer(assets).observe(image,dict(coordinate_space='source_pixels',
                source_height=image.shape[0],source_width=image.shape[1]),ocr)
    def check(name,valid):
        if not valid:raise AssertionError(name)
        checks.append(name)
    found=observe(frame)
    check('real_phone_five_cards',found['phase']=='MULLIGAN_CONFIRM')
    own=found['resource_anchors']['own']['bounds']
    check('connected_resource_edges_verified',found['resource_anchors']['own'].get('proposal_basis')=='other_current_resource_box'
          and min(found['resource_anchors']['own']['edge_coverage'])>=.94)
    x,y,bw,bh=own
    for side in ('top','bottom','left','right'):
        damaged=frame.copy();p=16
        if side=='top':damaged[y-p:y+p,x-p:x+bw+p]=0
        elif side=='bottom':damaged[y+bh-p:y+bh+p,x-p:x+bw+p]=0
        elif side=='left':damaged[y-p:y+bh+p,x-p:x+p]=0
        else:damaged[y-p:y+bh+p,x+bw-p:x+bw+p]=0
        check('missing_own_'+side+'_rejected',not inspect(damaged)['ok'])
    for label in ('title','confirm'):
        pts=np.asarray(found['structure'][label]['box']);a,b=np.floor(pts.min(axis=0)).astype(int);c,d=np.ceil(pts.max(axis=0)).astype(int)
        damaged=frame.copy();damaged[b-12:d+12,a-12:c+12]=0
        check('missing_'+label+'_rejected',observe(damaged)['phase']=='UNKNOWN')

    # Preserve resource/title/control pixels; replace only the five large cards
    # with four generated copies. This is generated evidence, not a new live game.
    four=frame.copy();card=frame[341:919,295:703].copy()
    four[332:924,285:2492]=0
    for cx in (700,1160,1620,2080):four[341:919,cx-204:cx+204]=card
    for row in ('own','enemy'):
        a,b,c,d=found['resource_anchors'][row]['bounds']
        four[b-18:b+d+18,a-18:a+c+18]=frame[b-18:b+d+18,a-18:a+c+18]
    check('generated_four_cards',observe(four)['phase']=='MULLIGAN_CONFIRM')
    bx,by,bw,bh=found['target_bounds'];button=frame[by-10:by+bh+10,bx-10:bx+bw+10].copy()
    title_pts=np.asarray(found['structure']['title']['box']);tx,ty=np.floor(title_pts.min(axis=0)).astype(int);ta,tb=np.ceil(title_pts.max(axis=0)).astype(int)
    title=frame[ty-10:tb+10,tx-10:ta+10].copy()
    for factor in (.8,1.25,1.4):
        changed=frame.copy();changed[by-18:by+bh+18,bx-18:bx+bw+18]=0
        changed[ty-12:tb+12,tx-12:ta+12]=0
        for image,cx,cy in ((button,bx+bw/2,by+bh/2),(title,(tx+ta)/2,(ty+tb)/2)):
            nw,nh=round(image.shape[1]*factor),round(image.shape[0]*factor)
            left,top=round(cx-nw/2),round(cy-nh/2)
            changed[top:top+nh,left:left+nw]=cv2.resize(image,(nw,nh))
        check('generated_control_scale_'+str(factor),observe(changed)['phase']=='MULLIGAN_CONFIRM')
    check('black_screen_rejected',observe(np.zeros_like(frame))['phase']=='UNKNOWN')
    return json.dumps(dict(passed=True,scope='saved_lossy_real_five_card_and_generated_four_card_size_replay',
                           checks=checks,opening=found,device_inputs=0,captures=0))

def run_device(source,assets,engine,characters_json):
    from .onnx_ocr import OriginalModelOCR,java_inference
    offset=lambda box,distance:json.loads(str(engine.offsetPolygon(json.dumps(np.asarray(box).tolist()),float(distance))))
    ocr=OriginalModelOCR(java_inference(engine),json.loads(str(characters_json)),offset)
    from .recognition_scale import shrink
    from .opening_dynamic import inspect as dynamic_opening
    image=cv2.imdecode(np.frombuffer(Path(source).read_bytes(),np.uint8),1)
    small,_=shrink(image)
    dynamic=dynamic_opening(small,ocr,True)
    if not dynamic['ready']:raise AssertionError('real_model_template_free_opening')
    result=json.loads(run(source,assets,ocr))
    result['template_free_dynamic']=dynamic
    from .opening_dynamic_test import run as negatives
    result['dynamic_negatives']=negatives(small,dynamic)
    return json.dumps(result,ensure_ascii=False)
