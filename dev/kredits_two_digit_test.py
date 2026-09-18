"""
kredits_two_digit_test.py - 验证两位数费用(10-24)的读取路径。

发现(2026-09-10):两位数时 KARDS 会把数字缩小(单数字高 36px,两位数只有
25px),好和 "K/M" 徽章并排塞进那个方块。而模板归一化是"按高度缩放到 40px",
自动抵消了这个缩放 —— 所以两位数应该能直接用【单数字模板】读,
不需要为 10-24 单独录模板。本脚本就是验证这一点。

★★★ 2026-09-13 晚补:**"11" 一直被读成 "1"** —— 因为两个字形都窄,老判据
(拿字形自己的宽度当尺子)|26-10|=16 > 10*1.2=12 -> 第二个 "1" 合不进来。
所以 10 和 12 一直是对的(第二个字形胖),这个 bug 躲过了所有抽查;
"21"/"31" 落在容差边缘,同样不可靠。真值帧 18 张,见下面 REAL_FRAMES
与 `src/kredits_numeral_ab.py`(全语料 612 帧 A/B:只有这批 "11" 变了,其余一张不变)。

用法:
  .venv\\Scripts\\python.exe src\\kredits_two_digit_test.py
"""

from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2

import kredits as K
from kredits import isolate_numeral
from kredits_templates import build_templates, match_digit, normalize_glyph, split_glyphs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLATES = os.path.join(ROOT, "shots", "kredits", "samples", "plates")

# 逐个看图核对出来的真值(只列两位数,单数字已单独验证过)
KNOWN = {
    "n_32": 10,
    "n_34": 11,      # ★ 2026-09-13 晚:这一张就是被读错的那批("11 K/11")
    "n_36": 12,
}

# ★★★ 真实整帧 + 真值(每一张都逐个看图核对过,不是按文件名推的)。
# 这 9 张画面上明明白白写着 "11 K/11"(0913_182909 那张是 11 K/12,剩余 11),
# 而改之前全部被读成 1 —— 这就是交接文档里那条
# `kredits read: 11 [settled-timeout->不采信] 采样 [1,3,5,1,1,1,1,1,…]` 的由来。
#
# ★★ 2026-09-13 深夜:**这批帧必须钉住**(`shots/kredits/truth/`,是副本)。
#   起因:实机跑了几个小时之后,`shots/attack_frames/` 里的帧会被**轮转上限**
#   删掉 —— 真值帧 `0913_191731_attack.png` 就是这么没的,于是这条用例
#   (以及 CASE 46)在实机跑到一半时**突然挂了**。真值是判据的地基,
#   不能放在会被轮转的目录里。
#   ⚠️ 丢的那一张没法找回;下面留了它的名字,提醒以后别再依赖 dump 目录。
LOST_TRUTH_FRAME = "0913_191731_attack.png(被 attack_frames 的轮转删掉,已无法找回)"
REAL_FRAMES = {
    "attack_probe/0912_003610_probe.png": 11,
    "attack_probe/0912_003624_probe.png": 11,
    "attack_probe/0912_003628_movefront.png": 11,
    "deploy_drag/0913_173740_x434.png": 11,
    "deploy_drag/0913_182801_x530.png": 11,
    "deploy_drag/0913_182909_x703.png": 11,
    "mouse_field/A_asis.png": 11,
    "mouse_field/B_safepoint.png": 11,
    "kredits/samples/plates/n_34_plate.png": 11,
}
#: 钉住的真值帧目录(副本;用例一律读这里,**不读会被轮转的 dump 目录**)
TRUTH_DIR = os.path.join(ROOT, "shots", "kredits", "truth")


def read_plate(plate):
    """在 plate(费用区域整块)上跑完整读取流程。"""
    h, w = plate.shape[:2]
    numeral, mask, bbox = isolate_numeral(plate, (0, 0, w, h))
    if numeral is None:
        return None, {"reason": "提取失败"}
    segs = split_glyphs(mask)
    detail = {"size": f"{numeral.shape[1]}x{numeral.shape[0]}", "segs": len(segs)}
    if not segs or len(segs) > 2:
        detail["reason"] = f"切分出 {len(segs)} 段"
        return None, detail
    digits, scores = [], []
    for x1, x2 in segs:
        g = normalize_glyph(mask[:, x1:x2])
        d, s = match_digit(g)
        digits.append(d)
        scores.append(round(s, 3))
    detail["digits"] = digits
    detail["scores"] = scores
    if None in digits:
        return None, detail
    return int("".join(str(d) for d in digits)), detail


