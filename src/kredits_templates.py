"""
kredits_templates.py - Kredits 数字模板库 + 匹配器(精确读费用)。

背景(见 kredits.py):这种风格化模板体数字 RapidOCR 读不出来,所以走模板匹配。
0-9 十个字形已录齐并逐个看图核对(2026-09-10),锚定在 shots/kredits/samples_r1/。

字形来源与判定:
  #00=0 #01=1 #02=2 #03=3 #04=4 #05=5 #06=6 #07=7 #08=8 #09=9
  (#10/#11/#13/#15 是被 HUD 墨迹切碎或重复的残片,不用)

匹配方法:
  1. 取字形掩码的紧致外接框,按高度归一化到固定大小(保持宽高比)
  2. 与每个数字模板做归一化互相关(cv2.matchTemplate TM_CCOEFF_NORMED)
  3. 取最高分;低于阈值则拒识(返回 None,宁可读不出也不要读错)

两位数(10-24):
  KARDS 上限 24,所以最多两位。**关键:两位数时游戏会把数字整体缩小**
  (实测单数字高 36px,两位数只有 25px),好和 "K/M" 徽章并排塞进同一个方块。
  因为归一化是"按高度缩放到固定高度",这个缩小被自动抵消 —— 所以
  **两位数不需要单独录模板**,切成两个字形后用单数字模板就能读。
  实测:10 -> "1"(0.92) "0"(0.89);12 -> "1"(0.92) "2"(0.93)。
  验证脚本:src/kredits_two_digit_test.py

用法:
  .venv\\Scripts\\python.exe src\\kredits_templates.py          # 自检:用样例互相匹配
"""

from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2
import cv_io  # noqa: F401  (开关:让 cv2 认中文路径,见 cv_io.py)
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 锚定样例:逐个看图核对过映射的那一批,固定不动,是模板库的唯一真源。
# (kredits_record.py 录的新样例放在 shots/kredits/samples/,不会再覆盖这里)
ANCHOR_SAMPLES = os.path.join(ROOT, "shots", "kredits", "samples_r1")
# 导出的归一化模板,仅供人工查看
TEMPLATES_DIR = os.path.join(ROOT, "shots", "kredits", "templates")

# 样例 -> 数字值。
# 这一栏是 2026-09-10 录制时【逐个看图核对】出来的,不是按录制顺序推的:
# 老版提取逻辑会把被墨迹切碎的字形丢掉、还会把两位数跟 K/M 徽章粘在一起,
# 所以录制序号跟数字值并不一一对应(例如 n_06 其实是 5、n_07 是 6)。
#   n_05 / n_11 / n_13 / n_15 是被切碎或重复的残片,不能当模板。
SAMPLE_TO_DIGIT = {
    "n_00": 0, "n_01": 1, "n_02": 2, "n_03": 3, "n_04": 4,
    "n_06": 5, "n_07": 6, "n_08": 7, "n_09": 8, "n_10": 9,
}

# 两位数(10-24)【无需】单独模板:游戏会把两位数缩小,而按高度归一化自动抵消
# 了这个缩放,切成两个字形后用上面的单数字模板即可。实测 10、12 均正确
# (见 kredits_two_digit_test.py)。第二轮录制(samples/)里的 n_32=10、n_36=12
# 就是那两个验证样本。

NORM_H = 40          # 归一化高度
MATCH_MIN_SCORE = 0.72   # 低于此分拒识

_TEMPLATES: dict = {}


def _tight(mask: np.ndarray):
    """裁到掩码的紧致外接框;全空返回 None。"""
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return None
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def normalize_glyph(mask: np.ndarray, height: int = NORM_H):
    """
    把字形掩码归一化:紧致裁剪 -> 按高度缩放(保持宽高比)。
    返回 (float32 灰度图) 或 None。
    """
    tight = _tight(mask)
    if tight is None or tight.shape[0] < 8:
        return None
    scale = height / float(tight.shape[0])
    w = max(1, int(round(tight.shape[1] * scale)))
    resized = cv2.resize(tight, (w, height), interpolation=cv2.INTER_AREA)
    return resized.astype(np.float32)


def build_templates(force: bool = False) -> dict:
    """从锚定样例目录载入 0-9 模板。返回 {digit: [归一化字形, ...]}。"""
    global _TEMPLATES
    if _TEMPLATES and not force:
        return _TEMPLATES

    bank: dict = {}
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    missing = []
    for stem, digit in sorted(SAMPLE_TO_DIGIT.items(), key=lambda kv: kv[1]):
        mask_path = os.path.join(ANCHOR_SAMPLES, f"{stem}_mask.png")
        mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
        if mask is None:
            missing.append(f"{stem}({digit})")
            continue
        norm = normalize_glyph(mask)
        if norm is None:
            missing.append(f"{stem}({digit}, 太小)")
            continue
        bank.setdefault(digit, []).append(norm)
        cv2.imwrite(os.path.join(TEMPLATES_DIR, f"digit_{digit}.png"),
                    norm.astype(np.uint8))

    if missing:
        print(f"kredits_templates: 缺锚定样例 {', '.join(missing)} "
              f"(目录 {ANCHOR_SAMPLES})")
    _TEMPLATES = bank
    print(f"kredits_templates: 载入 {len(bank)} 个数字模板 "
          f"{sorted(bank)}")
    return bank


