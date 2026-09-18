"""只读:在本局存帧上核对"战斗机拦截"这条规则的**输入侧**。

问题:这一局我方没有轰炸机 -> 规则没机会触发。那么至少要确认:
  ① 敌方支援线的**类型**读得对(有没有战斗机?);
  ② 我方有没有轰炸机(哪怕在场上);
  ③ 有没有任何一帧同时满足"我方有轰炸机 + 敌方支援线有战斗机"(= 规则该触发的帧)。
"""
import cv2, sys, glob, os
sys.path.insert(0, 'src')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import board
from ui_state import load_meta, load_templates

tpl = load_templates(load_meta('config/templates.json'))
files = sorted(glob.glob('shots/attack_frames/*_after.png')) + \
        sorted(glob.glob('shots/attack_frames/*_attack.png'))
files = sorted(files, key=os.path.getmtime)[-24:]
enemy_types, our_types, scenarios = {}, {}, []
for p in files:
    f = cv2.imread(p)
    if f is None:
        continue
    fi = board.read_field(f, templates=tpl)
    es = [u.get('type') for u in (fi.get('enemy_support') or []) if not u.get('is_hq')]
    os_ = [u.get('type') for u in (fi.get('our_support') or []) if not u.get('is_hq')]
    fl = [u.get('type') for u in (fi.get('frontline') or []) if not u.get('is_hq')]
    for t in es:
        enemy_types[t] = enemy_types.get(t, 0) + 1
    for t in os_ + fl:
        our_types[t] = our_types.get(t, 0) + 1
    hit = ('bomber' in (os_ + fl)) and ('fighter' in es)
    if hit:
        scenarios.append((os.path.basename(p), es, os_ + fl))
print('看了 %d 帧' % len(files))
print('敌方支援线上读到的类型分布:', enemy_types)
print('我方场上读到的类型分布    :', our_types)
print('★ 同时满足"我方有轰炸机 + 敌方支援线有战斗机"的帧:', len(scenarios))
for s in scenarios[:6]:
    print('   ', s)
print()
print('结论:', '规则没机会触发(我方这一局没有轰炸机)' if not scenarios
      else '有该触发的帧 -> 需要看日志里有没有拦截那一行')
