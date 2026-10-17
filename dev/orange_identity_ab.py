"""Offline old/new orange identity replay. No capture, cursor, or hash writes.

Default cases include measured main-card crops, broad-context stress cases
(the full real screenshot is deliberately used as a synthetic noisy diff),
and two old weather crops. For actual scan diffs use --manifest JSON:
{"cases":[{"frame":"shots/hover.png", "neutral":"shots/neutral.png",
"probe_x":528, "expected_name":"..."}]}. A case may instead provide
diff_box [x,y,w,h], fee {x,y,w,h}, panel_box, or expected_rejected true.
Timing is static recognition work; it is not whole-turn or live-game speed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import types
from unittest.mock import Mock, patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import hand_cost_filter as hcf
import hand_scanner_v2 as current
from card_match import CardHashDB
from hover_card_reader import _ocr
from ui_state import load_meta, load_templates


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def baseline_module(ref):
    source = subprocess.run(['git', 'show', f'{ref}:src/hand_scanner_v2.py'],
                            cwd=ROOT, check=True, capture_output=True).stdout
    module = types.ModuleType('_orange_identity_baseline')
    module.__file__ = str(ROOT / 'src' / 'hand_scanner_v2.py')
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module, hashlib.sha256(source).hexdigest()


def default_cases():
    cases = []
    for filename, px, expected in (
            ('1016_130701_x405.png', 405, '第 506 空降步兵团'),
            ('1016_125431_x388.png', 388, '第 506 空降步兵团'),
            ('1016_123254_x455.png', 455, '丁格犬侦察车')):
        case = dict(frame='shots/orange_hover_roi_20261016/' + filename,
                    probe_x=px, expected_name=expected)
        cases.append(dict(case, name=filename + ':same_main_panel',
                          input_kind='same_main_panel'))
        cases.append(dict(case, name=filename + ':broad_context_stress',
                          input_kind='synthetic_wide_diff', diff_box=[0, 0, 1280, 720]))
    campaign = 'logs/pc_campaign_20261014_104905/'
    cases += [dict(name='cyclone_weather_crop',
                   frame=campaign + 'm03_1791947955598891300_0003_weather_3.png',
                   panel_box=[210, 0, 235, 320],
                   input_kind='same_weather_crop', expected_name='旋风【cyclone】',
                   expected_weather_id='cyclone'),
              dict(name='unread_torrential_rain_crop',
                   frame=campaign + 'm04_1791948168465528000_0006_weather_5.png',
                   panel_box=[210, 108, 235, 320],
                   input_kind='same_weather_crop', expected_rejected=True)]
    cases.append(dict(name='observed_jungle_fever_artwork_fee_failure',
                      frame='logs/pc_speed_fix1_20261017_131846/profile_01_hover_cost_mismatch.png',
                      probe_x=717, input_kind='observed_fee_selection_failure', fan_cost=4,
                      require_verified_fee=True, expected_old_fee_rejected=True,
                      recheck_orange=True,
                      expected_name='丛林热【temp_jungle_fever_1】',
                      expected_weather_id='temp_jungle_fever_1'))
    return cases


def fee_refusal(fee_cost):
    """No classification is authorized when the selected fee is unverified."""
    return dict(elapsed_s=0.0, info={key: None for key in
                ('name', 'type', 'cost', 'weather_id', 'weather_unresolved', 'weather_text',
                 'name_tier', 'hover_retried', 'hash_hit_distance')},
                playable=False, ocr_calls=[], ocr_count=0, ocr_pixels=0,
                static_retry_count=0, hash_learn_calls_suppressed=0,
                fee_rejected=True, selected_hover_cost=fee_cost)


def resolve_path(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def image_read(path):
    frame = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f'Cannot read image: {path}')
    return frame


def replay(module, templates, frame, box, px, active, recheck_card=None):
    scanner = module.HandScannerV2.__new__(module.HandScannerV2)
    scanner.templates = templates
    scanner.icon_names = [name for name in templates if name.endswith('_icon')]
    scanner.hash_db = CardHashDB(str(ROOT / 'config/card_hashes.json'))
    scanner._learn_hash = Mock()  # Never learn or save during a replay.
    scanner.classic_strategy = False
    scanner._scan_deadline = None
    scanner._orange_identity_active = active
    scanner.y = module.PROBE_Y
    scanner._last_client = (px, scanner.y)
    scanner.user_took_over = Mock(return_value=False)
    scanner._move = Mock(side_effect=AssertionError('live cursor input prohibited'))
    scanner._baseline = Mock(return_value=np.zeros_like(frame))
    scanner._hover_frame = Mock(return_value=frame)
    scanner.orange_cache = []
    calls = []

    def measured_ocr(image):
        started = time.perf_counter()
        try:
            return _ocr(image)
        finally:
            calls.append(dict(shape=list(image.shape[:2]),
                              pixels=int(image.shape[0] * image.shape[1]),
                              elapsed_s=round(time.perf_counter() - started, 6)))

    x, y, width, height = box
    started = time.perf_counter()
    recheck = None
    with patch.object(module, '_ocr', side_effect=measured_ocr):
        if recheck_card is None:
            info = scanner._classify(frame[y:y+height, x:x+width], y0=y,
                                     box=box, frame=frame)
        else:
            original = scanner._classify
            seen = []
            def remember_info(*args, **kwargs):
                info = original(*args, **kwargs)
                seen.append(info)
                return info
            scanner._classify = remember_info
            valid, note = scanner.recheck_card(recheck_card)
            info = seen[-1] if seen else {}
            recheck = dict(valid=bool(valid), note=note,
                           deadline_restored=scanner._scan_deadline is None)
    elapsed = time.perf_counter() - started
    fields = ('name', 'type', 'cost', 'weather_id', 'weather_unresolved',
              'weather_text', 'name_tier', 'hover_retried', 'hash_hit_distance')
    return dict(elapsed_s=round(elapsed, 6),
                info={key: info.get(key) for key in fields},
                playable=bool(info.get('name') and module.is_playable(info.get('type'), info.get('name'))),
                ocr_calls=calls, ocr_count=len(calls),
                ocr_pixels=sum(call['pixels'] for call in calls),
                hover_calls_total=scanner._hover_frame.call_count,
                static_retry_count=max(0, scanner._hover_frame.call_count - (1 if recheck_card else 0)),
                recheck=recheck,
                hash_learn_calls_suppressed=scanner._learn_hash.call_count)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', default='bea3acb94144b96171aa867e869e3b50e46ca46b')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--repeat', type=int, default=2)
    parser.add_argument('--system-id', default='unverified')
    parser.add_argument('--volume-serial', default='unverified')
    parser.add_argument('--game-version', default='unverified')
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error('--repeat must be positive')
    cases = json.loads(args.manifest.read_text(encoding='utf-8'))['cases'] if args.manifest else default_cases()
    old, old_sha = baseline_module(args.baseline_ref)
    templates = load_templates(load_meta(str(ROOT / 'config/templates.json')))
    # Initialize the shared OCR runtime before either timed path.
    _ocr(np.zeros((128, 128, 3), np.uint8))
    report = dict(date=datetime.now(timezone.utc).isoformat(),
                  system_id=args.system_id, volume_serial=args.volume_serial,
                  game_version=args.game_version, live_capture_or_input=False,
                  hash_cache_writes=False, baseline_ref=args.baseline_ref,
                  baseline_source_sha256=old_sha,
                  current_source_sha256=sha256(ROOT / 'src/hand_scanner_v2.py'),
                  repeats=args.repeat, samples=[], skipped=[],
                  limits=['Static OCR replay excludes game animation, mouse waits and whole turns.',
                          'Broad-context stress cases use a synthetic diff boundary on a real frame.',
                          'Only manifest cases with neutral/diff_box represent observed scan diffs.',
                          'Identical static retry frames do not simulate an animation finishing.'])
    failures = []
    for index, case in enumerate(cases):
        path = resolve_path(case['frame'])
        if not path.exists():
            report['skipped'].append(case)
            continue
        frame = image_read(path)
        px = case.get('probe_x', 528)
        fee = case.get('fee')
        fee_candidates = [fee] if fee else []
        old_fee = fee
        if fee is None and not case.get('panel_box') and case.get('input_kind') != 'same_weather_crop':
            fee_candidates = hcf.candidates(frame, zone=(max(340, px-140), 50, min(960, px+30), 600),
                                        height_range=(20, 50))
            old_fee = max(fee_candidates, key=lambda candidate: candidate['h'], default=None)
            fee = current.HandScannerV2._primary_orange_fee(fee_candidates)
            if fee is None:
                raise AssertionError(f'No unique enlarged orange header for {case}')
        fee_costs = {mode: hcf.read_candidate_cost(frame, selected, enlarged=True) if selected else None
                     for mode, selected in (('old', old_fee), ('new', fee))}
        panel_box = tuple(case.get('panel_box') or (
            current.HandScannerV2._orange_panel_box(frame, fee) if fee else (0, 0, frame.shape[1], frame.shape[0])))
        if case.get('neutral'):
            diff_box = current.diff_bbox(image_read(resolve_path(case['neutral'])), frame)
            if diff_box is None:
                raise AssertionError(f'No diff against neutral for {case}')
        else:
            diff_box = tuple(case.get('diff_box') or panel_box)
        sample = dict(case, frame_sha256=sha256(path), frame_shape=list(frame.shape[:2]),
                      fee=fee, old_fee=old_fee, fee_candidates=fee_candidates,
                      selected_fee_costs=fee_costs,
                      old_box=list(diff_box), new_box=list(panel_box), results={})
        raw = {'old': [], 'new': []}
        for repeat in range(args.repeat):
            # Alternate execution order to avoid always warming one path first.
            order = ('old', 'new') if (index + repeat) % 2 == 0 else ('new', 'old')
            for mode in order:
                module, box = (old, diff_box) if mode == 'old' else (current, panel_box)
                if case.get('require_verified_fee') and fee_costs[mode] != case.get('fan_cost'):
                    raw[mode].append(fee_refusal(fee_costs[mode]))
                else:
                    raw[mode].append(replay(module, templates, frame, box, px, active=mode == 'new'))
        for mode, results in raw.items():
            sample['results'][mode] = dict(
                median_elapsed_s=round(statistics.median(result['elapsed_s'] for result in results), 6),
                runs=results)
        new_infos = [result['info'] for result in raw['new']]
        success = True
        if 'expected_name' in case:
            success &= all(info['name'] == case['expected_name'] for info in new_infos)
        if 'expected_weather_id' in case:
            success &= all(info['weather_id'] == case['expected_weather_id'] for info in new_infos)
        if case.get('expected_rejected'):
            success &= all(not result['playable'] for result in raw['new'])
        if case.get('expected_old_fee_rejected'):
            success &= all(result.get('fee_rejected', False) for result in raw['old'])
        if case.get('recheck_orange'):
            card = dict(x=px, orange=True, name=case['expected_name'], cost=case['fan_cost'],
                        info=dict(weather_id=case['expected_weather_id']))
            sample['orange_recheck'] = replay(current, templates, frame, panel_box, px,
                                                active=False, recheck_card=card)
            success &= sample['orange_recheck']['recheck']['valid']
            success &= sample['orange_recheck']['recheck']['deadline_restored']
        sample['new_matches_expectation'] = bool(success)
        sample['same_identity'] = all(
            tuple(a['info'][key] for key in ('name', 'type', 'cost', 'weather_id')) ==
            tuple(b['info'][key] for key in ('name', 'type', 'cost', 'weather_id'))
            for a, b in zip(raw['old'], raw['new']))
        if not success:
            failures.append(case.get('name', case['frame']))
        report['samples'].append(sample)
        print(json.dumps(dict(case=case.get('name', case['frame']), passed=bool(success),
                              old_s=sample['results']['old']['median_elapsed_s'],
                              new_s=sample['results']['new']['median_elapsed_s'],
                              old_ocr=[result['ocr_count'] for result in raw['old']],
                              new_ocr=[result['ocr_count'] for result in raw['new']],
                              new_info=new_infos[0]), ensure_ascii=False), flush=True)
    report['failures'] = failures
    report['passed'] = bool(report['samples']) and not failures
    out = args.out or ROOT / 'logs' / ('orange_identity_ab_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Report: {out}')
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
