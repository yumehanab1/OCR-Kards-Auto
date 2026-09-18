"""只读:拆开 `read_field` 里每一步的耗时,找出真正的热点。"""
import cv2, sys, time, glob, os
sys.path.insert(0, 'src')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import board, hq_hp
from ui_state import load_meta, load_templates

tpl = load_templates(load_meta('config/templates.json'))
p = sorted(glob.glob('shots/attack_frames/*_attack.png'), key=os.path.getmtime)[-1]
f = cv2.imread(p)
print('帧', os.path.basename(p))
board.read_field(f, templates=tpl)      # 预热


def clock(fn, n=3):
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t0) / n


boxes = board.merged_card_boxes(f)
rows = board.rows_from_boxes(boxes)
print('  merged_card_boxes : %.3fs' % clock(lambda: board.merged_card_boxes(f)))
print('  card_boxes        : %.3fs' % clock(lambda: board.card_boxes(f)))
print('  badge_boxes       : %.3fs' % clock(lambda: board.badge_boxes(f)))
print('  rows_from_boxes   : %.3fs (%.4fs 一下,可忽略)'
      % (clock(lambda: board.rows_from_boxes(boxes)), 0))
print('  rows=%d, 卡=%d' % (len(rows), sum(len(r['boxes']) for r in rows)))

# 每张卡的总部判定:hq_hp.read vs _ocr_big_number
targets = [b for i, r in enumerate(rows) if i in (0, len(rows) - 1) for b in r['boxes']]
print('  总部候选行里的卡 %d 张' % len(targets))
t0 = time.perf_counter()
ok = 0
for b in targets:
    if hq_hp.read(f, b) is not None:
        ok += 1
dt_shield = time.perf_counter() - t0
t0 = time.perf_counter()
for b in targets:
    board._ocr_big_number(f, b)
dt_ocr = time.perf_counter() - t0
print('  hq_hp.read 全部     : %.3fs (命中 %d/%d,每张 %.3fs)'
      % (dt_shield, ok, len(targets), dt_shield / max(1, len(targets))))
print('  _ocr_big_number 全部: %.3fs (每张 %.3fs)  <- 盾牌失败才走的兜底'
      % (dt_ocr, dt_ocr / max(1, len(targets))))
print()
print('  read_field 总计     : %.3fs' % clock(lambda: board.read_field(f, templates=tpl), 2))
