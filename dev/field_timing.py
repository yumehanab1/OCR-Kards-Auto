"""只读:量一次 `board.read_field` 的耗时,以及里面"类型识别"占多少。

用途:整局时间里,**每次读战场都贵**(攻击阶段每发攻击要读两次),
而 `read_field` 会对每一张卡跑一次类型图标匹配 —— 先把这个数拿准,再决定砍哪。
"""
import cv2, sys, time, glob, os
sys.path.insert(0, 'src')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import board
from ui_state import load_meta, load_templates

tpl = load_templates(load_meta('config/templates.json'))
fs = sorted(glob.glob('shots/attack_frames/*_attack.png'), key=os.path.getmtime)[-3:]
for p in fs:
    f = cv2.imread(p)
    if f is None:
        continue
    # 预热
    board.read_field(f, templates=None)
    t0 = time.perf_counter()
    fi = board.read_field(f, templates=None)
    t_notype = time.perf_counter() - t0
    t0 = time.perf_counter()
    fi2 = board.read_field(f, templates=tpl)
    t_type = time.perf_counter() - t0
    n_cards = sum(len(r.get('boxes') or []) for r in fi2['rows'])
    print('%-26s 卡 %d 张 | 不做类型 %.3fs | 带类型 %.3fs (每张卡 +%.3fs)'
          % (os.path.basename(p), n_cards, t_notype, t_type,
             (t_type - t_notype) / max(1, n_cards)))
    # 单张卡的分类耗时
    us = [u for u in (fi2.get('enemy_support') or []) + (fi2.get('our_support') or [])]
    if us:
        t0 = time.perf_counter()
        for u in us:
            board.classify_unit_type(f, u, tpl)
        dt = time.perf_counter() - t0
        print('     classify_unit_type: %d 张共 %.3fs (每张 %.3fs)'
              % (len(us), dt, dt / len(us)))
