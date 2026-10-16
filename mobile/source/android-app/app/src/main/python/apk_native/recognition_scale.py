"""Uniform height-720 recognition, with explicit coordinate restoration."""
import cv2
import numpy as np

BOXES={'box','boxes','bounds','regions','target_bounds','panel_bounds','card_box','card_box_estimate','badge_box','shield_box',
       'label_bounds','hq_box','rectangles','support_rectangles','unclassified_support_rectangles','unknown_rectangles','sharp_unknown_rectangles'}
POINTS={'center','digit_center','digit_center_source','grab_source','drop_source','point','at','grab','position'}

def shrink(frame):
    h,w=frame.shape[:2]
    if h<=720:return frame,(1.,1.)
    width=round(w*720/h)
    return cv2.resize(frame,(width,720),interpolation=cv2.INTER_AREA),(w/width,h/720)

def coordinates(value,sx,sy,key=''):
    if isinstance(value,np.generic):value=value.item()
    if isinstance(value,np.ndarray):value=value.tolist()
    if isinstance(value,dict):
        out={k:coordinates(v,sx,sy,k) for k,v in value.items()}
        for k in ('cx','x','left','right'):
            if isinstance(out.get(k),(int,float)):out[k]*=sx
        for k in ('cy','y','top','bottom','line_y'):
            if isinstance(out.get(k),(int,float)):out[k]*=sy
        return out
    if isinstance(value,(list,tuple)):
        if key in BOXES|POINTS and value and all(isinstance(v,(int,float,np.number)) for v in value):
            return [(round(float(v)*(sx if i%2==0 else sy)) if key in BOXES else float(v)*(sx if i%2==0 else sy)) for i,v in enumerate(value)]
        if key in BOXES|POINTS:return [coordinates(v,sx,sy,key) for v in value]
        return [coordinates(v,sx,sy) for v in value]
    return value

def restore(result,frame,scaled,factors):
    from .layout_profiles import for_shape
    out=coordinates(result,*factors)
    out['source_shape']=list(frame.shape)
    out['coordinate_space']='source_pixels'
    out['recognition_shape']=list(scaled.shape)
    out['recognition_scale_to_source']=list(factors)
    out['layout_profile']=for_shape(frame.shape).name
    return out
