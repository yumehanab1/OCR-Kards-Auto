"""Reward cleanup uses scoped menu OCR; unrelated text stays unavailable."""
import json,time
from pathlib import Path
import cv2,numpy as np
from .menu import NativeMenuRecognizer

def run(source,assets,menu_source):
    class ScopedOnly:
        calls=0
        def recognizeNativeText(self,request):
            packet=json.loads(request)
            assert packet['ocr_scope']=='menu_controls'
            self.calls+=1
            return json.dumps(dict(packet,ok=True,scope='menu_controls',items=[],
                width=packet['source_width'],height=packet['source_height']))
    frame=cv2.imdecode(np.frombuffer(Path(source).read_bytes(),np.uint8),1)
    bridge=ScopedOnly();recognizer=NativeMenuRecognizer(assets,bridge,settlement=True)
    def observe(image):
        return recognizer.observe(image,dict(coordinate_space='source_pixels',source_height=image.shape[0],source_width=image.shape[1],
            frame_id=bridge.calls+1,captured_elapsed_ms=0,foreground_generation=1,png_path='saved-settlement.png'))
    started=time.perf_counter();seen=observe(frame);elapsed=(time.perf_counter()-started)*1000
    assert seen['state']=='unknown' and not seen['targets'],seen
    assert seen['ocr_metrics']['scope']=='menu_controls'
    menu=cv2.imdecode(np.frombuffer(Path(menu_source).read_bytes(),np.uint8),1)
    returned=observe(menu)
    assert returned['state']=='deck_ready' and returned['selected_mode']=='ranked',returned
    black=observe(np.zeros_like(frame))
    assert black['state']=='unknown' and not black['targets']
    return json.dumps(dict(passed=True,scope='saved_real_reward_lossy_replay_not_new_live_return',unknown_has_no_target=True,
                           full_page_ocr_calls=0,known_menu_state=returned['state'],elapsed_ms=elapsed,device_inputs=0,captures=0))
