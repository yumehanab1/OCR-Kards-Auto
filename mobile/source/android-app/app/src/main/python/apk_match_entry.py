"""APK menu entry for an explicitly selected casual/ranked match.

Only this session's verified queue request can hand over to the opening engine.
No ADB, shell, old main_loop or frozen-core import is used here.
"""
from __future__ import annotations

import json
from pathlib import Path
import time
import cv2
import numpy as np


MODES = ('casual', 'ranked')
# Includes all observed startup overlays; same ceiling as MenuDispatchGuard.
MAX_MENU_INPUTS = 16
WAIT_STATES = frozenset(('unknown', 'menu_transition'))
FRAME_KEYS = ('frame_id', 'captured_elapsed_ms', 'foreground_generation', 'source_width', 'source_height')
POPUP_ACTIONS = {'task_popup':'menu_dismiss_task', 'pass_popup':'menu_dismiss_pass',
                 'box_popup':'menu_dismiss_box', 'store_popup':'menu_dismiss_store',
                 'airdrop_popup':'menu_dismiss_airdrop', 'starter_popup':'menu_dismiss_starter',
                 'weekend_popup':'menu_dismiss_weekend',
                 'blocking_popup':'menu_dismiss_blocking_popup'}
NATIVE_POPUP_ACTIONS = {**POPUP_ACTIONS,'generic_popup':'menu_dismiss_generic',
                        'login_popup_cleanup':'menu_clear_login_popup'}
# A historically exercised neutral background point below task/reward cards.
# Promotions use their visibly matched close X instead, never their content.
TASK_DISMISS_BOUNDS = [890, 585, 32, 30]
FIRST_DECK_BOUNDS = [358, 87, 177, 250]
# Empty tabletop below the first row; reviewed second-deck close returned to list.
DECK_CLOSE_BOUNDS = [840, 586, 28, 28]


def first_deck_frame(frame):
    """Observe the shared card's thick cream outline, independent of its art/name.

    All four sides must exist in the first top slot. Thin empty-deck placeholders
    and clipped/scrolled cards do not have three pale pixels across every edge.
    Menu selection labels are checked separately before this geometry is used.
    """
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    pale=(hsv[:,:,2]>=145)&(hsv[:,:,1]<=105)
    edges={}
    for name,(x,y,w,h),axis in (
            ('top',(358,87,177,10),0),('bottom',(358,326,177,11),0),
            ('left',(358,97,9,229),1),('right',(525,97,10,229),1)):
        counts=pale[y:y+h,x:x+w].sum(axis=axis)
        edges[name]=float((counts>=3).mean())
    return {'ok':all(value>=.90 for value in edges.values()),'edges':edges,
            'bounds':list(FIRST_DECK_BOUNDS)}


def parse(value):
    return value if isinstance(value, dict) else json.loads(str(value))


