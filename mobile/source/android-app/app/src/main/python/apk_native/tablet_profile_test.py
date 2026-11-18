"""Landscape tablet admission and lossless coordinate contracts (offline only)."""
import unittest
import numpy as np
from .pipeline import Pipeline
from .layout_profiles import for_shape
from .recognition_scale import shrink, restore
from .result import ResultRecognizer


class TabletProfileTests(unittest.TestCase):
    def test_supported_landscape_profiles(self):
        for w,h in ((1920,1200),(2560,1600),(1600,1200),(2048,1536),
                    (1800,1200),(1280,1000),(2400,1080),(2520,1080)):
            with self.subTest(size=(w,h)):
                frame=np.full((h,w,3),30,np.uint8)
                Pipeline._validate(frame)
                if w/h<1.70:self.assertEqual('tablet_landscape',for_shape(frame.shape).name)

    def test_unsupported_shapes_and_alpha(self):
        for shape in ((1200,1200,3),(1200,1500,3),(1200,900,3),
                      (1000,2401,3),(1200,1600,4),(0,1600,3)):
            with self.subTest(shape=shape),self.assertRaises(ValueError):
                Pipeline._validate(np.zeros(shape,np.uint8))

    def test_tablet_source_restoration_is_uniform_not_stretched(self):
        for w,h in ((1920,1200),(1600,1200),(2048,1536)):
            frame=np.full((h,w,3),30,np.uint8)
            reduced,factors=shrink(frame)
            self.assertEqual((720,round(w*720/h),3),reduced.shape)
            # The fixed grab offset is 25 source-height-normalized pixels,
            # never 25 * source_width/1280 on a tablet.
            restored=restore({'grab_source':[125.,225.],'digit_center_source':[100.,200.],
                              'target_bounds':[90,190,40,40]},frame,reduced,factors)
            point=restored['grab_source'];digit=restored['digit_center_source']
            self.assertAlmostEqual(25*h/720,point[1]-digit[1])
            self.assertAlmostEqual(25*factors[0],point[0]-digit[0])
            self.assertLess(abs(factors[0]-factors[1]),.002)
            self.assertEqual([h,w,3],restored['source_shape'])
            self.assertEqual('source_pixels',restored['coordinate_space'])

    def test_result_semantics_do_not_relax_on_tablet(self):
        for w,h in ((1920,1200),(1600,1200)):
            def row(text,x,y):
                return dict(text=text,score=.99,box=[[x,y],[x+40,y],[x+40,y+20],[x,y+20]])
            items=[row('失败',w*.48,h*.5),row('继续',w*.48,h*.90)]
            frame=np.full((h,w,3),30,np.uint8)
            recognizer=ResultRecognizer()
            self.assertTrue(recognizer.inspect(frame,dict(state='result_defeat',ocr_items=items),None)['ready'])
            self.assertFalse(recognizer.inspect(frame,dict(state='result_defeat',ocr_items=items[:1]),None)['ready'])
            self.assertFalse(recognizer.inspect(frame,dict(state='result_defeat',ocr_items=items+[row('胜利',w*.5,h*.4)]),None)['ready'])


if __name__=='__main__':unittest.main()
