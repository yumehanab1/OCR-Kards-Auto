"""卡面检测 A/B:新行为(SPLIT_2D=True)vs 老行为(False)。

指标(每帧):
  · card_boxes 个数
  · rows 行数(read_field)
  · find_enemy_hq 有没有找到 + hp
  · 敌方支援线/我方支援线 张数
只看**差异帧**,并把差异最明显的几帧标出来 —— 差异本身要人眼复核。
"""
import cv2, sys, glob, os
sys.path.insert(0, 'src')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import board


def measure(path):
    f = cv2.imread(path)
    if f is None:
        return None
    out = {}
    for tag, flag in (('new', True), ('old', False)):
        board.SPLIT_2D = flag
        cb = board.card_boxes(f)
        field = board.read_field(f, templates=None)
        hq = board.find_enemy_hq(f, field=field, templates=None)
        out[tag] = {
            'boxes': len(cb),
            'rows': len(field.get('rows') or []),
            'hq': (int(hq['x']), hq.get('hp')) if hq else None,
            'ours': len(field.get('our_support') or []),
            'enemy': len(field.get('enemy_support') or []),
            'front': len(field.get('frontline') or []),
        }
    return out


files = (sorted(glob.glob('shots/attack_frames/*.png'))
         + sorted(glob.glob('shots/board_samples/*.png')))
diff, same = [], 0
tot_new_boxes = tot_old_boxes = 0
hq_new = hq_old = 0
row_new = row_old = 0
for p in files:
    m = measure(p)
    if m is None:
        continue
    tot_new_boxes += m['new']['boxes']
    tot_old_boxes += m['old']['boxes']
    hq_new += 1 if m['new']['hq'] else 0
    hq_old += 1 if m['old']['hq'] else 0
    row_new += m['new']['rows']
    row_old += m['old']['rows']
    if m['new'] != m['old']:
        diff.append((os.path.basename(p), m))
    else:
        same += 1
print('看了 %d 帧:一样 %d / 不同 %d' % (len(files), same, len(diff)))
print('card_boxes 总数  老 %d -> 新 %d' % (tot_old_boxes, tot_new_boxes))
print('找到总部的帧数   老 %d -> 新 %d' % (hq_old, hq_new))
print('行数合计         老 %d -> 新 %d' % (row_old, row_new))
print()
print('%-26s %-22s %-22s' % ('帧', '老(boxes/rows/hq)', '新(boxes/rows/hq)'))
for name, m in diff[:40]:
    o, n = m['old'], m['new']
    mark = ''
    if (n['hq'] and not o['hq']):
        mark = '  ★新找到总部'
    elif (o['hq'] and not n['hq']):
        mark = '  ⚠新丢掉总部'
    elif n['rows'] > o['rows']:
        mark = '  ★行数增加'
    elif n['rows'] < o['rows']:
        mark = '  ⚠行数减少'
    print('%-26s %-22s %-22s%s' % (name[:26],
                                   '%d/%d/%s' % (o['boxes'], o['rows'], o['hq']),
                                   '%d/%d/%s' % (n['boxes'], n['rows'], n['hq']), mark))
