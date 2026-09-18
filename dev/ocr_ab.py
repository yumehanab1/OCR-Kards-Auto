"""A/B:`read_field` 的 OCR 兜底 —— 旧行为(per_card)vs 新行为(auto)。

比的是**结果有没有变**(总部找没找到、hp 一致不一致),以及**快了多少**。
"""
import cv2, sys, glob, os, time
sys.path.insert(0, 'src')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import board
from ui_state import load_meta, load_templates

tpl = load_templates(load_meta('config/templates.json'))
files = (sorted(glob.glob('shots/attack_frames/*.png'))
         + sorted(glob.glob('shots/board_samples/*.png')))
diff, same, t_old, t_new = [], 0, 0.0, 0.0
hq_old = hq_new = 0
for p in files:
    f = cv2.imread(p)
    if f is None:
        continue
    res = {}
    for mode in ('per_card', 'auto'):
        board.READ_FIELD_OCR = mode
        t0 = time.perf_counter()
        fi = board.read_field(f, templates=tpl)
        hq = board.find_enemy_hq(f, field=fi, templates=tpl)
        dt = time.perf_counter() - t0
        res[mode] = (hq, dt, len([u for r in fi['rows'] for u in r['units'] if u['is_hq']]))
        if mode == 'per_card':
            t_old += dt
        else:
            t_new += dt
    board.READ_FIELD_OCR = 'auto'
    o, n = res['per_card'], res['auto']
    hq_old += 1 if o[0] else 0
    hq_new += 1 if n[0] else 0
    ok_same = (None if not o[0] else (o[0]['x'], o[0].get('hp'))) == \
              (None if not n[0] else (n[0]['x'], n[0].get('hp'))) and o[2] == n[2]
    if ok_same:
        same += 1
    else:
        diff.append((os.path.basename(p),
                     None if not o[0] else (o[0]['x'], o[0].get('hp'), o[2]),
                     None if not n[0] else (n[0]['x'], n[0].get('hp'), n[2])))
print('帧数 %d:结果一样 %d / 不一样 %d' % (len(files), same, len(diff)))
print('找到总部的帧数 旧 %d -> 新 %d' % (hq_old, hq_new))
print('read_field+find_enemy_hq 总耗时 旧 %.1fs -> 新 %.1fs (省 %.0f%%)'
      % (t_old, t_new, 100.0 * (t_old - t_new) / max(1e-6, t_old)))
print()
print('%-26s %-26s %s' % ('帧', '旧(总部x,hp,is_hq数)', '新(总部x,hp,is_hq数)'))
for name, o, n in diff[:20]:
    print('%-26s %-26s %s' % (name[:26], str(o), str(n)))