def main() -> int:
    build_templates(force=True)
    print()
    files = sorted(glob.glob(os.path.join(PLATES, "*.png")))
    if not files:
        print(f"没有 plate 图: {PLATES}")
        return 1

    print(f"共 {len(files)} 块费用区域\n")
    print(f"{'plate':<12}{'真值':<6}{'判读':<6}{'尺寸':<10}{'段数':<6}{'各位/分数':<26}结果")
    print("-" * 82)

    checked = 0
    wrong = 0
    for f in files:
        stem = os.path.basename(f).replace("_plate.png", "")
        plate = cv2.imread(f)
        if plate is None:
            continue
        value, detail = read_plate(plate)
        truth = KNOWN.get(stem)
        size = detail.get("size", "-")
        segs = detail.get("segs", "-")
        info = ""
        if "digits" in detail:
            info = " ".join(f"{d}({s:.2f})" for d, s in
                            zip(detail["digits"], detail["scores"]))

        verdict = ""
        if truth is not None:
            checked += 1
            ok = value == truth
            if not ok:
                wrong += 1
            verdict = "OK" if ok else f"FAIL(应为{truth})"
        else:
            verdict = "—"

        # 只打印两位数相关的,以及判读出来的非 None
        if truth is not None or value is not None:
            print(f"{stem:<12}{str(truth if truth is not None else ''):<6}"
                  f"{str(value):<6}{size:<10}{str(segs):<6}{info:<26}{verdict}")

    print("-" * 82)
    print(f"已知真值的两位数样本:{checked - wrong}/{checked} 读对")
    print()
    print("如果两位数全部读对,说明【不需要为 10-24 单独录模板】—— 单数字模板")
    print("按高度归一化后天然兼容被缩小的两位数。")

    bad = real_frame_cases()
    return 0 if (wrong == 0 and bad == 0) else 1


def real_frame_cases() -> int:
    """
    ★★★ 真实整帧上的验收(这是本轮修的那个 bug 的验收面):

      ① `read_kredits` 必须读出**真值**(11),绝不许再变成 1;
      ② 高度护栏**独立**成立:就算把合并规则退回老的,也只许给 None(不猜),
         **绝不许给出错的数字**;
      ③ 老行为要能被复现出来(证明这条用例确实钉在 bug 上,而不是钉在空气上)。
    """
    print()
    print("=" * 82)
    print("真实整帧(画面上写着 11 K/11,改之前读成 1)—— 本轮 bug 的验收面")
    print("=" * 82)
    print(f"{'帧':<44}{'真值':<6}{'老(宽度+无护栏)':<18}{'新':<8}结论")
    print("-" * 82)
    bad = 0
    reproduced_old = 0
    for rel, truth in sorted(REAL_FRAMES.items()):
        # ★ 读**钉住**的那一份(shots/kredits/truth/),不读会被轮转删掉的 dump 目录
        path = os.path.join(TRUTH_DIR, os.path.basename(rel))
        frame = cv2.imread(path)
        if frame is None:
            print(f"{rel:<44}(读不到图,跳过)")
            continue
        # ★ 整帧用 `OURS_BOX`;费用区域裁图(比如录下来的 plate)整张图就是那个区域。
        #   (判据和 `kredits_numeral_ab.py` 一致;踩过:拿 OURS_BOX 去读 62x142 的裁图
        #    会切出空图,读成 None —— 那不是"读不对",是框用错了。)
        h, w = frame.shape[:2]
        box = K.OURS_BOX if (w >= 1000 and h >= 600) else (0, 0, w, h)
        old = K.read_kredits(frame, box, merge_mode=K.MERGE_MODE_OLD,
                             height_guard=False)
        guarded_only = K.read_kredits(frame, box, merge_mode=K.MERGE_MODE_OLD)
        new = K.read_kredits(frame, box)
        if old == truth:
            print(f"{rel:<44}**老行为没复现出这个 bug(这张帧已经读对了)**")
        else:
            reproduced_old += 1
        ok = (new == truth)
        # ① 必须读出真值
        if not ok:
            bad += 1
        # ② 护栏独立成立:只加护栏(合并规则还是老的)-> 只许 None 或真值
        assert guarded_only in (None, truth), \
            f"护栏开着却给出了错的数字 {guarded_only}(真值 {truth}):{rel}"
        # ③ 明确钉住"读到 11 绝不能变成 1"
        assert new != 1, f"两位数被截断成 1(就是本轮修的那个 bug):{rel} -> {new}"
        print(f"{rel:<44}{truth:<6}{str(old):<18}{str(new):<8}"
              f"{'OK' if ok else 'FAIL'}")
    print("-" * 82)
    print(f"真值帧 {len(REAL_FRAMES)} 张:改前读成 1 的 {reproduced_old} 张,"
          f"改后全对 {len(REAL_FRAMES) - bad} 张")
    assert reproduced_old > 0, \
        "一张都没复现出老行为 —— 说明这批帧没钉在真 bug 上,用例是假的"
    return bad


if __name__ == "__main__":
    sys.exit(main())
