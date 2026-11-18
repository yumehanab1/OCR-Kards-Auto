"""Saved API35 task overlays and current-frame negative authorization cases."""
import json
from pathlib import Path
import unittest
from unittest import mock
import cv2
import numpy as np
from .menu import NativeMenuRecognizer, task_regions, task_popup, login_reward_regions
from .recognition_scale import shrink


class TaskRegionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[6]
        evidence=cls.root/'repro/tablet181_20261117'
        cls.rows=json.loads((evidence/'task-replay181.json').read_text('utf8'))
        cls.frames={r['label']:shrink(cv2.imread(str(evidence/(r['label']+'-task-original.png'))))[0]
                    for r in cls.rows}

    def test_saved_overlay_top_labels_not_daily_footer(self):
        for row in self.rows:
            frame=self.frames[row['label']]
            self.assertIsNone(login_reward_regions(frame))
            self.assertEqual(row['target'],task_popup(frame,row['items']))
            self.assertEqual(row['regions'],task_regions(frame))
            for item in row['items']:
                if item['text']=='入伍任务':
                    self.assertLess(min(p[1] for p in item['box']),frame.shape[0]*.05)

    def test_missing_low_score_or_wrong_semantics_reject(self):
        for row in self.rows:
            frame=self.frames[row['label']];items=row['items']
            self.assertIsNone(task_popup(frame,[]))
            self.assertIsNone(task_popup(frame,[r for r in items if r['text']!='入伍任务']))
            self.assertIsNone(task_popup(frame,[dict(r,score=.929) for r in items]))
            self.assertIsNone(task_popup(frame,[dict(r,text='商店') for r in items]))

    def test_bright_or_occupied_blank_reject(self):
        for row in self.rows:
            frame=self.frames[row['label']].copy();x,y,w,h=map(round,row['target'])
            frame[y:y+h,x:x+w]=255
            self.assertIsNone(task_popup(frame,row['items']))
            occupied=dict(text='领取',score=.99,box=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]])
            self.assertIsNone(task_popup(self.frames[row['label']],row['items']+[occupied]))

    def test_new_frame_must_recheck_not_cached(self):
        row=self.rows[0];frame=self.frames[row['label']];items=list(row['items'])
        class Bridge:
            def recognizeNativeText(self,request):
                p=json.loads(request)
                return json.dumps(dict(p,ok=True,scope='menu_controls',width=frame.shape[1],height=720,
                    items=[dict(r,score_available=True) for r in items]))
        recognizer=NativeMenuRecognizer(self.root/'android-app/app/src/main/assets/match-entry',Bridge(),startup=True)
        packet=dict(source_width=frame.shape[1],source_height=720,coordinate_space='source_pixels',
                    frame_id=1,captured_elapsed_ms=100,foreground_generation=1,png_path='current.png')
        with mock.patch.object(recognizer.detector,'match',side_effect=AssertionError('broad scan')):
            self.assertEqual('blocking_popup',recognizer.observe(frame,packet)['state'])
            items.clear()
            with self.assertRaises(AssertionError):recognizer.observe(frame,dict(packet,frame_id=2))


if __name__=='__main__':unittest.main()
