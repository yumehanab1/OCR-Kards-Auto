"""Real 4:3 deck rail regression; geometry only proposes current OCR."""
import json
from pathlib import Path
import unittest
from unittest import mock
import cv2
import numpy as np
from .menu import NativeMenuRecognizer, deck_regions, menu_from_text
from .recognition_scale import shrink


class TabletDeckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parents[6]
        cls.assets=root/'android-app/app/src/main/assets/match-entry'
        evidence=root/'repro/tablet180_20261117'
        cls.frame,_=shrink(cv2.imread(str(evidence/'tablet35-deck-list.png')))
        cls.items=json.loads((evidence/'tablet35-deck-list-ocr.json').read_text('utf8'))

    def test_full_rail_and_real_card(self):
        rs=deck_regions(self.frame)
        self.assertEqual(2,len(rs))
        self.assertGreater(rs[0][0]+rs[0][2],374)  # old crop cut both labels
        result=menu_from_text(self.frame,self.items)
        self.assertEqual('deck_list',result['state'])
        self.assertEqual([486,118,177,248],result['targets']['menu_select_deck'])

    def test_border_alone_or_missing_label_cannot_authorize(self):
        self.assertIsNone(menu_from_text(self.frame,[]))
        self.assertIsNone(menu_from_text(self.frame,[r for r in self.items if r['text']!='对战模式']))
        self.assertEqual([],deck_regions(np.zeros_like(self.frame)))

    def test_early_regions_before_expensive_template_search(self):
        rows=self.items
        class Bridge:
            def recognizeNativeText(self,request):
                p=json.loads(request)
                assert p['ocr_scope']=='menu_controls'
                return json.dumps(dict(p,ok=True,scope='menu_controls',width=960,height=720,
                    items=[dict(r,score_available=True) for r in rows]))
        recognizer=NativeMenuRecognizer(self.assets,Bridge(),startup=True)
        packet=dict(source_width=960,source_height=720,coordinate_space='source_pixels',
                    frame_id=1,captured_elapsed_ms=100,foreground_generation=1,png_path='current.png')
        with mock.patch.object(recognizer.detector,'match',side_effect=AssertionError('broad scan')):
            result=recognizer.observe(self.frame,packet)
        self.assertEqual('deck_list',result['state'])

    def test_settlement_uses_same_fresh_deck_proof_before_broad_search(self):
        rows=self.items
        class Bridge:
            def recognizeNativeText(self,request):
                p=json.loads(request)
                self.request=p
                return json.dumps(dict(p,ok=True,scope='menu_controls',width=960,height=720,
                    items=[dict(r,score_available=True) for r in rows]))
        bridge=Bridge()
        recognizer=NativeMenuRecognizer(self.assets,bridge,settlement=True)
        packet=dict(source_width=960,source_height=720,coordinate_space='source_pixels',
                    frame_id=193,captured_elapsed_ms=100,foreground_generation=7,png_path='current.png')
        with mock.patch.object(recognizer.detector,'match',side_effect=AssertionError('broad scan')):
            result=recognizer.observe(self.frame,packet)
        self.assertEqual('deck_list',result['state'])
        self.assertEqual(193,bridge.request['frame_id'])
        self.assertGreater(bridge.request['ocr_regions'][0][0]+bridge.request['ocr_regions'][0][2],374)

    def test_low_confidence_and_duplicate_label_rejected(self):
        self.assertIsNone(menu_from_text(self.frame,[dict(r,score=.89) for r in self.items]))
        label=next(r for r in self.items if r['text']=='对战模式')
        self.assertIsNone(menu_from_text(self.frame,self.items+[label]))


if __name__=='__main__':unittest.main()
