"""Current-frame shared template response equivalence and gap exclusion."""
import cv2,numpy as np,time
from .page_detector import Detector

def run():
    rng=np.random.default_rng(172);checks=[]
    def baseline(gray,needle,regions):
        score,point=-1.,(0,0)
        for a,b,c,d in regions:
            _,value,_,where=cv2.minMaxLoc(cv2.matchTemplate(gray[b:d,a:c],needle,cv2.TM_CCOEFF_NORMED))
            if value>score:score,point=value,(a+where[0],b+where[1])
        return score,point
    layouts=[[],[(0,0,100,100)],[(0,0,140,140),(20,10,160,150),(5,15,155,155)],
             [(0,0,80,80),(120,120,200,200)],[(0,0,180,80),(0,120,180,200),(0,0,80,200)]]
    for seed in range(20):
        gray=rng.integers(0,256,(200,200),dtype=np.uint8)
        needle=gray[90:110,90:110].copy()
        for i,regions in enumerate(layouts):
            old=baseline(gray,needle,regions);new=Detector.match_regions(gray,needle,regions)
            assert abs(old[0]-new[0])<2e-5,(old,new)
            assert old[1]==new[1],(old,new)
            checks.append('equivalence_%s_%s'%(seed,i))
    # Bounding work may contain a perfect target excluded by every candidate.
    gray=rng.integers(0,256,(200,200),dtype=np.uint8);needle=gray[90:110,90:110].copy()
    regions=[(0,0,180,80),(0,120,180,200),(0,0,80,200)]
    score,point=Detector.match_regions(gray,needle,regions)
    assert score<.93 and point!=(90,90)
    checks.append('bounding_gap_never_authorizes')
    gray[:]=0
    assert Detector.match_regions(gray,needle,regions)[0]<.93
    checks.append('new_pixels_no_negative_or_positive_cache')
    return dict(passed=True,checks=checks)

if __name__=='__main__':print(run())
