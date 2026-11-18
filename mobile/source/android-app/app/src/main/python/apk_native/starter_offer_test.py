"""Real 4:3 starter-panel replay; mutations must never authorize a purchase."""
import copy
import json
from pathlib import Path
import unittest
import cv2
from .generic_popup import starter_offer, inspect_geometry, starter_regions
from .recognition_scale import shrink


class StarterOfferTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parents[6]
        evidence=root/'repro/tablet179_20261117'
        cls.frame,_=shrink(cv2.imread(str(evidence/'tablet35-starter-original.png')))
        cls.items=json.loads((evidence/'tablet35-starter-ocr.json').read_text('utf8'))

    def test_real_panel_and_x(self):
        result=starter_offer(self.frame,self.items)
        self.assertEqual(result['offer_id'],'starter_bundle')
        self.assertEqual(result['close']['bounds'],[890,152,23,22])
        regions=starter_regions(self.frame)
        self.assertEqual(len(regions),2)
        self.assertTrue(all(0<=x<x+w<=960 and 0<=y<y+h<=720 for x,y,w,h in regions))
        self.assertIsNone(inspect_geometry(self.frame))  # General path not widened.

    def test_caption_required_unique_and_high_confidence(self):
        for title in ('入门礼包','一次性优惠。'):
            rows=[r for r in self.items if r['text']!=title]
            self.assertIsNone(starter_offer(self.frame,rows))
            row=next(r for r in self.items if r['text']==title)
            self.assertIsNone(starter_offer(self.frame,self.items+[row]))
            rows=copy.deepcopy(self.items)
            next(r for r in rows if r['text']==title)['score']=.92
            self.assertIsNone(starter_offer(self.frame,rows))

    def test_no_x_no_border_no_authority(self):
        for x,y,w,h in ((875,140,50,45),(15,120,930,30),(15,570,930,30)):
            frame=self.frame.copy();frame[y:y+h,x:x+w]=0
            self.assertIsNone(starter_offer(frame,self.items))

    def test_caption_geometry(self):
        rows=copy.deepcopy(self.items)
        next(r for r in rows if r['text']=='入门礼包')['box']=[[800,200],[900,200],[900,250],[800,250]]
        self.assertIsNone(starter_offer(self.frame,rows))


if __name__=='__main__':unittest.main()