def result_controls(frame):
    """Observed result-page frame and bottom continue glyphs, never a target.

    Both controls are disjoint from the strict failure text. Requiring all four
    sides rejects bare-text/loading images; settlement still owns every tap.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = {}
    for name, (x, y, w, h), axis in (
            ('top', (1065, 29, 187, 3), 0), ('bottom', (1065, 70, 187, 3), 0),
            ('left', (1065, 29, 3, 44), 1), ('right', (1249, 29, 3, 44), 1)):
        edges[name] = float((gray[y:y+h, x:x+w].max(axis=axis) >= 60).mean())
    white = gray[670:694, 618:661] >= 140
    count = int(white.sum())
    columns = int((white.sum(axis=0) >= 2).sum())
    rows = int((white.sum(axis=1) >= 2).sum())
    return {'ok': all(v >= .95 for v in edges.values()) and
            150 <= count <= 350 and 28 <= columns <= 39 and 16 <= rows <= 22,
            'view_battlefield_edges': edges, 'continue_pixels': count,
            'continue_columns': columns, 'continue_rows': rows}


_OBSERVERS = {}


def read_frame(path):
    """Decode one captured frame, and report which route produced it.

    A live settle pass classified nothing at all (`unsupported_frame_size`,
    frame None) for files this same process decoded elsewhere without complaint,
    so decoding here is explicit and never silent: `cv2.imread` first, then the
    frame's own bytes through `cv2.imdecode`, and the route taken is returned as
    evidence. A decode problem must not be reported as a screen the recogniser
    failed to name.
    """
    frame = cv2.imread(str(path))
    route = 'imread'
    if frame is None:
        try:
            with open(str(path), 'rb') as handle:
                frame = cv2.imdecode(np.frombuffer(handle.read(), np.uint8), cv2.IMREAD_COLOR)
            route = 'imdecode'
        except OSError as error:
            import os
            route = 'unreadable:%s:%s|exists=%s|cwd=%s' % (
                error.__class__.__name__, error, os.path.exists(str(path)), os.getcwd())
    return frame, route


def observe(png_path, assets_dir, result_only=False):
    """Classify one already-captured frame with this module's recogniser.

    Used by the settlement loop, which must learn the current screen from the
    same recognised states the menu uses. The recogniser is cached per assets
    directory because template loading costs far more than one match.

    The decoded frame is described in the result: a frame the app could not
    decode, a frame it decoded differently, and a frame it simply did not
    recognise are three different faults and may not look alike in a report.
    """
    assets = str(assets_dir)
    recognizer = _OBSERVERS.get(assets)
    if recognizer is None:
        recognizer = Recognizer(assets)
        _OBSERVERS[assets] = recognizer
    frame, route = read_frame(png_path)
    observation = (recognizer.observe(frame, result_only=True) if result_only else
                   recognizer.observe(frame))
    observation['frame_shape'] = list(frame.shape) if frame is not None else None
    observation['frame_reader'] = route
    observation['frame_path'] = str(png_path)
    observation['frame_path_length'] = len(str(png_path))
    observation['cv2_version'] = cv2.__version__
    return json.dumps(observation, ensure_ascii=False)


class Recognizer:
    def __init__(self, assets):
        assets = Path(assets)
        self.specs = json.loads((assets / 'manifest.json').read_text(encoding='utf-8'))['templates']
        self.templates = {name: cv2.imread(str(assets / spec['file'])) for name, spec in self.specs.items()}
        if any(value is None for value in self.templates.values()):
            raise ValueError('menu_template_missing')

    def observe(self, frame, result_only=False):
        if frame is None or frame.shape != (720, 1280, 3):
            return {'state': 'unknown', 'reason': 'unsupported_frame_size'}
        if np.max(frame) < 8:
            return {'state': 'unknown', 'reason': 'black_transition'}
        matches = {}

        def match(name):
            if name in matches:
                return matches[name]
            template = self.templates[name]
            x, y, w, h = self.specs[name]['bounds']
            # Small positional tolerance, no full-screen search for a coincidental label.
            # The centered task line shifts its fixed caption 4px left when
            # progress grows from one digit to two (observed 10/12). Its title
            # still uses the original tolerance and remains independently required.
            task_shift = 4 if name.startswith('task_subtitle') else 0
            left, top, right, bottom = max(0,x-3-task_shift), max(0,y-3), min(1280,x+w+3), min(720,y+h+3)
            roi = frame[top:bottom, left:right]
            scores = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, point = cv2.minMaxLoc(scores)
            bx, by = left+point[0], top+point[1]
            crop = frame[by:by+h,bx:bx+w]
            mad = float(np.mean(cv2.absdiff(crop, template)))
            brightness = float(crop.mean()) / max(1., float(template.mean()))
            good = score >= .93 and mad <= 13 and .88 <= brightness <= 1.14
            result = {'ok': bool(good), 'score': round(score, 5), 'mad': round(mad, 3),
                      'brightness': round(brightness, 3), 'bounds': [bx, by, w, h]}
            matches[name] = result
            return result

        def has(*names):
            return all(match(name)['ok'] for name in names)

        def result(state, targets=None, selected='', reason=''):
            # The 开始 control is reported for every frame, including the pages
            # whose state is decided before 'home' is checked. It is the only
            # thing a return tap is allowed to press, so a caller must be able to
            # ask "is that button drawn here?" without knowing the page's name.
            plain, highlighted = match('home_play'), match('home_play_selected')
            # The selected tab has its own observed pixels. Its icon alone is
            # never authority: the complete menu labels must also be present.
            # While cards are rendering, report visible-but-not-actionable so
            # return callers wait rather than pressing the current tab again.
            selected_context = (has('battle_selected', 'training_unselected') or
                                has('battle_unselected', 'training_selected'))
            variant = ('unselected' if plain['ok'] else
                       'selected' if highlighted['ok'] and selected_context else 'absent')
            start = highlighted if variant == 'selected' else plain
            visible = variant != 'absent'
            return {'state': state, 'selected_mode': selected, 'targets': targets or {},
                    'reason': reason, 'action_ready': bool(targets),
                    'evidence': matches,
                    'start_control': {'ok': visible and state != 'menu_transition',
                                      'visible': visible, 'variant': variant,
                                      'score': start['score'], 'bounds': start['bounds']}}

        if result_only:
            # Battle's old result crop has a different text size. Reuse this
            # already-verified strict banner, with the complete result controls
            # around it; a pasted banner alone is not a finished match.
            context = result_controls(frame)
            matches['result_controls'] = context
            return result('result_defeat' if has('defeat_banner') and context['ok'] else 'unknown')
        if has('disconnect_title', 'reconnect'):
            return result('disconnected', {'menu_reconnect': match('reconnect')['bounds']})
        # Two observed daily-reward variants share this title. The press-anywhere
        # form shows 继续; the unclaimed form exposes the golden 领取 label at the
        # same slot. Both anchors are observed controls, never reward art.
        if has('login_title', 'login_continue'):
            return result('login_reward', {'menu_dismiss_reward': match('login_continue')['bounds']})
        if has('login_title', 'login_claim'):
            return result('login_reward', {'menu_dismiss_reward': match('login_claim')['bounds']})
        if has('task_title') and any(has(name) for name in ('task_subtitle',
                'task_subtitle_pass_backdrop','task_subtitle_cards_backdrop')):
            return result('task_popup', {'menu_dismiss_task': list(TASK_DISMISS_BOUNDS)})
        if has('pass_title', 'pass_close'):
            return result('pass_popup', {'menu_dismiss_pass': match('pass_close')['bounds']})
        if has('box_title', 'box_close'):
            return result('box_popup', {'menu_dismiss_box': match('box_close')['bounds']})
        # Third observed startup promotion: a taller panel whose text block is
        # neither pass_title nor box_title. Same two-anchor rule, observed title
        # text plus the observed close control, never promotional content.
        if has('store_title', 'store_close'):
            return result('store_popup', {'menu_dismiss_store': match('store_close')['bounds']})
        # Exact observed offer variants each have their own once-only action:
        # they can follow store/pass/box without reusing those issued tokens.
        # A white X alone is never authority. Require the full title and all
        # four complete panel-border strips, disjoint from title and X, with
        # coherent +/-3px match offsets; changing timers/prices are excluded.
        for popup in ('airdrop', 'starter', 'weekend'):
            anchors = tuple(popup+'_'+suffix for suffix in (
                'title', 'close', 'edge_top', 'edge_bottom', 'edge_left', 'edge_right'))
            if has(*anchors):
                offsets = [(matches[name]['bounds'][0]-self.specs[name]['bounds'][0],
                            matches[name]['bounds'][1]-self.specs[name]['bounds'][1])
                           for name in anchors]
                coherent = all(max(row[axis] for row in offsets)-min(row[axis] for row in offsets) <= 1
                               for axis in (0, 1))
                matches[popup+'_panel'] = {'ok': coherent, 'anchor_offsets': offsets}
                if coherent:
                    return result(popup+'_popup', {
                        'menu_dismiss_'+popup: match(popup+'_close')['bounds']})
        if has('detail_battle', 'detail_training', 'detail_start'):
            ranked, casual = match('selector_ranked'), match('selector_casual')
            selected = ''
            for mode, good, other in (('ranked',ranked,casual), ('casual',casual,ranked)):
                # The whole selector contains BOTH labels. Require a unique complete state,
                # plus orange text only on the selected side; gray text is not selection.
                if good['ok'] and good['score'] >= .965 and good['score'] - other['score'] >= .025:
                    x,y,w,h = good['bounds']
                    hsv = cv2.cvtColor(frame[y:y+h,x:x+w], cv2.COLOR_BGR2HSV)
                    orange = (hsv[:,:,0] >= 10) & (hsv[:,:,0] <= 30) & (hsv[:,:,1] >= 120) & (hsv[:,:,2] >= 100)
                    left, right = int(orange[:,:w//2].sum()), int(orange[:,w//2:].sum())
                    on, off = (left,right) if mode == 'ranked' else (right,left)
                    if on >= 60 and off <= max(8, on*.08):
                        selected = mode
            if selected:
                x,y,w,h = matches['selector_'+selected]['bounds']
                targets = {
                    'menu_select_ranked': [x,y,w//2,h],
                    'menu_select_casual': [x+w//2,y,w-w//2,h],
                    'menu_start_queue': match('detail_start')['bounds']}
                if DECK_CLOSE_BOUNDS is not None:
                    targets['menu_close_deck']=list(DECK_CLOSE_BOUNDS)
                return result('deck_ready',targets,selected)
            return result('unknown')
        if has('battle_selected', 'training_unselected'):
            matches['first_deck_frame']=first_deck_frame(frame)
            if matches['first_deck_frame']['ok']:
                return result('deck_list', {'menu_select_deck':list(FIRST_DECK_BOUNDS)})
            if has('home_play_selected'):
                # Observed live after a return tap: the stable menu shell is
                # already drawn while the first card's top/bottom are still
                # transparent. This names a wait, not a card or a click target.
                return result('menu_transition', reason='first_deck_not_ready')
        if has('battle_unselected', 'training_selected'):
            return result('mode_menu', {'menu_battle_mode': match('battle_unselected')['bounds']})
        # Card collection: named so the dismissal loop can never mistake it for
        # the start page. The 开始 slot is drawn identically on both, so its own
        # tab label is the anchor. Checked before 'home' and before deck_list.
        if has('card_tab'):
            return result('card_collection')
        # Home needs a home-only anchor beside the play button: the button alone
        # also matches the card collection, which is how a live settlement run
        # misread that screen as unknown and spent its whole budget there.
        if has('home_play', 'home_tasks'):
            return result('home', {'menu_home_start': match('home_play')['bounds']})
        if has('queue_cancel'):
            return result('queueing')
        # A finished match leaves its 胜利/失败 banner on screen, which no other
        # state covers: the settlement dismissal needs to tell "still on the
        # result page" from "back on a menu", and PC records that this banner is
        # text rather than a button. Banner observed on settled Android frames.
        if has('defeat_banner'):
            return result('result_defeat')
        return result('unknown')


class MenuFlow:
    """Pure bounded state machine. Issued actions never repeat in one session."""
    def __init__(self, mode, started):
        if mode not in MODES:
            raise ValueError('invalid_match_mode')
        self.mode, self.started = mode, started
        self.last_key = None
        self.last_time = None
        self.last_frame = None
        self.stable = 0
        self.queue_requested = None
        self.pending = None
        self.issued = set()
        self.unknown_since = None
        self.transition_since = None
        self.inputs = 0
        self.required_frames = 2
        self.max_inputs = MAX_MENU_INPUTS
        self.login_cleanup_attempts = 0
        self.login_cleanup_started = None
        self.first_deck_selected = False
        self.startup_cleanup = False
        self.startup_cleanup_attempts = 0
        self.startup_cleanup_frame = None
        self.startup_cleanup_sent = None

    def observe(self, observation, frame_id, now, opening=False):
        if now-self.started >= 180000:
            return {'stop': 'menu_time_budget'}
        state = observation['state']
        if self.startup_cleanup and self.queue_requested is None:
            if opening:
                self.startup_cleanup = False
                return {'stop': 'startup_existing_game_mode_unverified'}
            if state in ('home','mode_menu','deck_list','deck_ready','mulligan_ready','battle'):
                self.startup_cleanup = False
                if self.pending and self.pending[0] == 'menu_startup_cleanup':
                    self.pending = None
            elif state == 'unknown':
                if frame_id == self.startup_cleanup_frame or (self.startup_cleanup_sent is not None
                        and now-self.startup_cleanup_sent < 1000):
                    return {'wait': state}
                if self.startup_cleanup_attempts >= 15:
                    return {'stop':'startup_cleanup_exhausted'}
                if self.inputs >= self.max_inputs:
                    return {'stop':'menu_input_budget'}
                bounds = observation.get('targets',{}).get('menu_startup_cleanup')
                if not bounds:
                    return {'stop':'menu_target_missing'}
                self.startup_cleanup_frame = frame_id
                return {'action':'menu_startup_cleanup','bounds':bounds}
        if self.queue_requested is not None:
            if now-self.queue_requested >= 120000:
                return {'stop': 'matchmaking_timeout_queue_may_continue'}
            if state == 'disconnected':
                return {'stop': 'disconnected_after_queue'}
            if opening:
                state = 'mulligan_ready'
            elif state not in (*WAIT_STATES, 'queueing') and now-self.queue_requested > 12000:
                return {'stop': 'queue_did_not_open'}
        elif state == 'queueing':
            return {'stop': 'existing_queue_mode_unverified'}
        key = (state, observation.get('popup_id','') if state=='generic_popup' else observation.get('selected_mode', ''))
        # Different capture IDs and a bounded gap prevent a duplicate/stale frame
        # or two unrelated visits to a screen from forming confirmation evidence.
        if (key == self.last_key and frame_id != self.last_frame and self.last_time is not None
                and 400 <= now-self.last_time <= 5000):
            self.stable += 1
        else:
            self.stable = 1
        self.last_key, self.last_time, self.last_frame = key, now, frame_id
        if state == 'mulligan_ready' and self.queue_requested is not None:
            return {'verified': True} if self.stable >= self.required_frames else {'wait': state}
        if self.queue_requested is not None:
            return {'wait': state}
        if state == 'menu_transition':
            if self.transition_since is None:
                self.transition_since = now
            if now-self.transition_since >= 30000:
                return {'stop': 'menu_transition_timeout'}
            return {'wait': state}
        self.transition_since = None
        if state == 'unknown':
            if self.unknown_since is None:
                self.unknown_since = now
            if now-self.unknown_since >= 30000:
                return {'stop': 'menu_unknown_timeout'}
            return {'wait': state}
        self.unknown_since = None
        if self.pending is not None:
            action, sent = self.pending
            expected = {
                'menu_home_start': state in ('mode_menu','deck_list'),
                'menu_battle_mode': state == 'deck_list',
                'menu_close_deck': state == 'deck_list',
                'menu_select_deck': state == 'deck_ready',
                'menu_select_casual': state == 'deck_ready' and key[1] == 'casual',
                'menu_select_ranked': state == 'deck_ready' and key[1] == 'ranked',
                'menu_dismiss_reward': state in ('home','mode_menu','deck_list','deck_ready',*NATIVE_POPUP_ACTIONS),
                'menu_reconnect': state in ('login_reward','home','mode_menu','deck_list','deck_ready',*NATIVE_POPUP_ACTIONS),
                **{dismiss: state in ('home','mode_menu','deck_list','deck_ready',*NATIVE_POPUP_ACTIONS)
                            and state != popup for popup,dismiss in NATIVE_POPUP_ACTIONS.items()},
            }.get(action, False)
            if action=='menu_clear_login_popup':
                if state=='login_popup_cleanup':
                    if now-sent<1000:return {'wait':state}
                    if self.login_cleanup_attempts>=15:return {'stop':'login_popup_cleanup_exhausted'}
                    # Each retry is based on two independently captured current overlay proofs.
                    if self.stable<self.required_frames:return {'wait':state}
                    self.pending=None
                    expected=True
                else:
                    expected=state in ('home','mode_menu','deck_list','deck_ready',*NATIVE_POPUP_ACTIONS)
            if action=='menu_dismiss_generic' and state=='generic_popup':
                expected=bool(key[1]) and key[1]!=getattr(self,'pending_popup_id','')
            if not expected:
                if now-sent >= (45000 if action == 'menu_reconnect' else 15000):
                    return {'stop': 'menu_action_unconfirmed:'+action}
                return {'wait': state}
            if self.stable < self.required_frames:
                return {'wait': state}
            if action == 'menu_select_deck':
                self.first_deck_selected = True
            self.pending = None
        if self.stable < self.required_frames:
            return {'wait': state}
        action = {'home':'menu_home_start', 'mode_menu':'menu_battle_mode',
                  'deck_list':'menu_select_deck','login_reward':'menu_dismiss_reward',
                  'disconnected':'menu_reconnect', **NATIVE_POPUP_ACTIONS}.get(state)
        if state == 'deck_ready':
            action = ('menu_close_deck' if not self.first_deck_selected else
                      'menu_start_queue' if key[1] == self.mode else 'menu_select_'+self.mode)
        if action is None:
            return {'wait': state}
        issued_key=(action,key[1]) if action=='menu_dismiss_generic' else action
        if action=='menu_clear_login_popup':
            if self.login_cleanup_attempts>=15:return {'stop':'login_popup_cleanup_exhausted'}
            if self.login_cleanup_started is not None and now-self.login_cleanup_started>=45000:
                return {'stop':'login_popup_cleanup_time_budget'}
        if issued_key in self.issued and action!='menu_clear_login_popup':
            return {'stop': 'menu_repeated_state:'+action}
        if self.inputs >= self.max_inputs:
            return {'stop': 'menu_input_budget'}
        bounds = observation.get('targets', {}).get(action)
        if not bounds:
            return {'stop': 'menu_target_missing'}
        return {'action': action, 'bounds': bounds}

    def accepted(self, action, now, popup_id=''):
        self.inputs += 1
        if action == 'menu_startup_cleanup':
            self.startup_cleanup_attempts += 1
            self.startup_cleanup_sent = now
        if action=='menu_clear_login_popup':
            self.login_cleanup_attempts+=1
            if self.login_cleanup_started is None:self.login_cleanup_started=now
        self.issued.add((action,popup_id) if action=='menu_dismiss_generic' else action)
        self.pending_popup_id=popup_id
        self.pending = (action, now)
        self.stable = 0
        self.last_key = None
        if action in ('menu_close_deck','menu_select_deck'):
            self.first_deck_selected = False
        if action == 'menu_start_queue':
            self.queue_requested = now


def run(bridge, assets_dir, mode, native=False):
    if native:
        from apk_native.menu import NativeMenuRecognizer
        recognizer = NativeMenuRecognizer(assets_dir, bridge, startup=True)
    else:
        recognizer = Recognizer(assets_dir)
    flow = MenuFlow(str(mode), int(bridge.elapsedRealtime()))
    if native:flow.max_inputs=32;flow.required_frames=1;flow.startup_cleanup=True
    reason = 'cancelled'
    verified = False
    expired_dispatches = 0
    while not bridge.isCancelled():
        now = int(bridge.elapsedRealtime())
        if now-flow.started >= 180000 or now >= int(bridge.deadlineElapsedRealtime())-8000:
            reason = 'menu_time_budget'
            break
        packet = parse(bridge.captureNative() if native else bridge.capture())
        if not packet.get('ok'):
            reason = str(packet.get('reason', packet.get('error', 'capture_failed')))
            if reason == 'waiting_for_new_game_foreground':
                bridge.emit(json.dumps({'kind':'menu','value':{'state':'waiting_for_game','mode':flow.mode}}))
                time.sleep(.8)
                continue
            break
        frame, reader = read_frame(packet['png_path'])
        opening = False
        if native and flow.queue_requested is not None:
            # Queue already owns the only next step. Do not scan unrelated
            # menus/OCR before inspecting the same source frame's opening.
            check = parse(bridge.inspectOpening())
            opening = (check.get('ok') is True and check.get('frame_id') == packet.get('frame_id')
                       and check.get('phase') in ('MULLIGAN_CONFIRM','CONFIRMED_MY_TURN'))
            observation={'state':'unknown','targets':{},'selected_mode':'',
                         'reason':'native_queue_opening_only','opening_evidence':check}
        else:
            observation = recognizer.observe(frame, packet) if native else recognizer.observe(frame)
            if native and flow.startup_cleanup and observation.get('state') == 'unknown':
                check = parse(bridge.inspectOpening())
                opening = (check.get('ok') is True and check.get('frame_id') == packet.get('frame_id')
                           and check.get('phase') in ('MULLIGAN_CONFIRM','CONFIRMED_MY_TURN','CONFIRMED_OPPONENT_TURN'))
                observation['opening_evidence'] = check
                h,w = frame.shape[:2]
                size = max(8,round(h*24/720))
                observation['targets']['menu_startup_cleanup'] = [w/2-size/2,round(h*665/720)-size/2,size,size]
        observation.update(frame_reader=reader,
            frame_shape=list(frame.shape) if frame is not None else None,
            frame_path=str(packet['png_path']))
        if not native and flow.queue_requested is not None:
            check = parse(bridge.inspectOpening())
            opening = (check.get('ok') is True and check.get('frame_id') == packet.get('frame_id')
                       and check.get('phase') == 'MULLIGAN_CONFIRM')
        now = int(bridge.elapsedRealtime())
        age = now-packet['captured_elapsed_ms']
        if age < 0 or age > 3000:
            # BOTH observations in a stable pair must be fresh, including the
            # observation used only as a precursor to a later authorized tap.
            flow.stable = 0
            flow.last_key = None
            bridge.emit(json.dumps({'kind':'menu','value':{'state':'unknown',
                'mode':flow.mode,'reason':'menu_frame_age_expired','frame_id':packet['frame_id'],
                'frame_age_ms':age,'observed_state':observation.get('state'),
                'timings_ms':observation.get('timings_ms'),
                'ocr_metrics':observation.get('ocr_metrics')}}))
            time.sleep(.5)
            continue
        decision = flow.observe(observation, packet['frame_id'], now, opening)
        value = dict(observation, mode=flow.mode, menu_inputs=flow.inputs,
                     action=decision.get('action',''), queue_requested=flow.queue_requested is not None,
                     first_deck_selected=flow.first_deck_selected,
                     frame_id=packet['frame_id'])
        if opening:
            value['state'] = 'mulligan_ready'
        bridge.emit(json.dumps({'kind':'menu','value':value}, ensure_ascii=False))
        if decision.get('verified'):
            verified, reason = True, 'mulligan_ready'
            break
        if decision.get('stop'):
            reason = decision['stop']
            break
        if decision.get('action'):
            age = int(bridge.elapsedRealtime())-packet['captured_elapsed_ms']
            if age < 0 or age > 3000:
                # Nothing sent: get two fresh observations, without consuming this action.
                flow.stable = 0
                flow.last_key = None
                time.sleep(.5)
                continue
            x,y,w,h = decision['bounds']
            point = [x+w/2, y+h/2]
            request = {key:packet[key] for key in FRAME_KEYS}
            if native:
                request.update(coordinate_space='source_pixels', popup_basis=observation.get('popup_basis',''),
                               startup_cleanup=flow.startup_cleanup,
                               queue_requested=flow.queue_requested is not None,
                               startup_cleanup_attempts=flow.startup_cleanup_attempts,
                               generic_popup_evidence=observation.get('generic_popup_evidence'),
                               login_popup_evidence=observation.get('login_popup_evidence'),
                               promotion_evidence=observation.get('promotion_evidence'))
            request.update(state=observation['state'], mode=flow.mode,
                selected_mode=observation.get('selected_mode',''), context=decision['action'],
                first_deck_selected=flow.first_deck_selected,
                target_bounds=decision['bounds'], kind='tap', duration_ms=60,
                **{'from':point, 'to':point})
            reply = parse(bridge.dispatchMenu(json.dumps(request)))
            bridge.emit(json.dumps({'kind':'menu_receipt','value':{'frame_id':packet['frame_id'],
                'action':decision['action'],'reply':reply}},ensure_ascii=False))
            if (reply.get('accepted') is False and reply.get('completed') is False
                    and reply.get('reason') == 'frame_age_expired'):
                # Java rejected BEFORE dispatch. Reacquire and recognize;
                # never replay the old request or advance the menu flow.
                expired_dispatches += 1
                flow.stable = 0
                flow.last_key = None
                bridge.emit(json.dumps({'kind':'menu_replan','value':{
                    'reason':'dispatch_frame_expired','frame_id':packet['frame_id'],
                    'frame_age_ms':int(bridge.elapsedRealtime())-packet['captured_elapsed_ms'],
                    'consecutive_rejections':expired_dispatches}}))
                if expired_dispatches >= 3:
                    reason = 'menu_dispatch_expired_3_times'
                    break
                time.sleep(.5)
                continue
            if reply.get('accepted'):
                flow.accepted(decision['action'], int(bridge.elapsedRealtime()),observation.get('popup_id',''))
            if not reply.get('accepted') or not reply.get('completed'):
                reason = 'menu_dispatch:'+str(reply.get('reason','unconfirmed'))
                break
            expired_dispatches = 0
        time.sleep(.8)
    result = {'verified':verified, 'reason':reason, 'mode':flow.mode,
              'menu_inputs':flow.inputs, 'queue_requested':flow.queue_requested is not None,
              'first_deck_selected':flow.first_deck_selected,
              'elapsed_ms':int(bridge.elapsedRealtime())-flow.started}
    return json.dumps(result, ensure_ascii=False)