def score_against(glyph: np.ndarray, template: np.ndarray) -> float:
    """
    一个字形对一个模板的相似度(0-1)。

    先按宽度缩放模板到字形宽度,再用 TM_CCOEFF_NORMED。宽度差太多直接低分,
    避免把一个瘦'1'和胖'0'硬比。
    """
    if glyph is None or template is None:
        return -1.0
    gh, gw = glyph.shape
    th, tw = template.shape
    if gh != th:
        return -1.0
    ratio = min(gw, tw) / max(gw, tw)
    if ratio < 0.5:                     # 宽度差一倍以上,基本不是同一个数字
        return -1.0 * (1.0 - ratio)
    t = cv2.resize(template, (gw, gh), interpolation=cv2.INTER_AREA)
    res = cv2.matchTemplate(glyph, t, cv2.TM_CCOEFF_NORMED)
    base = float(res.max())
    return base * (0.6 + 0.4 * ratio)   # 宽度越接近越可信


def match_digit(glyph: np.ndarray, bank: dict | None = None):
    """
    返回 (digit, score) 或 (None, best_score)。分数低于阈值返回 None。
    """
    bank = bank if bank is not None else build_templates()
    best_digit, best_score = None, -1.0
    for digit, templates in bank.items():
        for t in templates:
            s = score_against(glyph, t)
            if s > best_score:
                best_score, best_digit = s, digit
    if best_score < MATCH_MIN_SCORE:
        return None, best_score
    return best_digit, best_score


def split_glyphs(mask: np.ndarray):
    """
    把数字区掩码按竖直空白切成最多两个字形的列表(用于两位数)。
    返回 [(x1,x2), ...] 或 [] 。
    """
    tight = _tight(mask)
    if tight is None:
        return []
    col_has = (tight > 0).sum(axis=0) > 0
    segments = []
    start = None
    for i, has in enumerate(col_has):
        if has and start is None:
            start = i
        elif not has and start is not None:
            segments.append((start, i))
            start = None
    if start is not None:
        segments.append((start, len(col_has)))
    return [s for s in segments if s[1] - s[0] >= 3]


def read_our_kredits(frame, box=None) -> tuple:
    """
    读我方当前费用。
    返回 (value_or_None, detail_dict)。
    """
    from kredits import OURS_BOX, isolate_numeral

    box = box or OURS_BOX
    numeral, mask, bbox = isolate_numeral(frame, box)
    if numeral is None:
        return None, {"reason": "no numeral"}

    segs = split_glyphs(mask)
    detail = {"bbox": bbox, "segments": len(segs)}

    if len(segs) == 1:
        x1, x2 = segs[0]
        g = normalize_glyph(mask[:, x1:x2])
        d, s = match_digit(g)
        detail.update({"digits": [d], "scores": [round(s, 3)]})
        return (d if d is not None else None), detail

    if len(segs) == 2:
        digits, scores = [], []
        for x1, x2 in segs:
            g = normalize_glyph(mask[:, x1:x2])
            d, s = match_digit(g)
            digits.append(d)
            scores.append(round(s, 3))
        detail.update({"digits": digits, "scores": scores})
        if None in digits:
            return None, detail
        return int(f"{digits[0]}{digits[1]}"), detail

    detail["reason"] = f"unexpected segment count {len(segs)}"
    return None, detail


def _selfcheck() -> int:
    bank = build_templates(force=True)
    print()
    print("留一验证:每个样例只用【其它数字】的模板来判读")
    print("(自己匹配自己一定是 1.000,所以必须把自己那一类排除)")
    print(f"{'样例':<8}{'真值':<6}{'判读':<6}{'分数':<8}{'次优':<12}结果")
    print("-" * 64)
    bad = 0
    for stem, digit in sorted(SAMPLE_TO_DIGIT.items(), key=lambda kv: kv[1]):
        mask = cv2.imread(os.path.join(ANCHOR_SAMPLES, f"{stem}_mask.png"),
                          cv2.IMREAD_GRAYSCALE)
        if mask is None:
            print(f"{stem:<8}{digit:<6}(无掩码)")
            continue
        g = normalize_glyph(mask)
        scores = {}
        for d, temps in bank.items():
            if d == digit:          # 留一:排除自己那一类
                continue
            scores[d] = max(score_against(g, t) for t in temps)
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        top_d, top_s = ranked[0]
        second = ranked[1] if len(ranked) > 1 else (None, -1.0)
        # 留一下正确行为是"判读不等于真值,且被阈值拒识"
        rejected = top_s < MATCH_MIN_SCORE
        ok = rejected
        if not ok:
            bad += 1
        print(f"{stem:<8}{digit:<6}{str(top_d):<6}{top_s:<8.3f}"
              f"{str(second[0])}:{second[1]:<7.3f}"
              f"{'拒识(正确)' if rejected else 'FAIL: 误判成 ' + str(top_d)}")
    print("-" * 64)
    print(f"{len(SAMPLE_TO_DIGIT) - bad}/{len(SAMPLE_TO_DIGIT)} 正确拒识")
    print("期望:全部拒识 —— 说明每个数字都靠自己的模板区分,没有互相混淆。")

    print()
    print("完整数字区读取测试(shots/kredits/extracted 里提取好的字形):")
    ex_dir = os.path.join(ROOT, "shots", "kredits", "extracted")
    files = sorted(glob.glob(os.path.join(ex_dir, "*.png")))
    files = [f for f in files if not f.endswith("_plate.png")]
    seen = {}
    for f in files[:200]:
        img = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        g = normalize_glyph(img)
        d, s = match_digit(g)
        seen.setdefault((d, round(s, 2)), 0)
        seen[(d, round(s, 2))] += 1
    for (d, s), n in sorted(seen.items(), key=lambda kv: -kv[1])[:10]:
        print(f"    {n:>4} 帧 -> 判读 {d} (分 {s})")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(_selfcheck())
