"""Lazy features owned by one source frame; no reuse across frames."""
import cv2


class FrameFeatures:
    def __init__(self,frame):
        self.frame=frame
        self.values={}

    def get(self,name):
        if name not in self.values:
            if name=='gray':value=cv2.cvtColor(self.frame,cv2.COLOR_BGR2GRAY)
            elif name=='hsv':value=cv2.cvtColor(self.frame,cv2.COLOR_BGR2HSV)
            elif name=='edges':value=cv2.Canny(self.frame,40,100)
            elif name=='structure_edges':
                # Suppress table weave before looking for card-sized boundaries.
                # Hand numerals, type icons and action colors use original pixels.
                value=cv2.Canny(cv2.GaussianBlur(self.frame,(0,0),1.5*self.frame.shape[0]/720),40,100)
            elif name=='cardinal_structure_edges':
                # Empty-row texture coverage only; card inventory still uses
                # original and full blurred contours, including unknown cards.
                import numpy as np
                smooth=cv2.GaussianBlur(self.frame,(0,0),1.5*self.frame.shape[0]/720)
                dx=np.abs(cv2.Sobel(smooth,cv2.CV_32F,1,0)).max(axis=2)
                dy=np.abs(cv2.Sobel(smooth,cv2.CV_32F,0,1)).max(axis=2)
                value=cv2.Canny(smooth,40,100)
                value[~((dx>=2*dy)|(dy>=2*dx))]=0
                _,labels,stats,_=cv2.connectedComponentsWithStats((value>0).astype(np.uint8),8)
                keep=stats[:,cv2.CC_STAT_AREA]>=max(8,round(12*self.frame.shape[0]/720));keep[0]=False
                value[~keep[labels]]=0
            else:raise KeyError(name)
            self.values[name]=value
        return self.values[name]
