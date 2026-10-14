"""Raw-plate/type/field contracts, fixed-grid conflicts and owner lifecycle.

Actual original-PNG recognition is separately replayed with the frozen core.
These tests create BGR components but stub the glyph/type proof where needed
to isolate an admission boundary. They do not claim pixel generalization.
"""
from types import SimpleNamespace
import sys
import unittest
from unittest import mock
import cv2
import numpy as np
import apk_green_stat as green


class GreenStatTests(unittest.TestCase):
    def setUp(self):
        self.box = (450, 549, 28, 30)
        self.type_box = (484, 550, 28, 29)
        self.original_boxes = [self.type_box]
        self.original = mock.Mock(side_effect=lambda *a: list(self.original_boxes))
        self.board = SimpleNamespace(FIELD=(200, 415, 1120, 595), STAT_DARK_V=90,
                STAT_SIZE=(22, 36), STAT_BRIGHT_V=150, STAT_BRIGHT_MIN=25,
                stat_boxes=self.original, _type_stat_plate=mock.Mock(return_value=True))
        self.frame = np.full((720, 1280, 3), 170, np.uint8)
        self.paint(self.box, green_ink=True)
        self.paint(self.type_box, green_ink=False)
        self.bank = SimpleNamespace(build_templates=lambda: {})
        self.patcher = mock.patch.dict(sys.modules, {"kredits_templates": self.bank})
        self.patcher.start(); self.addCleanup(self.patcher.stop)
        self.adapter = green.install(self.board)
        self.info = dict(zip(green.FIELDS,(1,1000,2,1920,1080)))
        self.addCleanup(self.adapter.uninstall)

    def paint(self, box, green_ink=True):
        x, y, w, h = box
        self.frame[y:y+h, x:x+w] = 20
        cv2.putText(self.frame, "3" if green_ink else "T", (x+6,y+h-6), cv2.FONT_HERSHEY_SIMPLEX,
                    .65, (0,160,0) if green_ink else (210,210,210), 2, cv2.LINE_8)

    def recovered(self, field=None):
        with mock.patch.object(green, "_residual_digit", return_value=True):
            return self.board.stat_boxes(self.frame, field)

    def test_raw_complete_component_and_unique_original_type_required(self):
        self.assertIn(self.box, self.recovered())
        self.board._type_stat_plate.return_value = False
        self.assertNotIn(self.box, self.recovered())

    def test_original_accepted_digit_does_not_call_new_proof(self):
        self.original_boxes.append(self.box)
        with mock.patch.object(green, "_residual_digit", side_effect=AssertionError("original path")):
            self.assertEqual(self.board.stat_boxes(self.frame), self.original_boxes)

    def test_missing_digit_proof_keeps_original_boxes(self):
        with mock.patch.object(green, "_residual_digit", return_value=False):
            self.assertEqual(self.board.stat_boxes(self.frame), self.original_boxes)

    def test_two_adjacent_type_proofs_reject(self):
        other = (416, 550, 28, 29); self.paint(other, False); self.original_boxes.append(other)
        self.assertNotIn(self.box, self.recovered())

    def test_without_raw_dark_component_no_recovery(self):
        self.frame[:] = 170
        self.assertNotIn(self.box, self.recovered())

    def test_non_support_field_does_not_call_new_proof(self):
        with mock.patch.object(green, "_residual_digit", side_effect=AssertionError("non-support")):
            self.assertEqual(self.board.stat_boxes(self.frame, (200,40,1120,400)), self.original_boxes)

    def test_raw_plate_outside_support_band_rejects(self):
        self.frame[:] = 170; self.paint((450, 529, 28,30)); self.paint(self.type_box, False)
        self.assertNotIn((450,529,28,30), self.recovered())

    def test_component_size_and_fill_cannot_be_bypassed(self):
        self.frame[:] = 170; self.paint((450,549,37,30)); self.paint(self.type_box, False)
        self.assertNotIn((450,549,37,30), self.recovered())
        self.frame[:] = 170
        x,y,w,h=self.box
        cv2.rectangle(self.frame, (x,y), (x+w-1,y+h-1), (20,20,20), 1)
        self.paint(self.type_box, False)
        self.assertNotIn(self.box, self.recovered())

    def test_field_clip_and_donor_boundary_rejects(self):
        for field in ((450,548,550,585),(451,548,550,585),(449,549,550,585),
                      (449,548,550,579),(449,548,511,585)):
            with self.subTest(field=field):
                self.assertNotIn(self.box, self.recovered(field))

    def test_invalid_field_shape_type_range_never_calls_original(self):
        for field in ((), (1,2,3), (1,2,3,4,5), (0,0,1280.,720), (False,0,1280,720),
                      (-1,0,1280,720), (0,0,1281,720), (0,0,1280,721), (5,0,4,720), "bad"):
            self.original.reset_mock()
            self.assertEqual(self.board.stat_boxes(self.frame,field), [])
            self.original.assert_not_called()

    def test_invalid_frame_has_no_boxes(self):
        for frame in (None, np.zeros((1080,1920,3),np.uint8), self.frame.astype(np.float32), np.zeros((720,1280),np.uint8)):
            self.assertEqual(self.board.stat_boxes(frame), [])

    def test_diagnostics_are_registered_deduplicated_and_detached(self):
        result = self.recovered()
        self.assertEqual(self.adapter.diagnostics()["recovered_plate_count"],0)
        self.adapter.register(self.frame,self.info)
        self.assertEqual(self.recovered(), result)
        self.assertEqual(self.recovered(), result)
        report=self.adapter.diagnostics()
        self.assertEqual(report["recovered_plate_count"],1)
        report["recovered_plate_boxes"].clear()
        self.assertEqual(self.adapter.diagnostics()["recovered_plate_count"],1)
        self.adapter.register(self.frame.copy(),dict(self.info,frame_id=2))
        self.assertEqual(self.adapter.diagnostics()["recovered_plate_count"],0)
        self.assertEqual(self.recovered(),result)
        self.assertEqual(self.adapter.diagnostics()["recovered_plate_count"],0)

    def test_diagnostic_bound_never_enters_pixel_decision(self):
        self.adapter.register(self.frame,self.info)
        for n in range(green.DIAGNOSTIC_LIMIT+3):
            self.adapter._remember(self.frame,(n,550,28,29))
        self.assertEqual(self.adapter.diagnostics()["recovered_plate_count"],green.DIAGNOSTIC_LIMIT)
        self.assertTrue(self.adapter.diagnostics()["truncated"])
        self.assertIn(self.box,self.recovered())

    def test_registered_metadata_copy_hash_and_mutation_taint(self):
        self.adapter.register(self.frame,self.info)
        self.info['frame_id']=99
        self.recovered()
        report=self.adapter.diagnostics()
        self.assertEqual(report['frame_id'],1)
        self.assertEqual(report['source_hash'],green._pixel_hash(self.frame))
        self.assertTrue(report['registered_frame_consistent'])
        report['capture']['frame_id']=999
        self.assertEqual(self.adapter.diagnostics()['frame_id'],1)
        self.frame[0,0]=0
        self.assertFalse(self.adapter.diagnostics()['registered_frame_consistent'])
        self.assertEqual(self.adapter.diagnostics()['recovered_plate_count'],0)
        self.frame[0,0]=170
        self.recovered()
        self.assertFalse(self.adapter.diagnostics()['registered_frame_consistent'])
        self.assertEqual(self.adapter.diagnostics()['recovered_plate_count'],0)

    def test_missing_invalid_registration_cannot_create_diagnostics(self):
        for info in (None,{},dict(self.info,frame_id=True),dict(self.info,source_width=0),dict(self.info,captured_elapsed_ms=-1)):
            self.adapter.register(self.frame,info)
            self.assertIn(self.box,self.recovered())
            self.assertFalse(self.adapter.diagnostics()['registered_frame_consistent'])
            self.assertEqual(self.adapter.diagnostics()['recovered_plate_count'],0)
        self.adapter.clear()
        self.assertIn(self.box,self.recovered())

    def test_repeated_install_uninstalls_prior_owner(self):
        original=self.original; prior=self.adapter
        newest=green.install(self.board); self.addCleanup(newest.uninstall)
        self.assertIs(newest.original,original)
        self.assertIs(self.board.stat_boxes,newest.callback)
        prior.uninstall()
        self.assertIs(self.board.stat_boxes,newest.callback)
        newest.uninstall()
        self.assertIs(self.board.stat_boxes,original)

    def test_uninstall_does_not_overwrite_later_wrapper(self):
        later=lambda *a: []
        self.board.stat_boxes=later
        self.adapter.uninstall()
        self.assertIs(self.board.stat_boxes,later)
        self.assertFalse(hasattr(self.board,green.OWNER_ATTRIBUTE))

    def test_fixed_grid_calls_all_original_offsets(self):
        read={"digit":3,"score":.86,"margin":.12}
        with mock.patch.object(green,"_read_green_digit",return_value=read) as reader, \
                mock.patch.object(cv2,"remap",wraps=cv2.remap) as sampler:
            self.assertTrue(green._residual_digit(self.frame,self.box,{}))
            self.assertEqual(reader.call_count,26)
            self.assertEqual(sampler.call_count,25)
            x,y,w,h=self.box
            got={(float(call.args[1][0,0]-x),float(call.args[2][0,0]-y)) for call in sampler.call_args_list}
            self.assertEqual(got,{(dx,dy) for dx in green.OFFSETS for dy in green.OFFSETS})

    def test_conflicting_high_digits_and_raw_winner_disagreement_reject(self):
        raw={"digit":3,"score":.81,"margin":.2}
        good={"digit":3,"score":.90,"margin":.2}
        other={"digit":4,"score":.90,"margin":.2}
        for samples in ([raw]+[good]*24+[other],[raw]+[other]*25):
            with mock.patch.object(green,"_read_green_digit",side_effect=samples):
                self.assertFalse(green._residual_digit(self.frame,self.box,{}))

    def test_score_and_margin_are_not_relaxed(self):
        raw={"digit":3,"score":.81,"margin":.2}
        for below in ({"digit":3,"score":.859999,"margin":.2}, {"digit":3,"score":.95,"margin":.119999}):
            with mock.patch.object(green,"_read_green_digit",side_effect=[raw]+[below]*25):
                self.assertFalse(green._residual_digit(self.frame,self.box,{}))

    def test_red_mixed_and_empty_ink_reject_before_bank(self):
        x,y,w,h=self.box
        crop=self.frame[y:y+h,x:x+w].copy()
        for mode in ("red","mixed","empty"):
            hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
            ink=(hsv[:,:,1]>=120)&(hsv[:,:,2]>=90)
            if mode=="red":hsv[:,:,0][ink]=0
            elif mode=="mixed":
                yy,xx=np.where(ink);hsv[yy[len(yy)//2],xx[len(xx)//2],0]=0
            else:hsv[:,:,1]=0
            modified=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
            self.assertIsNone(green._read_green_digit(modified,{}))


if __name__ == "__main__":
    unittest.main()
