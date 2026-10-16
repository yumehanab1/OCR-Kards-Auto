"""Current modal close shape, independent of promotional words and templates."""
import json
import cv2
import numpy as np
from .generic_popup import inspect,_cross_shape


def run():
    checks=[]
    def check(name,valid):
        if not valid:raise AssertionError(name)
        checks.append(name)
    def panel(kind='cross',dx=0,dy=0):
        frame=np.full((720,1280,3),30,np.uint8)
        x,y,w,h=300+dx,180+dy,680,360
        cv2.rectangle(frame,(x,y),(x+w,y+h),(145,145,145),2)
        a,b=x+w-36,y+16;size=22
        if kind in ('cross','one_diagonal','half_cross'):
            cv2.line(frame,(a,b),(a+size,b+size),(225,225,225),3,cv2.LINE_AA)
        if kind=='cross':cv2.line(frame,(a+size,b),(a,b+size),(225,225,225),3,cv2.LINE_AA)
        elif kind=='half_cross':cv2.line(frame,(a+size,b),(a+size//2,b+size//2),(225,225,225),3,cv2.LINE_AA)
        elif kind=='solid':cv2.rectangle(frame,(a,b),(a+size,b+size),(225,225,225),-1)
        elif kind=='text':cv2.putText(frame,'AXA',(a-25,b+size),cv2.FONT_HERSHEY_SIMPLEX,.8,(225,225,225),2,cv2.LINE_AA)
        return frame
    original=panel();proof=inspect(original,{})
    check('current_modal_cross_without_template',proof is not None and proof['basis']=='current_close_x_geometry')
    check('measured_diagonal_coverage',min(proof['close']['diagonal_coverage'])>=.70)
    check('shape_score_is_actual_geometric_product',abs(proof['close']['score']-
        min(proof['close']['diagonal_coverage'])*proof['close']['diagonal_purity'])<1e-9)
    check('measured_panel_has_two_current_sides',sum(value>=.65 for value in proof['edge_coverage'])>=2)
    x,y,w,h=proof['close']['bounds'];px,py,pw,ph=proof['panel_bounds']
    check('target_in_measured_top_right',px+pw*.75<=x<x+w<=px+pw+1 and py<=y<y+h<=py+ph*.25)
    for scale in (.70,1.40):
        frame=cv2.resize(original,(round(1280*scale),round(720*scale)),interpolation=cv2.INTER_AREA)
        check('scaled_cross_'+str(scale),inspect(frame,{}) is not None)
    for dx,dy in ((-55,-30),(55,35)):
        check('translated_panel_'+str(dx),inspect(panel(dx=dx,dy=dy),{}) is not None)
    for kind in ('one_diagonal','half_cross','solid','text','none'):
        check(kind+'_rejected',inspect(panel(kind),{}) is None)
    no_modal=np.full_like(original,30)
    cv2.line(no_modal,(945,196),(967,218),(225,225,225),3)
    cv2.line(no_modal,(967,196),(945,218),(225,225,225),3)
    check('standalone_menu_cross_without_modal_rejected',inspect(no_modal,{}) is None)
    check('solid_component_rejected',_cross_shape(np.ones((20,20),np.uint8)) is None)
    slash=np.zeros((20,20),np.uint8);cv2.line(slash,(0,0),(19,19),1,3)
    check('single_diagonal_component_rejected',_cross_shape(slash) is None)
    return dict(passed=True,checks=checks,scope='generated_current_modal_close_geometry',device_inputs=0,captures=0)


if __name__=='__main__':print(json.dumps(run(),ensure_ascii=True))
