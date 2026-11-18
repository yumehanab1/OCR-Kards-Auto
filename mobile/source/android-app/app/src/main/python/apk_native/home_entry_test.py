"""Fine-scale home proof and small news-art cross rejection; no input authority."""
import cv2
import numpy as np
from .page_detector import Detector
from .generic_popup import inspect_geometry


def run():
    checks=[]
    rng=np.random.default_rng(175)
    bank={n:rng.integers(0,256,(40,32,3),dtype=np.uint8) for n in ('home_play','home_tasks')}
    gray=rng.integers(0,30,(720,1280),dtype=np.uint8)
    needle=cv2.cvtColor(cv2.resize(bank['home_play'],(34,43)),cv2.COLOR_BGR2GRAY)
    gray[100:143,40:74]=needle
    detector=Detector(bank,'filtered',refine=True)
    evidence={'home_play':dict(score=.80,bounds=[40,100,32,40],factor=1.,ok=False),
              'home_tasks':dict(score=.98,bounds=[600,600,32,40],factor=1.,ok=True)}
    detector.refine_home_entry(gray,evidence)
    assert evidence['home_play']['ok'] and evidence['home_play']['score']>=.93
    checks.append('current_tasks_corroborates_fine_start_scale')
    evidence={'home_play':dict(score=.80,bounds=[40,100,32,40],factor=1.,ok=False),
              'home_tasks':dict(score=.80,bounds=[600,600,32,40],factor=1.,ok=False)}
    detector.refine_home_entry(gray,evidence)
    assert not evidence['home_play']['ok']
    checks.append('missing_tasks_never_authorizes_start')
    frame=np.full((720,1280,3),30,np.uint8)
    cv2.rectangle(frame,(300,180),(980,540),(145,145,145),2)
    cv2.line(frame,(950,196),(956,202),(225,225,225),1)
    cv2.line(frame,(956,196),(950,202),(225,225,225),1)
    assert inspect_geometry(frame) is None
    checks.append('tiny_news_cross_rejected')
    return dict(passed=True,checks=checks,device_inputs=0)


if __name__=='__main__':print(run())
