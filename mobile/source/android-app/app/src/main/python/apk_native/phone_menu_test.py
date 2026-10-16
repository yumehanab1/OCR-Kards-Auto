"""Saved phone selector replay; templates never consume this review as an asset."""
import json
from pathlib import Path
import cv2
import numpy as np
from .menu import NativeMenuRecognizer


def run(source, assets):
    frame=cv2.imdecode(np.frombuffer(Path(source).read_bytes(),np.uint8),1)
    recognizer=NativeMenuRecognizer(assets,None,startup=True)
    h,w=frame.shape[:2]
    packet=dict(coordinate_space='source_pixels',source_height=h,source_width=w)
    observed=recognizer.observe(frame,packet)
    checks=[]
    def check(name,valid):
        if not valid:raise AssertionError(name)
        checks.append(name)
    check('ranked_highlight_and_grey_casual',observed['state']=='deck_ready' and observed['selected_mode']=='ranked')
    check('no_whole_page_ocr',not observed['ocr_items'] and not observed['ocr_metrics'])
    for key in ('menu_select_casual','menu_select_ranked'):
        x,y,bw,bh=observed['targets'][key]
        missing=frame.copy();missing[y-10:y+bh+10,x-10:x+bw+10]=0
        changed=recognizer.observe(missing,packet)
        check('missing_'+key,changed['state']!='deck_ready' and not changed['selected_mode'])
    switched=frame.copy()
    for key,color in [('menu_select_casual',(0,140,255)),('menu_select_ranked',(190,190,190))]:
        x,y,bw,bh=observed['targets'][key]
        roi=switched[y:y+bh,x:x+bw]
        hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV)
        mask=((hsv[:,:,2]>120)&(hsv[:,:,1]<105) if 'casual' in key else
              (hsv[:,:,0]>=5)&(hsv[:,:,0]<=35)&(hsv[:,:,1]>=120)&(hsv[:,:,2]>=100))
        roi[mask]=color
    new=recognizer.observe(switched,packet)
    check('generated_casual_highlight_current_pixels',new['state']=='deck_ready' and new['selected_mode']=='casual')
    check('black_page_has_no_selector',recognizer.observe(np.zeros_like(frame),packet)['selected_mode']=='')
    return json.dumps(dict(passed=True,scope='saved_lossy_phone_menu_and_generated_negatives',
                           checks=checks,selected_mode=observed['selected_mode'],targets=observed['targets'],
                           device_inputs=0,captures=0))
