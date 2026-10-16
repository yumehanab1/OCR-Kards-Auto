"""Turn-region capture identity and 1.8x coordinate restoration, without input."""
import json
import numpy as np
from .ocr_bridge import NativeOCR
from .onnx_ocr import OriginalModelOCR


def run():
    checks=[]
    def check(name,valid):
        if not valid:raise AssertionError(name)
        checks.append(name)
    frame=np.zeros((720,1280,3),np.uint8)
    regions=[[768,230,512,432]]
    packet=dict(frame_id=17,captured_elapsed_ms=1000,foreground_generation=5,
                source_width=2304,source_height=1296,coordinate_space='source_pixels',png_path='/current.png')
    label=dict(box=[[2025,864],[2142,864],[2142,900],[2025,900]],text='结束回合',score=.97,score_available=True)
    class Bridge:
        def __init__(self,changes=None):self.changes=changes or {};self.requests=[]
        def recognizeNativeText(self,encoded):
            request=json.loads(encoded);self.requests.append(request)
            reply=dict(request,ok=True,scope=request['ocr_scope'],width=2304,height=1296,items=[label])
            reply.update(self.changes)
            return json.dumps(reply)
    bridge=Bridge();native=NativeOCR(bridge);native.bind(packet)
    found,_=native.regions(frame,regions,scope='turn_controls')
    check('explicit_backend_capability',native.supports_turn_controls and OriginalModelOCR.supports_turn_controls)
    check('single_turn_scope_uses_exact_capture',bridge.requests[0]['ocr_scope']=='turn_controls'
          and all(bridge.requests[0][key]==value for key,value in packet.items()))
    check('one_point_eight_roi_restored_to_source',bridge.requests[0]['ocr_regions']==[[1382,414,922,778]])
    check('source_ocr_boxes_restored_to_recognition_pixels',np.allclose(found[0][0],np.asarray(label['box'])/1.8)
          and found[0][1:] == ('结束回合',.97))
    native.bind(dict(packet,frame_id=18,captured_elapsed_ms=1500,png_path='/next.png'))
    native.regions(frame,regions,scope='turn_controls')
    check('identical_pixels_still_request_current_scoped_capture',len(bridge.requests)==2
          and bridge.requests[1]['frame_id']==18)
    for key,value in (('frame_id',0),('captured_elapsed_ms',0),('foreground_generation',0),
                      ('source_width',1280),('source_height',720),('png_path','/old.png'),
                      ('scope','result_controls'),('coordinate_space','normalized'),('width',1280)):
        native=NativeOCR(Bridge({key:value}));native.bind(packet)
        try:native.regions(frame,regions,scope='turn_controls');refused=False
        except ValueError:refused=True
        check('mismatched_'+key+'_rejected',refused)
    for boxes in ([],regions*2):
        native=NativeOCR(Bridge());native.bind(packet)
        try:native.regions(frame,boxes,scope='turn_controls');refused=False
        except ValueError:refused=True
        check('native_turn_count_'+str(len(boxes))+'_rejected',refused)
    original=object.__new__(OriginalModelOCR)
    seen=[]
    def local_engine(crop):
        seen.append(crop.shape)
        return [([[4,5],[34,5],[34,15],[4,15]],'结束回合',.96)],[.01,.02,.03]
    original.region_engine=local_engine
    found,timing=original.regions(frame,regions,scope='turn_controls')
    check('original_model_crops_only_current_roi',seen==[(432,512,3)])
    check('local_model_boxes_translated_to_supplied_frame',found[0][0]==[[772,235],[802,235],[802,245],[772,245]])
    check('local_model_timing_preserved',np.allclose(timing,[.01,.02,.03]))
    for boxes in ([],regions*2):
        try:original.regions(frame,boxes,scope='turn_controls');refused=False
        except ValueError:refused=True
        check('original_turn_count_'+str(len(boxes))+'_rejected',refused)
    try:original.regions(frame,[[768,230,513,432]],scope='turn_controls');refused=False
    except ValueError:refused=True
    check('original_roi_outside_frame_rejected',refused)
    return dict(passed=True,checks=checks,scope='generated_turn_controls_backend',device_inputs=0,captures=0)


if __name__=='__main__':print(json.dumps(run(),ensure_ascii=True))
