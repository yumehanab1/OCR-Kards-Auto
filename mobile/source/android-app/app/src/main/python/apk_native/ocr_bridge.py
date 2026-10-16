"""Exact-current-frame bridge to bundled native Chinese OCR."""
import json
import numpy as np
import time
import copy

class NativeOCR:
    supports_turn_controls=True
    def __init__(self,bridge):
        self.bridge=bridge
        self.packet=None
        self.cached_frame=None
        self.cached_items=None
        self.last_metrics={}

    def bind(self,packet):
        self.packet=dict(packet)

    def regions(self,frame,regions,*,scope='opening_controls'):
        if self.packet is None:raise ValueError('native_ocr_without_capture')
        if scope not in ('opening_controls','result_controls','menu_controls','turn_controls'):raise ValueError('native_ocr_region_scope')
        if scope=='turn_controls' and len(regions)!=1:raise ValueError('turn_controls_region_count')
        source=[self.packet['source_height'],self.packet['source_width']]
        if list(frame.shape[:2]) not in (source,[720,round(source[1]*720/source[0])]):
            raise ValueError('native_ocr_geometry_mismatch')
        sx,sy=source[1]/frame.shape[1],source[0]/frame.shape[0]
        request=dict(self.packet,ocr_scope=scope,
                     ocr_regions=[[round(v*(sx if i%2==0 else sy)) for i,v in enumerate(box)] for box in regions])
        started=time.perf_counter()
        result=json.loads(str(self.bridge.recognizeNativeText(json.dumps(request))))
        self.last_metrics=dict(scope=scope,elapsed_ms=(time.perf_counter()-started)*1000,
                               frame_id=self.packet['frame_id'],ok=result.get('ok') is True,
                               reason=result.get('reason'),model_stage_ms=result.get('model_stage_ms'))
        if result.get('ok') is not True:return [],0
        if result.get('scope')!=scope or result.get('coordinate_space')!='source_pixels' or [result.get('height'),result.get('width')]!=source:
            raise ValueError('native_ocr_geometry_mismatch')
        for key in ('frame_id','captured_elapsed_ms','foreground_generation','source_width','source_height','png_path'):
            if result.get(key)!=self.packet.get(key):raise ValueError('native_ocr_capture_mismatch')
        items=[]
        for item in result.get('items',[]):
            if item.get('score_available') is True and isinstance(item.get('score'),(int,float)):
                items.append(((np.asarray(item['box'])/[sx,sy]).tolist(),item['text'],float(item['score'])))
        return items,0

    def __call__(self,frame):
        if self.packet is None:raise ValueError('native_ocr_without_capture')
        if self.packet.get('coordinate_space')!='source_pixels':
            raise ValueError('native_ocr_geometry_mismatch')
        source_shape=[self.packet.get('source_height'),self.packet.get('source_width')]
        recognition_shape=list(frame.shape[:2])
        if recognition_shape!=source_shape and recognition_shape!=[720,round(source_shape[1]*720/source_shape[0])]:
            raise ValueError('native_ocr_geometry_mismatch')
        started=time.perf_counter()
        # Exact source pixels only: a changed overlay, label, animation, or
        # geometry always goes through the current capture's OCR bridge.
        if self.cached_frame is not None and np.array_equal(frame,self.cached_frame):
            self.last_metrics={'cache_hit':True,'elapsed_ms':(time.perf_counter()-started)*1000}
            return copy.deepcopy(self.cached_items),0
        result=json.loads(str(self.bridge.recognizeNativeText(json.dumps(self.packet))))
        self.last_metrics={'cache_hit':False,'elapsed_ms':(time.perf_counter()-started)*1000,
                           'ok':result.get('ok') is True,'reason':result.get('reason'),
                           'model_stage_ms':result.get('model_stage_ms')}
        if result.get('ok') is not True:
            # OCR failure is unavailable observation evidence, never a guessed
            # state and never permission to dispatch using the previous frame.
            return [],0
        if result.get('coordinate_space')!='source_pixels' or [result.get('height'),result.get('width')]!=source_shape:
            raise ValueError('native_ocr_geometry_mismatch')
        for key in ('frame_id','captured_elapsed_ms','foreground_generation','source_width','source_height','png_path'):
            if result.get(key)!=self.packet.get(key):raise ValueError('native_ocr_capture_mismatch')
        items=[]
        rx=recognition_shape[1]/float(source_shape[1]); ry=recognition_shape[0]/float(source_shape[0])
        for item in result.get('items',[]):
            # Never invent confidence when a platform backend omits it.
            if item.get('score_available') is True and isinstance(item.get('score'),(int,float)):
                box=np.asarray(item['box'],dtype=float)
                box[:,0]*=rx; box[:,1]*=ry
                items.append((box.tolist(),item['text'],float(item['score'])))
        self.cached_frame=frame.copy()
        self.cached_items=copy.deepcopy(items)
        return items,0
