"""Saved-image regression of the production observation chain; no device I/O."""
import json,sys,time
from pathlib import Path
import cv2,numpy as np
from .onnx_ocr import OriginalModelOCR,java_inference
from .pipeline import Pipeline,load_banks

def run(directory,core,menu,opening,engine,characters_json):
    sys.path.insert(0,str(Path(core)/'src'))
    # pipeline.combat imports unit_state, therefore core is installed by caller
    # before this module is imported (bootstrap entry below).
    offset=lambda box,distance:json.loads(str(engine.offsetPolygon(json.dumps(np.asarray(box).tolist()),float(distance))))
    ocr=OriginalModelOCR(java_inference(engine),json.loads(str(characters_json)),offset)
    banks=load_banks(core,menu,opening);rows=[];dataset=None;preparations={};current_states={};end_pairs={}
    for item in json.loads((Path(directory)/'manifest.json').read_text(encoding='utf8')):
        if dataset!=item['dataset']:
            pipeline=Pipeline(*banks,ocr);dataset=item['dataset']
        start=time.perf_counter()
        frame=cv2.imdecode(np.fromfile(str(Path(directory)/item['file']),np.uint8),cv2.IMREAD_COLOR)
        if item.get('warm_current_control_bounds'):
            from .recognition_scale import shrink
            small,factors=shrink(frame)
            bounds=[round(v/(factors[0] if i%2==0 else factors[1])) for i,v in enumerate(item['warm_current_control_bounds'])]
            pipeline.page.shape=small.shape;pipeline.page.cache(small,'battle',bounds)
        result=(pipeline.observe_turn_ui(frame) if item.get('turn_ui_only') else pipeline.observe(frame))
        if 'expected_ocr_used' in item and result['page'].get('ocr_used')!=item['expected_ocr_used']:
            raise ValueError('saved_native_ocr_path:'+item['file'])
        if item.get('expected_selected_action') and result['selected_action'].get('action')!=item['expected_selected_action']:
            raise ValueError('saved_native_selected_action:'+item['file'])
        if item.get('expected_observation_scope') and result.get('observation_scope')!=item['expected_observation_scope']:
            raise ValueError('saved_native_observation_scope:'+item['file'])
        if item.get('end_transition_pair'):
            from .turn_ui import opponent_evidence
            from .recognition_scale import shrink,coordinates
            from apk_end_turn_ledger import EndTurnLedger
            small,factors=shrink(frame)
            proof=opponent_evidence(small,coordinates(result['page'],1/factors[0],1/factors[1]),pipeline.page.detector)
            if not proof:raise ValueError('saved_turn_transition_proof:'+item['file'])
            key=item['end_transition_pair']
            if key not in end_pairs:
                ledger=EndTurnLedger(timeout_ms=12000,sample_gap_ms=250,stable_span_ms=500)
                ledger.register(0,0,item['end_transition_source'],item['end_transition_dispatch_ms'],0)
                end_pairs[key]=ledger
            packet=dict(item['end_transition_packet'],**coordinates(proof,*factors))
            outcomes=end_pairs[key].observe(packet,item['end_transition_observed_ms'],0)
            confirmed=bool(outcomes and outcomes[0]['status']=='confirmed')
            if confirmed!=item['expected_end_transition_confirmed']:
                raise ValueError('saved_turn_transition_pair:'+item['file'])
            result['saved_end_transition']=dict(confirmed=confirmed,outcomes=outcomes,device_inputs=0)
        if item.get('current_state_sequence'):
            key=item['current_state_sequence'];prior=current_states.get(key)
            if item.get('expected_current_state_recovery'):
                from .executor import ActionExecutor
                from .turn_ui import end_control
                class ReadOnlyReplayBridge:
                    def elapsedRealtime(self):return 10000
                    def emit(self,value):pass
                executor=ActionExecutor(ReadOnlyReplayBridge(),None,None,directory,100000,20)
                executor.last_end_state_key=prior;executor.same_state_end_attempts=1
                executor.report['hooks'].append({});executor.report['pending_end_turn_inputs']=1
                executor.settle_end([dict(status='unconfirmed',reason='turn_transition_timeout',hook_index=0)])
                h,w=frame.shape[:2]
                resumed=executor.resume_current_state(result,dict(frame_id=len(rows)+1,source_height=h,source_width=w,
                    foreground_generation=1,captured_elapsed_ms=10000),end_control(result['page']) is not None,dict(ready=True))
                if (not resumed or executor.report['end_turns_unconfirmed']!=1 or executor.report['end_turns_confirmed']!=0):
                    raise ValueError('saved_current_state_recovery:'+item['file'])
                result['saved_current_state_recovery']=dict(resumed=True,previous_unknown_retained=True,device_inputs=0)
            current_states[key]=result['current_state_key']
        if 'expected_card_display' in item and result.get('card_display',{}).get('ready')!=item['expected_card_display']:
            raise ValueError('saved_native_card_display:'+item['file'])
        if item.get('expected_deploy_action') and result.get('plan',{}).get('action')!=item['expected_deploy_action']:
            raise ValueError('saved_native_deploy_action:'+item['file'])
        if item.get('expected_selected_action') and result.get('selected_action',{}).get('action')!=item['expected_selected_action']:
            raise ValueError('saved_native_selected_action:'+item['file'])
        if item.get('turn_sequence'):
            from .turn_preparation import TurnPreparation
            gate=preparations.setdefault(item['turn_sequence'],TurnPreparation())
            h,w=frame.shape[:2]
            prep=gate.observe(result,dict(frame_id=len(rows)+1,captured_elapsed_ms=item['turn_sequence_ms'],
                foreground_generation=1,source_height=h,source_width=w))
            if prep['ready']!=item['expected_turn_ready']:
                raise ValueError('saved_native_turn_preparation:'+item['file']+':'+prep['reason'])
            result['saved_turn_preparation']=prep
        if item.get('verify_state') and result['state']!=item['expected_state']:
            raise ValueError('saved_native_state:'+item['file']+':'+result['state'])
        if 'expected_choice' in item and result.get('choice_evidence',{}).get('ready')!=item['expected_choice']:
            raise ValueError('saved_native_choice:'+item['file'])
        if 'expected_choice_modal' in item and result.get('choice_modal')!=item['expected_choice_modal']:
            raise ValueError('saved_native_choice_modal:'+item['file'])
        if item.get('expected_deploy_reason') and result.get('plan',{}).get('reason')!=item['expected_deploy_reason']:
            raise ValueError('saved_native_deploy_reason:'+item['file'])
        if item.get('expected_end_ready'):
            from .end_audit import audit
            check=audit(result,lambda action:True,allow_local_unknown=True)
            if not check['ready']:raise ValueError('saved_native_end_audit:'+item['file']+':'+check['reason'])
            result['saved_end_audit']=check
        if item.get('expected_vacancy') and not result.get('support_probe',{}).get('vacancy_candidate'):
            raise ValueError('saved_native_vacancy:'+item['file'])
        if item.get('expected_frontline') and result.get('scene',{}).get('frontline',{}).get('owner')!=item['expected_frontline']:
            raise ValueError('saved_native_frontline:'+item['file'])
        if item.get('expected_result_proof') and not result['page'].get('result_proof',{}).get('ready'):
            raise ValueError('saved_native_result_proof:'+item['file'])
        result.update(file=item['file'],dataset=dataset,source_sha256=item['sha256'],
                      expected_state=item['expected_state'],elapsed_ms=(time.perf_counter()-start)*1000)
        rows.append(result)
    def encode(value):
        if isinstance(value,np.generic):return value.item()
        if isinstance(value,np.ndarray):return value.tolist()
        raise TypeError(type(value).__name__)
    from .menu import NativeMenuRecognizer
    class SavedBridge:
        def recognizeNativeText(self, request):
            packet=json.loads(request)
            found,_=ocr(self.frame)
            return json.dumps(dict(packet,items=[{'box':np.asarray(b).tolist(),'text':s,
                'score':float(c),'score_available':True} for b,s,c in found or []]))
    menu_rows=[]
    for item in json.loads((Path(directory)/'manifest.json').read_text(encoding='utf8')):
        expected=item.get('expected_menu_state') or {'home':'home','deck_menu':'deck_list','deck_detail':'deck_ready'}.get(item['expected_state'])
        if expected is None:continue
        frame=cv2.imdecode(np.fromfile(str(Path(directory)/item['file']),np.uint8),cv2.IMREAD_COLOR)
        h,w=frame.shape[:2];bridge=SavedBridge();bridge.frame=frame
        packet={'ok':True,'coordinate_space':'source_pixels','width':w,'height':h,'source_width':w,
                'source_height':h,'frame_id':1,'captured_elapsed_ms':0,'foreground_generation':1,'png_path':item['file']}
        started=time.perf_counter()
        observed=NativeMenuRecognizer(menu,bridge).observe(frame,packet)
        if any(name not in observed.get('targets',{}) for name in item.get('expected_menu_targets',[])):
            raise ValueError('saved_native_menu_target:'+item['file'])
        startup=NativeMenuRecognizer(menu,bridge,startup=True).observe(frame,packet)
        startup_expected='unknown' if expected=='login_popup_cleanup' else expected
        if startup['state']!=startup_expected:
            raise ValueError('saved_startup_state:'+item['file']+':'+startup['state'])
        menu_rows.append(dict(file=item['file'],expected_state=expected,observation=observed,
                             startup_observation=startup,
                             elapsed_ms=(time.perf_counter()-started)*1000,passed=observed['state']==expected))
    return json.dumps({'frames':rows,'native_menu_frames':menu_rows,
                      'device_inputs':0,'live_match_verified':False},default=encode,ensure_ascii=False)
