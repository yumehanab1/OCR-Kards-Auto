"""Native campaign battle loop. Every input uses the existing Java bridge."""
import json,time
from pathlib import Path
from apk_battle_runtime import Stop,Replan,options_from_json,_json
from .pipeline import Pipeline,load_banks
from .ocr_bridge import NativeOCR
from .executor import ActionExecutor

class ResultProof:
    def __init__(self):self.previous=None
    def observe(self,observed,packet):
        state=observed.get('state');page=observed.get('page',{})
        names=('victory_btn',) if state=='result_victory' else ('defeat_banner','defeat_btn') if state=='result_defeat' else ()
        strong=bool(names) and (any(page.get('evidence',{}).get(n,{}).get('score',0)>=.93 for n in names)
                              or page.get('result_proof',{}).get('ready') is True)
        previous=self.previous
        if not strong:
            self.previous=None
            return False
        if previous is None or previous[0]!=state:
            self.previous=(state,dict(packet))
            return False
        prior=previous[1]
        delta=packet['captured_elapsed_ms']-prior['captured_elapsed_ms']
        if (any(packet.get(k)!=prior.get(k) for k in ('source_width','source_height','foreground_generation'))
                or delta<0 or delta>5000):
            self.previous=(state,dict(packet))
            return False
        if packet['frame_id']<=prior['frame_id']:return False
        # Keep the first current proof while captures arrive faster than the
        # minimum separation. Moving this anchor every frame could prevent a
        # valid independent pair forever at a stable sub-300ms capture cadence.
        return delta>=300

def run(bridge,core,menu,opening,evidence,options_json='{}'):
    options=options_from_json(options_json);out=Path(evidence);out.mkdir(parents=True,exist_ok=True)
    started=int(bridge.elapsedRealtime())
    deadline=min(started+int(options['max_seconds']*1000),int(bridge.deadlineElapsedRealtime()))
    executor=None
    report=dict(scope='apk_native_source_pixel_engine',runtime_version=2,options=options,
                read_only=options['read_only'],host_inputs=0,result_verified=False,
                full_game_passed=False,stop_reason=None,exception=None)
    proof=ResultProof();last_progress=started;unknown_since=None;previous_turn=0;modal_since=None;choice_failures=0
    try:
        ocr=NativeOCR(bridge);pipeline=Pipeline(*load_banks(core,menu,opening),ocr)
        executor=ActionExecutor(bridge,pipeline,ocr,evidence,deadline,options['max_inputs'],
                                options['read_only'],options['max_failed_inputs'])
        while True:
            try:observed,packet=executor.take_ready_observation() or executor.capture()
            except Replan as error:
                executor.emit('replan',dict(reason=str(error)))
                if executor.now()-last_progress>=options['idle_seconds']*1000:raise Stop('no_progress_timeout')
                continue
            state=observed['state'];now=executor.now()
            if options['read_only']:raise Stop('inspection_complete')
            if proof.observe(observed,packet):
                report['result_verified']=True;raise Stop(state)
            if observed.get('choice_modal'):
                if state=='battle' and observed.get('choice_evidence',{}).get('ready'):
                    try:effect=executor.execute(observed,packet)
                    except Replan as error:
                        executor.emit('replan',dict(reason=str(error)));continue
                    choice_failures=0 if effect['confirmed'] else choice_failures+1
                    last_progress=executor.now()
                    if choice_failures>=5:raise Stop('three_choice_failed_5_times')
                    continue
                if modal_since is None:modal_since=now
                if now-modal_since>=12000:raise Stop('choice_modal_timeout')
                time.sleep(.6);continue
            modal_since=None;choice_failures=0
            if state in ('battle','opponent_turn','result_victory','result_defeat'):unknown_since=None
            elif unknown_since is None:unknown_since=now
            elif now-unknown_since>=options['unknown_seconds']*1000:raise Stop('unknown_screen_timeout')
            if previous_turn!=executor.turn:previous_turn=executor.turn;last_progress=now
            if executor.end_ledger.pending is None and state=='battle':
                selected=observed['selected_action'].get('action')
                if selected in ('deploy','blind_middle','attack_hq','attack_unit','movefront','end_turn_verified'):
                    if selected in ('deploy','blind_middle') and not options['deploy_enabled']:
                        raise Stop('native_deployment_disabled_not_supported')
                    try:executor.execute(observed,packet);last_progress=executor.now()
                    except Replan as error:executor.emit('replan',dict(reason=str(error)))
                    continue
            if now-last_progress>=options['idle_seconds']*1000:raise Stop('no_progress_timeout')
            # No fixed wait after a confirmed action; only waiting frames pause.
            time.sleep(.18 if state in ('battle','result_victory','result_defeat') else .3)
    except Stop as error:report['stop_reason']=str(error)
    except BaseException as error:
        report.update(stop_reason='runtime_exception',exception=type(error).__name__+': '+str(error))
    finally:
        if executor is not None:
            try:executor.settle_end(executor.end_ledger.finalize(executor.now(),report['stop_reason']))
            except Stop:pass # Keep the primary stop and the ledger's unresolved evidence.
            report.update(executor.report);report['engine_turns_seen']=executor.turn
        report['elapsed_ms']=int(bridge.elapsedRealtime())-started
        report['battle_result_reached']=report['result_verified'] and report['stop_reason'] in ('result_victory','result_defeat')
        (out/'battle-summary.json').write_text(_json(report),encoding='utf8')
        bridge.emit(_json(dict(kind='finished',value=report)))
    return _json(report)
