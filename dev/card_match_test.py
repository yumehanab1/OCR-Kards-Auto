"""
card_match_test.py - 离线单测:卡名匹配 / 费用兜底 / 图像指纹(不需要游戏)。

覆盖的每一条都对应 PROJECT_STATE.md 里踩过的坑:
  第 33 条  描述里的"攻击"被当成卡名 -> 必须不命中
  第 35 条  纯英文+数字卡名读不出     -> 交给费用徽章兜底 + 指纹库
  第 37 条  2 字卡名("强袭")被长度限制卡住 -> 去噪声后要能命中

另外把 shots/diffdiag 里的【真实悬停帧】跑一遍回归,打印每张牌
"OCR 读到什么 -> 判成什么",这是离线能拿到的最强证据。

用法:
  .venv\\Scripts\\python.exe src\\card_match_test.py
  .venv\\Scripts\\python.exe src\\card_match_test.py --frames   # 只跑真实帧回归
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2

import card_match as cm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (OCR 原文, 期望卡名 or None, 说明)
NAME_CASES = [
    # ---- 精确 ----
    ("强袭", "强袭", "2 字卡名精确命中"),
    ("血红镰刀", "血红镰刀", "4 字卡名精确命中"),
    ("Pak 40 反坦克炮", "Pak 40 反坦克炮", "带空格,归一化后精确命中"),
    # ---- 第 37 条:去噪声 ----
    ("强袭★", "强袭", "★ 装饰符"),
    ("强袭 ", "强袭", "尾随空格"),
    ("强袭指令", "强袭", "OCR 把类型「指令」拼在卡名后面"),
    ("强袭.", "强袭", "标点噪声"),
    # ---- 长卡名 + 噪声 ----
    ("喷烟者42型+", "喷烟者 42 型", "+ 噪声,库里名字带空格"),
    ("105毫米轻型榴弹炮+D2", "105 毫米轻型榴弹炮", "库名带空格 + 角标噪声"),
    ("Pak40反坦克炮+", "Pak 40 反坦克炮", "OCR 漏空格 + 噪声"),
    ("T-34-85 1945", "T-34-85 1945", "纯英文数字卡名(完整读到时)"),
    ("T-34-851945", "T-34-85 1945", "去掉空格后要能对上"),
    # ---- 第 33 条:描述文字绝不能命中 ----
    ("伤害，且能攻击被守护的单", None, "描述残句含「攻击」这个 2 字卡名"),
    ("炮兵在攻击时不会受到反击", None, "描述整句含「攻击」"),
    ("使用时，一次性触发效果，", None, "指令卡的说明文字"),
    ("部署效果会在单位被部署时", None, "关键字说明"),
    ("结束回合", None, "UI 按钮"),
    ("友方回合：", None, "HUD 回合提示(实测挡住了卡名)"),
    ("yume_hanabi", None, "玩家名"),
    ("STALINGRAD", None, "战役名"),
    ("", None, "空字符串"),
    # ---- 短 token 不许乱匹配 ----
    ("18", None, "HUD 回合数字"),
    ("3K", None, "费用徽章不是卡名"),
]

# 费用徽章 OCR 行 {(text, conf): 期望值}
def _line(text, conf=0.8, x=360, y=330):
    return {"text": text, "conf": conf, "x": x, "y": y, "w": 40, "h": 30,
            "cx": x + 20, "cy": y + 15}


COST_CASES = [
    ([_line("3K")], 3, "单个 3K"),
    ([_line("2K")], 2, "单个 2K"),
    ([_line("10K")], 10, "两位数"),
    ([_line("24K")], 24, "上限 24"),
    ([_line("3K"), _line("2K")], None, "两个不同值 -> 不猜"),
    ([_line("3K"), _line("3K")], 3, "两个相同值 -> 可以信"),
    ([_line("3K", conf=0.3)], None, "置信度过低 -> 不用"),
    ([_line("喷烟者42型+")], None, "卡名行里没有行首 NK"),
    ([_line("105毫米轻型榴弹炮+02")], None, "行首是 105 但不是 NK"),
    ([_line("3Kredits")], 3, "带 Kredits 后缀"),
]


def run_name_cases() -> bool:
    print("=" * 92)
    print("卡名匹配(纯函数,不需要游戏)")
    print("=" * 92)
    print(f"{'结果':<6}{'OCR 原文':<26}{'期望':<20}{'实得':<20}命中级别")
    print("-" * 92)
    ok_all = True
    for text, want, note in NAME_CASES:
        got, tier = cm.match_name(text, debug=True)
        ok = got == want
        ok_all &= ok
        print(f"{'OK ' if ok else 'FAIL':<6}{text!r:<26}{str(want):<20}"
              f"{str(got):<20}{tier}   {note}")
    print("-" * 92)
    print(f"卡名匹配 {sum(1 for t, w, n in NAME_CASES if cm.match_name(t) == w)}"
          f"/{len(NAME_CASES)}")
    return ok_all


def run_cost_cases() -> bool:
    print()
    print("=" * 92)
    print("费用徽章兜底(卡名读不出时用)")
    print("=" * 92)
    ok_all = True
    for lines, want, note in COST_CASES:
        got, ev = cm.read_cost_badge(lines)
        ok = got == want
        ok_all &= ok
        txt = lines[0]["text"] if lines else ""
        print(f"{'OK ' if ok else 'FAIL':<6}{txt!r:<30}{str(want):<8}"
              f"{str(got):<8}{ev:<20}{note}")
    print(f"费用兜底 {sum(1 for l, w, n in COST_CASES if cm.read_cost_badge(l)[0] == w)}"
          f"/{len(COST_CASES)}")
    return ok_all


def run_hash_cases() -> bool:
    print()
    print("=" * 92)
    print("放大卡图像指纹(自动学习 + 查表)")
    print("=" * 92)
    import numpy as np

    # 用"有结构的图"当卡面,而不是纯随机噪声 —— 纯随机图的 dHash 本身就不稳定,
    # 它衡量不了这套指纹在真实截图上的表现。真实卡面是大块美术 + 文字。
    h, w = 300, 220
    yy, xx = np.mgrid[0:h, 0:w]
    def card(seed, base):
        rng = np.random.default_rng(seed)
        blob = np.zeros((h, w, 3), np.float64)
        for _ in range(6):                      # 几块大色块
            cy, cx = rng.integers(0, h), rng.integers(0, w)
            r = rng.integers(40, 120)
            m = ((yy - cy) ** 2 + (xx - cx) ** 2) < r * r
            blob[m] += rng.integers(0, 255, 3)
        blob += base
        return np.clip(blob, 0, 255).astype(np.uint8)

    card_a = card(1, 20)
    card_b = card(2, 90)
    # 同一张卡的"再拍一帧":轻微模糊 + 亮度抖动(实测同一张卡两次截图的差异量级)
    smooth = cv2.GaussianBlur(card_a, (5, 5), 0).astype(np.int16)
    noisy = np.clip(smooth + 4, 0, 255).astype(np.uint8)

    bits_a = cm.dhash(card_a)
    bits_b = cm.dhash(card_b)
    bits_noisy = cm.dhash(noisy)
    d_same = cm.hamming(cm.hash_to_hex(bits_a), cm.hash_to_hex(bits_noisy))
    d_diff = cm.hamming(cm.hash_to_hex(bits_a), cm.hash_to_hex(bits_b))
    print(f"  同一张卡(轻微模糊+亮度抖动) -> 汉明距离 {d_same}")
    print(f"  两张不同的卡                  -> 汉明距离 {d_diff}")
    ok_same = d_same <= 12
    ok_diff = d_diff > 12

    db = cm.CardHashDB(path=os.path.join(ROOT, "shots", "card_hashes_test.json"))
    db.entries = []
    db.learn(bits_a, "测试卡甲", "tank")
    db.learn(bits_b, "测试卡乙", "infantry")
    n1, t1, dd1 = db.lookup(bits_noisy)
    n2, t2, dd2 = db.lookup(bits_b)
    print(f"  噪声版甲 -> 认出 {n1!r} ({t1}) 距离 {dd1}")
    print(f"  原版乙   -> 认出 {n2!r} ({t2}) 距离 {dd2}")
    ok_recall = n1 == "测试卡甲" and n2 == "测试卡乙"
    # 库里没有的东西必须认不出(返回 None),不能乱认
    unknown = card(99, 200)
    n3, _, dd3 = db.lookup(cm.dhash(unknown))
    ok_reject = n3 is None
    print(f"  库里没有的卡 -> {n3!r} 距离 {dd3}(必须是 None)")
    for cond, label in ((ok_same, "同卡距离小"), (ok_diff, "异卡距离大"),
                        (ok_recall, "能认出"), (ok_reject, "不乱认")):
        print(f"  {'OK ' if cond else 'FAIL'} {label}")
    return ok_same and ok_diff and ok_recall and ok_reject


def run_frame_regression() -> bool:
    """
    真实悬停帧回归:把 shots/diffdiag 的 6 张 hover 图跑一遍,
    打印 OCR 行 -> 匹配结果,让人一眼看出读对/读错/读不出。
    """
    import hand_scanner_v2 as hsv
    from hover_card_reader import _ocr

    print()
    print("=" * 92)
    print("真实悬停帧回归(shots/diffdiag,离线)", )
    print("=" * 92)
    base_path = os.path.join(ROOT, "shots", "diffdiag", "base1.png")
    base = cv2.imread(base_path)
    if base is None:
        print("  缺 base1.png,跳过")
        return True
    hsv._load_db()
    zone = hsv.NAME_ZONE_MAX_Y
    for x in (388, 460, 520, 592, 640, 700):
        p = os.path.join(ROOT, "shots", "diffdiag", f"hover_x{x}.png")
        hov = cv2.imread(p)
        if hov is None:
            continue
        box = hsv.diff_bbox(base, hov)
        print(f"\n--- x={x}  diff box={box} ---")
        if box is None:
            continue
        bx, by, bw, bh = box
        region = hov[by:by + bh, bx:bx + bw]
        lines = _ocr(region)
        print(f"  {'整帧y':>6}{'h':>5}{'conf':>7}  {'匹配':<20} 原文")
        for ln in sorted(lines, key=lambda l: l["y"]):
            fy = ln["y"] + by
            keep = fy < zone
            nm, tier = cm.match_name(ln["text"], debug=True)
            tag = "" if keep else "(手牌区,丢弃)"
            if nm or keep:
                print(f"  {fy:>6.0f}{ln['h']:>5.0f}{ln['conf']:>7.2f}  "
                      f"{str(nm):<20} {ln['text']!r} {tag}"
                      f"{'' if not nm else '  <- ' + tier}")
        cost, ev = cm.read_cost_badge(lines)
        print(f"  => 费用徽章兜底读到: {cost} ({ev})")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", action="store_true", help="只跑真实帧回归")
    args = ap.parse_args()
    ok = True
    if not args.frames:
        ok &= run_name_cases()
        ok &= run_cost_cases()
        ok &= run_hash_cases()
    run_frame_regression()
    print()
    print("=" * 92)
    print("全部通过" if ok else "存在失败项")
    print("=" * 92)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
