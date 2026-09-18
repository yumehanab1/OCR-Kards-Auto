"""把 A/B 差异帧画出来:蓝=老行为检出的框,绿=新行为检出的框。人眼复核"丢掉的是不是真卡"。
"""
import cv2, sys, os
sys.path.insert(0, 'src')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import board

FRAMES = ['shots/attack_frames/0912_192728_attack.png',
          'shots/attack_frames/0912_192745_after.png',
          'shots/board_samples/0911_122530_004.png',
          'shots/attack_frames/0912_204422_after.png',
          'shots/attack_frames/0912_205326_attack.png',
          'shots/attack_frames/0912_204135_attack.png',
          'shots/attack_frames/0912_205607_attack.png']
OUT = 'shots/card_ab'
os.makedirs(OUT, exist_ok=True)

for p in FRAMES:
    f = cv2.imread(p)
    if f is None:
        continue
    board.SPLIT_2D = False
    old = board.card_boxes(f)
    board.SPLIT_2D = True
    new = board.card_boxes(f)
    img = f.copy()
    for b in old:
        cv2.rectangle(img, (b['x'], b['y']), (b['x'] + b['w'], b['y'] + b['h']),
                      (255, 0, 0), 2)
        cv2.putText(img, 'O', (b['x'] + 3, b['y'] + 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 0, 0), 2)
    for b in new:
        cv2.rectangle(img, (b['x'], b['y']), (b['x'] + b['w'], b['y'] + b['h']),
                      (0, 255, 0), 2)
        cv2.putText(img, 'N', (b['x'] + b['w'] - 16, b['y'] + b['h'] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
    name = os.path.basename(p).replace('.png', '')
    cv2.imwrite(os.path.join(OUT, name + '_ab.png'), img)
    print('%-28s 老 %d 个框 / 新 %d 个框 -> %s' % (name, len(old), len(new),
                                                os.path.join(OUT, name + '_ab.png')))
    board.SPLIT_2D = True
