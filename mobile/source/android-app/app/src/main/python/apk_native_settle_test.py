"""Original-pixel settlement request checks using fake captures and receipts."""
import unittest,json
from unittest import mock
import numpy as np
import apk_settle as settle
from apk_settle_test import SettleThenReturnTests


class NativeSettleTests(SettleThenReturnTests):
    def native_run(self,states,after,reply=None,geometry=True):
        bridge=self.Bridge(states,on_tap_states=after)
        original=bridge.capture
        def capture():
            packet=json.loads(original())
            packet.update(width=2772,height=1240,source_width=2772,source_height=1240,coordinate_space='source_pixels')
            if not geometry:packet['source_width']=1920
            return json.dumps(packet)
        bridge.captureNative=capture
        class Recognizer:
            def __init__(self,*args):pass
            def observe(self,frame,packet):
                observed=json.loads(bridge.observeMenu(json.dumps({'png_path':packet['png_path'],'assets':'saved'})))
                observed['start_control']['bounds']=[100,200,80,60]
                return observed
        if reply is not None:
            def dispatch(request):
                value=reply.pop(0) if isinstance(reply,list) else reply
                bridge.settle_requests.append(json.loads(request))
                if value.get('accepted'):bridge.taps.append(True)
                return json.dumps(value)
            bridge.dispatchSettle=dispatch
        with mock.patch('apk_native.menu.NativeMenuRecognizer',Recognizer),mock.patch(
                'apk_match_entry.read_frame',return_value=(np.zeros((1240,2772,3),np.uint8),'fake_native')):
            report=self._virtual_run(bridge,native=True)
        return report,bridge

    def test_native_bottom_point_preserves_original_geometry(self):
        report,bridge=self.native_run(['result_victory'],['home'])
        self.assertEqual('home',report['final_state'])
        request=bridge.settle_requests[0]
        self.assertEqual('source_pixels',request['coordinate_space'])
        self.assertLess(abs(request['from'][0]-1386),30)
        self.assertLess(abs(request['from'][1]-1240*665/720),30)

    def test_native_return_uses_observed_control_instead_of_fixed_slot(self):
        report,bridge=self.native_run(['result_defeat'],['card_collection','home'])
        self.assertEqual('home',report['final_state'])
        self.assertEqual([140.,230.],bridge.settle_requests[-1]['from'])

    def test_source_size_mismatch_refuses_any_tap(self):
        report,bridge=self.native_run(['result_defeat'],['home'],geometry=False)
        self.assertEqual('settle_capture_failed',report['reason'])
        self.assertEqual([],bridge.settle_requests)

    def test_uncompleted_native_receipt_stops(self):
        report,bridge=self.native_run(['result_defeat'],['home'],reply={'accepted':True,'completed':False})
        self.assertEqual('settle_input_refused',report['reason'])
        self.assertEqual(1,len(bridge.settle_requests))

    def test_expired_unsent_settle_reacquires_before_next_attempt(self):
        report,bridge=self.native_run(['result_defeat'],['home'],reply=[
            {'accepted':False,'completed':False,'reason':'frame_age_expired'},
            {'accepted':True,'completed':True}])
        self.assertEqual('home',report['final_state'])
        self.assertEqual(1,report['clicks'])
        self.assertEqual([1,2],[r['frame_id'] for r in bridge.settle_requests])
        self.assertEqual(2,len(report['dispatch_receipts']))

    def test_expired_settle_rejection_is_bounded(self):
        report,bridge=self.native_run(['result_defeat'],['home'],reply={
            'accepted':False,'completed':False,'reason':'frame_age_expired'})
        self.assertEqual('settle_expired_dispatch_budget',report['reason'])
        self.assertEqual(0,report['clicks'])
        self.assertEqual(3,len(bridge.settle_requests))

    def test_expired_return_reacquires_and_retains_full_receipts(self):
        report,bridge=self.native_run(['result_defeat'],['card_collection','home'],reply=[
            {'accepted':True,'completed':True},
            {'accepted':False,'completed':False,'reason':'frame_age_expired'},
            {'accepted':True,'completed':True}])
        self.assertEqual('home',report['final_state'])
        self.assertEqual(3,len(report['dispatch_receipts']))
        self.assertEqual(len(bridge.settle_requests),len({r['frame_id'] for r in bridge.settle_requests}))

    def test_expiry_word_does_not_allow_uncertain_retry(self):
        for reply in ({'accepted':True,'completed':False,'reason':'frame_age_expired'},
                      {'accepted':False,'reason':'frame_age_expired'}):
            report,bridge=self.native_run(['result_defeat'],['home'],reply=reply)
            self.assertEqual('settle_input_refused',report['reason'])
            self.assertEqual(1,len(bridge.settle_requests))


if __name__=='__main__':unittest.main()
