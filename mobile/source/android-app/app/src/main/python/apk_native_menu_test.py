import unittest
import io,json
from apk_native.menu import popup_target
from apk_native.menu import first_deck_target,pass_popup_target
import cv2
import numpy as np
from apk_match_entry import MenuFlow
from apk_native.ocr_bridge import NativeOCR
from apk_native.page_detector import Detector
from apk_native.generic_popup import inspect as generic_popup


def text(value, score=.99, box=None):
    return {'text':value,'score':score,'box':box or [[1200,180],[1500,180],[1500,230],[1200,230]]}


class NativeMenuTests(unittest.TestCase):
    def test_generic_close_requires_panel_and_corner_x(self):
        rng=np.random.default_rng(9)
        cross=rng.integers(0,256,(25,25,3),dtype=np.uint8)
        frame=np.zeros((720,1280,3),np.uint8)
        cv2.rectangle(frame,(360,200),(920,500),(200,200,200),2)
        frame[210:235,885:910]=cross
        found=generic_popup(frame,{'test_close':cross})
        self.assertIsNotNone(found)
        self.assertGreaterEqual(found['close']['score'],.93)
        self.assertIsNone(generic_popup(np.zeros_like(frame),{'test_close':cross}))
        frame[198:204,355:925]=0
        self.assertIsNone(generic_popup(frame,{'test_close':cross}))

    def test_distinct_generic_popups_need_two_frames_and_receipt(self):
        flow=MenuFlow('casual',0)
        one={'state':'generic_popup','popup_id':'a'*64,'targets':{'menu_dismiss_generic':[900,210,25,25]}}
        self.assertIn('wait',flow.observe(one,1,500))
        self.assertEqual('menu_dismiss_generic',flow.observe(one,2,1000)['action'])
        flow.accepted('menu_dismiss_generic',1000,one['popup_id'])
        self.assertIn('wait',flow.observe(one,3,1500))
        two=dict(one,popup_id='b'*64)
        self.assertIn('wait',flow.observe(two,4,2000))
        self.assertEqual('menu_dismiss_generic',flow.observe(two,5,2500)['action'])

    def test_local_scale_refinement_checks_current_pixels(self):
        rng=np.random.default_rng(42)
        template=rng.integers(0,256,(40,80,3),dtype=np.uint8)
        template=cv2.GaussianBlur(template,(7,7),2)
        needle=cv2.cvtColor(cv2.resize(template,(90,45)),cv2.COLOR_BGR2GRAY)
        gray=np.zeros((720,1280),np.uint8);gray[200:245,300:390]=needle
        detector=Detector({'label':template},'filtered',refine=True)
        detector.text_boxes=[(300,200,90,45)]
        first=detector.match(gray,'label')
        self.assertGreaterEqual(first['score'],.93)
        self.assertLessEqual(max(abs(a-b) for a,b in zip([300,200,90,45],first['bounds'])),2)
        blank=detector.match(np.zeros_like(gray),'label')
        self.assertLess(blank['score'],.93)

    def test_ocr_cache_requires_exact_pixels_and_current_geometry(self):
        class Bridge:
            calls=0
            fail=False
            def recognizeNativeText(self,request):
                self.calls+=1
                if self.fail:return json.dumps({'ok':False,'reason':'expired'})
                return json.dumps(dict(json.loads(request),ok=True,coordinate_space='source_pixels',
                    height=4,width=6,items=[dict(text='开始',score=.99,score_available=True,
                        box=[[0,0],[2,0],[2,2],[0,2]])]))
        bridge=Bridge();ocr=NativeOCR(bridge);frame=np.zeros((4,6,3),np.uint8)
        packet=dict(coordinate_space='source_pixels',height=4,width=6,source_height=4,source_width=6,
                    frame_id=1,captured_elapsed_ms=0,foreground_generation=1,png_path='one')
        ocr.bind(packet);items,_=ocr(frame);items[0][0][0][0]=99
        ocr.bind(dict(packet,frame_id=2,png_path='two'))
        again,_=ocr(frame.copy())
        self.assertEqual(1,bridge.calls);self.assertEqual(0,again[0][0][0][0])
        self.assertTrue(ocr.last_metrics['cache_hit'])
        frame[0,0,0]=1;ocr(frame);self.assertEqual(2,bridge.calls)
        bridge.fail=True;frame[0,0,0]=2
        self.assertEqual([],ocr(frame)[0]);self.assertEqual([],ocr(frame)[0])
        self.assertEqual(4,bridge.calls)
        ocr.bind(dict(packet,source_width=7))
        with self.assertRaises(ValueError):ocr(frame)

    def test_pass_requires_full_panel_and_independent_captions(self):
        frame=np.zeros((1240,2772,3),np.uint8)
        cv2.rectangle(frame,(830,340),(1942,900),(200,200,200),2)
        captions=[text('10月战场通票',box=[[880,380],[1250,380],[1250,450],[880,450]]),
                  text('现已上架商店！',box=[[880,470],[1200,470],[1200,510],[880,510]])]
        self.assertIsNotNone(pass_popup_target(frame,captions))
        self.assertIsNone(pass_popup_target(frame,captions[:1]))
        frame[330:350,820:1950]=0
        self.assertIsNone(pass_popup_target(frame,captions))

    def test_dynamic_card_requires_all_four_thick_edges(self):
        frame=np.zeros((1240,2772,3),np.uint8)
        x,y,w,h=620,180,330,460
        frame[y:y+8,x:x+w]=220;frame[y+h-8:y+h,x:x+w]=220
        frame[y:y+h,x:x+8]=220;frame[y:y+h,x+w-8:x+w]=220
        self.assertEqual([x,y,w,h],first_deck_target(frame,500))
        frame[y:y+h,x:x+10]=0
        self.assertIsNone(first_deck_target(frame,500))

    def test_popup_point_tracks_fractional_aspects(self):
        for width,height in ((1920,1080),(2600,1200),(2772,1240),(2733,1200)):
            box=popup_target((height,width,3),[text('入伍任务'),text('完成所有入伍任务！')])
            self.assertAlmostEqual(width/2,box[0]+box[2]/2)
            self.assertEqual(round(height*665/720),box[1]+box[3]/2)

    def test_title_alone_or_double_word_cannot_authorize(self):
        for items in ([text('加倍')],[text('入伍任务')],[text('完成所有入伍任务！')]):
            self.assertIsNone(popup_target((1240,2772,3),items))

    def test_low_confidence_subtitle_cannot_authorize(self):
        self.assertIsNone(popup_target((1240,2772,3),[text('入伍任务'),text('完成所有入伍任务！',.92)]))

    def test_original_pixel_target_and_text_overlap(self):
        items=[text('入伍任务'),text('完成所有入伍任务！')]
        self.assertEqual([1365.5,1124.5,41,41],popup_target((1240,2772,3),items))
        items.append(text('购买',box=[[1360,1120],[1420,1120],[1420,1168],[1360,1168]]))
        self.assertIsNone(popup_target((1240,2772,3),items))

    def test_popup_dismissal_needs_two_new_confirmed_frames(self):
        flow=MenuFlow('casual',0)
        popup={'state':'blocking_popup','targets':{'menu_dismiss_blocking_popup':[1365.5,1124.5,41,41]}}
        self.assertIn('wait',flow.observe(popup,1,500))
        self.assertEqual('menu_dismiss_blocking_popup',flow.observe(popup,2,1000)['action'])
        flow.accepted('menu_dismiss_blocking_popup',1000)
        self.assertIn('wait',flow.observe(popup,3,1500))
        home={'state':'home','targets':{'menu_home_start':[30,100,70,80]}}
        self.assertIn('wait',flow.observe(home,4,2000))
        self.assertEqual('menu_home_start',flow.observe(home,5,2500)['action'])

    def test_unknown_is_not_popup_disappearance(self):
        flow=MenuFlow('casual',0);flow.accepted('menu_dismiss_blocking_popup',500)
        for frame_id in range(2,10):
            self.assertIn('wait',flow.observe({'state':'unknown'},frame_id,frame_id*500))
        self.assertIsNotNone(flow.pending)


def self_check():
    output=io.StringIO()
    result=unittest.TextTestRunner(stream=output,verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(NativeMenuTests))
    return json.dumps({'passed':result.wasSuccessful(),'tests_run':result.testsRun,
                      'device_inputs':0,'details':output.getvalue()})


if __name__=='__main__':unittest.main()
