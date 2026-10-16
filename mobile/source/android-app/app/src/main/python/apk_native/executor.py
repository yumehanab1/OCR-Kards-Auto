"""APK source-pixel action execution through the existing Java dispatch gate."""
import hashlib,json,time
from pathlib import Path
import cv2,numpy as np
from .pipeline import Pipeline,load_banks
from .ocr_bridge import NativeOCR
from .action_request import request
from .action_chain import select
from .effects import sequence_postcondition
from .end_audit import audit,StableAudit,UnknownFrontlineRecheck
from .turn_ui import opponent_evidence,end_control
from .turn_preparation import TurnPreparation
from apk_end_turn_ledger import EndTurnLedger
from apk_battle_runtime import Stop,Replan,_json,_parse

class ActionExecutor:
    def __init__(self,bridge,pipeline,ocr,evidence,deadline,max_inputs,read_only=False,
                 max_failed_inputs=5):
        self.bridge,self.pipeline,self.ocr=bridge,pipeline,ocr
        self.out=Path(evidence).resolve();self.deadline=deadline;self.max_inputs=max_inputs;self.read_only=read_only
        self.last_id=-1;self.last_capture_time=-1;self.foreground_generation=None;self.shape=None
        self.turn=0;self.previous_state=None;self.isolated=[];self.consumed=set()
        self.failed_deploys=0;self.failed_inputs=0;self.max_failed_inputs=max_failed_inputs
        self.last_end_state_key=None;self.same_state_end_attempts=0
        self.ready_observation=None
        self.effect_capture_context=None
        self.turn_preparation=TurnPreparation()
        # Native recognition is expensive on long-screen frames. Keep the
        # independent-frame proof, but bound each transition window so a
        # single unreadable label cannot stall the turn for half a minute.
        self.end_audit=StableAudit()
        self.frontline_recheck=UnknownFrontlineRecheck()
        self.end_ledger=EndTurnLedger(timeout_ms=12000, sample_gap_ms=250, stable_span_ms=500)
        self.report=dict(game_inputs=0,inputs=[],hooks=[],captures=0,actions_confirmed=0,
            unconfirmed_inputs=0,unconfirmed_skipped=0,failed_inputs=0,end_turns_confirmed=0,
            end_turns_unconfirmed=0,pending_end_turn_inputs=0,end_turn_outcomes=[],host_inputs=0,
            max_failed_inputs=max_failed_inputs)

    def now(self):return int(self.bridge.elapsedRealtime())
    def running(self):
        if self.bridge.isCancelled():raise Stop('cancelled')
        if self.now()>=self.deadline:raise Stop('time_budget')
    def emit(self,kind,value):self.bridge.emit(_json(dict(kind=kind,value=value)))

    def resume_current_state(self,observed,packet,own_proof,preparation):
        if observed.get('planning_complete') is False:return False
        if (own_proof and preparation['ready'] and self.end_ledger.pending is None
                and self.last_end_state_key is not None
                and observed.get('current_state_key') is not None
                and observed['current_state_key']!=self.last_end_state_key):
            self.turn+=1;self.isolated.clear();self.failed_deploys=0;self.failed_inputs=0
            self.report['failed_inputs']=0
            self.last_end_state_key=None;self.same_state_end_attempts=0
            self.emit('current_state_resumed',dict(frame_id=packet['frame_id'],planning_epoch=self.turn,
                reason='current_own_state_changed_after_completed_end',previous_end_success_inferred=False))
            return True
        return False

    def take_ready_observation(self):
        """Reuse the last independent postcondition frame for one fresh action."""
        queued=self.ready_observation;self.ready_observation=None
        if queued is None:return None
        self.running();observed,packet=queued
        if (observed.get('state')!='battle' or observed.get('choice_modal')
                or observed.get('card_display',{}).get('ready')):
            self.frontline_recheck.reset();return None
        if (self.end_ledger.pending is not None or packet['frame_id'] in self.consumed
                or not 0<=self.now()-packet['captured_elapsed_ms']<=3000):
            self.frontline_recheck.reset();return None
        if (packet['frame_id']!=self.last_id or packet['captured_elapsed_ms']!=self.last_capture_time
                or packet['foreground_generation']!=self.foreground_generation
                or self.shape!=(packet['source_height'],packet['source_width'],3)):
            self.frontline_recheck.reset();return None
        if self.is_effect_partial(observed):
            observed=self.complete_effect_planning(observed,packet)
            if observed is None:
                self.frontline_recheck.reset();return None
            own_proof=end_control(observed['page']) is not None
            self.observe_turn_state(own_proof,observed.get('turn_transition_proof'))
            preparation=self.turn_preparation.observe(observed,packet)
            observed['turn_preparation']=preparation
            self.resume_current_state(observed,packet,own_proof,preparation)
            observed['planning_turn']=self.turn
            record_file='native-planning-%06d.json'%packet['frame_id']
            (self.out/record_file).write_text(_json(dict(packet=packet,observation=observed,
                planning_turn=self.turn)),encoding='utf8')
            self.emit('effect_planning_completed',dict(frame_id=packet['frame_id'],
                completion_elapsed_ms=observed['capture_timings_ms']['planning_completion'],
                age_ms=self.now()-packet['captured_elapsed_ms'],record_file=record_file,
                turn=self.turn,planning_turn=self.turn))
        if (observed.get('planning_complete') is False
                or observed.get('turn_preparation',{}).get('ready') is False):
            self.frontline_recheck.reset();return None
        entry=dict(state=observed['state'],scene=observed.get('scene'),
                   plan=observed.get('plan',{}),combat=observed.get('combat'))
        selected=select(entry,allow=self.allow)
        observed=dict(observed,selected_action=selected)
        if selected.get('action')=='end_turn_candidate':
            # The post-input frame already contains a complete planning scan.
            # Re-audit with updated actor isolation and failed-deploy counts,
            # without pretending this same frame is a new preparation sample.
            if not self.audit_end_candidate(observed,packet):return None
        else:
            self.frontline_recheck.reset()
            if selected.get('action') not in ('deploy','blind_middle','attack_hq','attack_unit','movefront'):return None
        (self.out/('native-replanned-%06d.json'%packet['frame_id'])).write_text(
            _json(dict(packet=packet,observation=observed)),encoding='utf8')
        self.emit('postcondition_frame_reused',dict(frame_id=packet['frame_id'],
                  age_ms=self.now()-packet['captured_elapsed_ms'],action=observed['selected_action']['action']))
        return observed,packet

    @staticmethod
    def is_effect_partial(observed):
        return (observed.get('planning_complete') is False
                and str(observed.get('observation_scope','')).startswith('effect_'))

    def complete_effect_planning(self,observed,packet):
        """Complete the exact current original, never an abbreviated empty hand."""
        complete=getattr(self.pipeline,'complete_planning',None)
        source=observed.get('source') or {}
        started=self.now()
        def skipped(reason):
            self.emit('postcondition_frame_reuse_skipped',dict(frame_id=packet['frame_id'],reason=reason,
                elapsed_ms=self.now()-started))
            return None
        if not callable(complete):return skipped('effect_planning_api_missing')
        if (source.get('frame_id')!=packet['frame_id'] or source.get('elapsed_ms')!=packet['captured_elapsed_ms']
                or source.get('shape')!=[packet['source_height'],packet['source_width'],3]):
            return skipped('effect_planning_source_metadata_mismatch')
        try:
            path=Path(source['path']).resolve()
            if self.out not in path.parents or path!=Path(packet['png_path']).resolve():
                return skipped('effect_planning_source_path_mismatch')
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=source.get('sha256'):
                return skipped('effect_planning_source_hash_mismatch')
            frame=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
            if frame is None or list(frame.shape)!=source['shape']:
                return skipped('effect_planning_source_geometry_mismatch')
        except (KeyError,OSError,ValueError):return skipped('effect_planning_source_unavailable')
        self.running()
        if not 0<=self.now()-packet['captured_elapsed_ms']<=3000:
            return skipped('effect_planning_frame_expired_before_completion')
        self.ocr.bind(packet)
        try:full=complete(frame,observed)
        except ValueError as error:return skipped(str(error))
        self.running()
        if not 0<=self.now()-packet['captured_elapsed_ms']<=3000:
            return skipped('effect_planning_frame_expired_after_completion')
        if (full.get('planning_complete') is not True or full.get('hand_scanned') is not True
                or full.get('combat_scanned') is not True or not isinstance(full.get('hand'),list)
                or not isinstance(full.get('scene'),dict) or not isinstance(full.get('combat'),dict)
                or not isinstance(full.get('support_probe'),dict) or full.get('current_state_key') is None
                or full.get('state')!='battle' or full.get('choice_modal')
                or full.get('card_display',{}).get('ready')
                or full.get('source_shape')!=source['shape']):
            return skipped('effect_planning_completion_incomplete')
        full['source']=source
        full['turn_transition_proof']=observed.get('turn_transition_proof')
        full['capture_timings_ms']=dict(observed.get('capture_timings_ms') or {},
            planning_completion=self.now()-started)
        return full

    def capture_effect(self,context):
        # Keep capture()'s no-argument contract for older/fake pipelines and
        # instrumented capture providers. Partial data requires both APIs.
        if (context not in ('deploy','move_front','attack_unit')
                or not callable(getattr(self.pipeline,'observe_effect',None))
                or not callable(getattr(self.pipeline,'complete_planning',None))):
            return self.capture()
        previous=self.effect_capture_context;self.effect_capture_context=context
        try:return self.capture()
        finally:self.effect_capture_context=previous

    def audit_end_candidate(self,observed,packet):
        if observed.get('planning_complete') is False:
            self.frontline_recheck.reset();return False
        evidence=audit(observed,self.allow,self.failed_deploys,allow_local_unknown=True)
        evidence=self.frontline_recheck.observe(evidence,packet,self.turn,self.now())
        observed['end_turn_audit']=evidence
        self.emit('end_turn_audit',dict(frame_id=packet['frame_id'],turn=self.turn,**evidence))
        if not evidence['ready']:return False
        evidence['frame_id']=packet['frame_id']
        if not evidence.get('unresolved_frontline_skipped'):evidence['current_frame_exhausted']=True
        observed['selected_action']=dict(action='end_turn_verified',end_turn_evidence=evidence)
        return True

    def observe_end_state(self,observed,packet,turn_proof,own_proof,preparation):
        if self.end_ledger.pending is None:return
        self.settle_end(self.end_ledger.observe(dict(packet,**(turn_proof or {})),self.now(),self.turn))
        # A settled current own state must not await missing historical frames.
        if self.end_ledger.pending is not None and own_proof and preparation['ready']:
            self.settle_end(self.end_ledger._finish('unconfirmed',
                'current_own_state_ready_without_transition_proof',self.now()))
            self.resume_current_state(observed,packet,own_proof,preparation)

    def observe_turn_state(self,own_proof,turn_proof):
        if own_proof and self.previous_state=='opponent_turn':
            self.turn+=1;self.isolated.clear();self.failed_deploys=0
            self.failed_inputs=0;self.report['failed_inputs']=0
            self.last_end_state_key=None;self.same_state_end_attempts=0
        if own_proof:self.previous_state='battle'
        elif turn_proof:self.previous_state='opponent_turn'

    def capture(self):
        self.running();capture_started=self.now();packet=_parse(self.bridge.captureNative())
        bridge_finished=self.now()
        if packet.get('ok') is not True:raise Stop('capture_rejected:'+str(packet.get('reason')))
        path=Path(packet['png_path']).resolve()
        if self.out not in path.parents:raise Stop('capture_outside_session_evidence')
        raw=path.read_bytes();frame=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
        if (packet.get('coordinate_space')!='source_pixels' or frame is None
                or frame.shape!=(packet['source_height'],packet['source_width'],3)
                or packet.get('width')!=packet['source_width'] or packet.get('height')!=packet['source_height']):
            raise Stop('invalid_native_capture_geometry')
        if self.shape is not None and self.shape!=frame.shape:raise Stop('native_capture_geometry_changed')
        captured=packet['captured_elapsed_ms'];index=packet['frame_id']
        if index<=self.last_id or captured<=self.last_capture_time or self.now()<captured:
            raise Stop('invalid_capture_packet_sequence')
        generation=packet['foreground_generation']
        if self.foreground_generation is not None and generation!=self.foreground_generation:raise Stop('foreground_changed')
        self.last_id=index;self.last_capture_time=captured;self.shape=frame.shape;self.foreground_generation=generation
        if self.now()-captured>3000:raise Replan('native_capture_frame_expired')
        self.ocr.bind(packet)
        if self.effect_capture_context is not None:
            observed=self.pipeline.observe_effect(frame,self.effect_capture_context)
            # State transitions keep their original full processing, including
            # independent turn/result proof and draw/choice interruption.
            if (self.is_effect_partial(observed) and (observed['state']!='battle'
                    or observed.get('choice_modal') or observed.get('card_display',{}).get('ready'))):
                try:observed=self.pipeline.complete_planning(frame,observed)
                except ValueError as error:raise Replan(str(error))
                if observed.get('planning_complete') is not True:raise Replan('effect_transition_planning_incomplete')
        else:
            observer=(self.pipeline.observe_turn_ui if self.end_ledger.pending is not None
                      or self.previous_state=='opponent_turn' else self.pipeline.observe)
            observed=observer(frame)
        self.running()
        source=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),shape=list(frame.shape),frame_id=index,elapsed_ms=captured)
        observed['source']=source;self.report['captures']+=1
        observed['capture_timings_ms']=dict(bridge=bridge_finished-capture_started,
            decode_and_recognition=self.now()-bridge_finished,total=self.now()-capture_started)
        if self.now()-captured>3000:
            self.emit('observation_expired',dict(frame_id=index,age_ms=self.now()-captured,
                state=observed['state'],timings_ms=observed.get('timings_ms'),
                capture_timings_ms=observed['capture_timings_ms']))
            raise Replan('native_observation_frame_expired')
        from .recognition_scale import shrink,coordinates
        proof_frame,factors=shrink(frame)
        proof_page=coordinates(observed['page'],1/factors[0],1/factors[1])
        turn_proof=(opponent_evidence(proof_frame,proof_page,self.pipeline.page.detector)
                    if observed['state']=='opponent_turn' and not observed.get('choice_modal') else None)
        if turn_proof:turn_proof=coordinates(turn_proof,*factors)
        observed['turn_transition_proof']=turn_proof
        if self.is_effect_partial(observed):
            # Missing hand/combat data is neither an empty hand nor a complete
            # preparation sample. Only the effect detector consumes this frame.
            observed['selected_action']=dict(action='wait',reason='effect_planning_incomplete')
            self.record_observation(observed,packet)
            return observed,packet
        own_proof=observed['state']=='battle' and not observed.get('choice_modal') and end_control(observed['page']) is not None
        self.observe_turn_state(own_proof,turn_proof)
        entry=dict(state=observed['state'],scene=observed.get('scene'),plan=observed.get('plan',{}),combat=observed.get('combat'))
        observed['selected_action']=select(entry,allow=self.allow)
        preparation=self.turn_preparation.observe(observed,packet)
        observed['turn_preparation']=preparation
        # A fast opponent can pass entirely between captures. A fresh own
        # state remains actionable without reconstructing that missing phase.
        # Changed resources/hand reset local retries; old end outcomes stay
        # unconfirmed. This is a planning epoch, not retrospective success.
        self.resume_current_state(observed,packet,own_proof,preparation)
        if observed['state']=='battle' and not preparation['ready']:
            observed['selected_action']=dict(action='wait',reason=preparation['reason'])
        if observed['state']=='battle' and observed.get('choice_evidence',{}).get('ready'):
            observed['selected_action']={'action':'choice_middle'}
        if self.end_ledger.pending is not None:
            self.frontline_recheck.reset()
            self.observe_end_state(observed,packet,turn_proof,own_proof,preparation)
        elif observed['selected_action'].get('action')=='end_turn_candidate':
            # User-approved single explicit control; unrelated missing action
            # plates are local skips, not a whole-turn completeness gate.
            self.audit_end_candidate(observed,packet)
        else:
            self.end_audit.previous=None
            self.frontline_recheck.reset()
        self.record_observation(observed,packet)
        return observed,packet

    def record_observation(self,observed,packet):
        (self.out/('native-observation-%06d.json'%packet['frame_id'])).write_text(_json(dict(packet=packet,observation=observed)),encoding='utf8')
        self.emit('native_observation',dict(state=observed['state'],frame_id=packet['frame_id'],turn=self.turn,
            observation_scope=observed.get('observation_scope'),planning_complete=observed.get('planning_complete',True),
            timings_ms=observed.get('timings_ms'),capture_timings_ms=observed['capture_timings_ms']))

    def settle_end(self,outcomes):
        for outcome in outcomes:
            confirmed=outcome['status']=='confirmed'
            hook=self.report['hooks'][outcome['hook_index']]
            hook.update(final_verification=outcome['status'],detail=outcome['reason'],end_turn_outcome=outcome)
            self.report['end_turn_outcomes'].append(outcome)
            self.report['pending_end_turn_inputs']-=1
            self.report['end_turns_confirmed']+=int(confirmed)
            self.report['end_turns_unconfirmed']+=int(not confirmed)
            self.emit('end_turn_outcome',outcome)
            if confirmed:
                self.failed_inputs = 0
                self.report['failed_inputs'] = 0
                self.last_end_state_key=None;self.same_state_end_attempts=0
            if not confirmed:
                self.failed_inputs += 1
                self.report['failed_inputs'] = self.failed_inputs
                # An unknown postcondition alone must not freeze future own
                # states. Identical-state retries are bounded at dispatch.

    @staticmethod
    def identity(action):
        kind=action.get('action') or action.get('kind')
        if kind in ('deploy','blind_middle'):return 'deploy',action.get('grab_source')
        plan=action.get('combat_plan') or action
        actor=(plan.get('unit') or {}).get('card') or plan.get('unit') or {}
        return kind,[actor.get('cx'),actor.get('cy')]
    def allow(self,action):
        kind,point=self.identity(action)
        if kind=='deploy' and self.failed_deploys>=2:return False
        if point is None or any(v is None for v in point):return False
        return not any(kind==old_kind and max(abs(a-b) for a,b in zip(point,old_point))<=self.shape[0]*12/720
                       for old_kind,old_point in self.isolated)

    def execute(self,observed,packet):
        # Every original consumed by sequence_postcondition stays pinned until
        # the whole action finishes, including exception/cancellation paths.
        begin=getattr(self.bridge,'beginEvidenceEffect',None)
        end=getattr(self.bridge,'endEvidenceEffect',None)
        if (begin is None)!=(end is None):raise Stop('incomplete_evidence_lease_bridge')
        if begin is not None:begin(packet['frame_id'])
        failed=True
        try:
            effect=self._execute(observed,packet)
            failed=not effect.get('confirmed',False)
            return effect
        finally:
            if end is not None:end(failed)

    def _execute(self,observed,packet):
        self.running()
        if observed.get('planning_complete') is False:raise Replan('effect_planning_incomplete')
        if self.read_only:raise Stop('read_only')
        if self.end_ledger.pending is not None:raise Stop('input_while_end_turn_pending')
        if packet['frame_id'] in self.consumed:raise Stop('stale_or_consumed_frame')
        if self.report['game_inputs']>=self.max_inputs:raise Stop('input_budget')
        try:plan=request(observed,packet,self.now(),self.deadline-self.now())
        except ValueError as error:raise Replan(str(error))
        state_key=observed.get('current_state_key') or 'unavailable_current_state'
        if (plan['context']=='end_turn' and self.last_end_state_key==state_key
                and self.same_state_end_attempts>=self.max_failed_inputs):
            raise Stop('same_state_end_turn_failed_%d_times'%self.max_failed_inputs)
        self.running()
        reply=_parse(self.bridge.dispatch(_json(plan)))
        item=dict(request=plan,reply=reply,accepted_elapsed_ms=self.now() if reply.get('accepted') is True else None)
        self.report['inputs'].append(item);self.emit('dispatch',item)
        if reply.get('accepted') is not True:
            if reply.get('accepted') is False and reply.get('completed') is False and reply.get('reason')=='temporary_game_window_occluded':
                raise Replan('temporary_game_window_occluded')
            if reply.get('reason') in ('frame_age_expired','input_frame_age_exceeded','frame_expired'):raise Replan('java_frame_expired_replan')
            raise Stop('gesture_rejected:'+str(reply.get('reason')))
        self.report['game_inputs']+=1;self.consumed.add(packet['frame_id'])
        if reply.get('completed') is not True:raise Stop('gesture_not_completed:'+str(reply.get('reason')))
        self.frontline_recheck.reset()
        if plan['context']=='choice_select':
            started=self.now();confirmed=False
            pair=dict(context='choice_select',request=plan,reply=reply,dispatch_elapsed_ms=item['accepted_elapsed_ms'],observations=[observed])
            while self.now()<min(self.deadline,started+4000):
                self.running();time.sleep(.12)
                try:after,_=self.capture()
                except Replan:continue
                pair['observations'].append(after)
                if not after.get('choice_modal') and after['state'] in ('battle','opponent_turn'):
                    confirmed=True;break
            hook=dict(kind='choice_select',turn=self.turn,inputs=1,terminated=False,
                      verification='confirmed' if confirmed else 'unconfirmed',before_capture=packet['frame_id'],
                      after_capture=self.last_id,detail='three_choice_disappeared' if confirmed else 'three_choice_still_present',
                      verification_elapsed_ms=self.now()-started)
            self.report['hooks'].append(hook);self.emit('hook',hook)
            self.report['actions_confirmed']+=int(confirmed);self.report['unconfirmed_inputs']+=int(not confirmed)
            (self.out/('native-effect-%06d.json'%packet['frame_id'])).write_text(_json(pair),encoding='utf8')
            return {'confirmed':confirmed,'reason':hook['detail']}
        if plan['context']=='end_turn':
            hook=dict(kind='end_turn',turn=self.turn,inputs=1,terminated=False,
                      verification='pending_transition',before_capture=packet['frame_id'])
            self.report['hooks'].append(hook);self.report['pending_end_turn_inputs']+=1
            self.end_ledger.register(len(self.report['hooks'])-1,len(self.report['inputs'])-1,
                                     packet,self.now(),self.turn)
            self.same_state_end_attempts=self.same_state_end_attempts+1 if self.last_end_state_key==state_key else 1
            self.last_end_state_key=state_key
            self.turn_preparation.after_completed_end(observed)
            self.end_audit.previous=None;self.emit('hook',hook)
            return dict(confirmed=False,reason='pending_turn_transition')
        # Reserve the actor/card before observing the outcome; an unknown effect
        # must never replay the same physical action in this turn.
        self.isolated.append(self.identity(observed['selected_action']))
        source_turn=self.turn
        pair=dict(context=plan['context'],request=plan,reply=reply,dispatch_elapsed_ms=item['accepted_elapsed_ms'],observations=[observed])
        effect=dict(confirmed=False,reason='effect_window_exhausted')
        verification_started=self.now()
        deadline=min(self.deadline,verification_started+4000)
        latest=None
        while self.now()<deadline:
            self.running();time.sleep(.12)
            try:after,after_packet=self.capture_effect(plan['context'])
            except Replan:continue
            latest=(after,after_packet)
            pair['observations'].append(after)
            if after.get('choice_modal') or after['state'] not in ('battle','opponent_turn'):
                effect=dict(confirmed=False,reason='effect_observation_interrupted:'+after['state']);break
            effect=sequence_postcondition(pair)
            if effect['confirmed']:break
            # Extend only a promising proof, rather than spend ten seconds on
            # every failed drag. Historical slow animations still get enough
            # independent captures to complete their existing postcondition.
            samples=effect.get('samples') or []
            if samples and any(samples[-1].get(key) is True for key in
                               ('complete_row_increment','front_observed','changed')):
                deadline=min(self.deadline,verification_started+10000)
            # An uncovered detector cannot become positive by polling it for
            # ten seconds. Preserve unknown + current-turn actor isolation.
            if effect.get('status')=='uncovered':break
        confirmed=effect['confirmed'];kind=plan['context'];skipped=not confirmed and kind!='deploy'
        if confirmed:
            identity=self.identity(observed['selected_action'])
            if identity in self.isolated:self.isolated.remove(identity)
        elif kind=='deploy' and self.turn==source_turn:
            self.failed_deploys+=1
        hook=dict(kind=kind,turn=source_turn,inputs=1,terminated=False,verification='confirmed' if confirmed else 'unconfirmed_skipped' if skipped else 'unconfirmed',
                  before_capture=packet['frame_id'],after_capture=self.last_id,detail=effect['reason'],effect=effect,
                  verification_elapsed_ms=self.now()-verification_started)
        self.report['hooks'].append(hook)
        self.report['actions_confirmed']+=int(confirmed);self.report['unconfirmed_inputs']+=int(not confirmed)
        self.report['unconfirmed_skipped']+=int(skipped)
        self.emit('hook',hook)
        (self.out/('native-effect-%06d.json'%packet['frame_id'])).write_text(_json(pair),encoding='utf8')
        if (latest is not None and latest[0]['state']=='battle'
                and not latest[0].get('choice_modal') and self.turn==source_turn):
            self.ready_observation=latest
        return effect
