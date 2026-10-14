"""
hq_hp.py - 读【总部血量】(盾牌里那个数字)。★ 2026-09-12 新增。

为什么不能用原来那条路(用户提出、实机量过):
    `board.find_enemy_hq` 原来是"对敌方那一行整行 OCR,找 h>=24 的纯数字"。
    实测**时好时坏**:20 张存帧里只有 **3 张**读得到;
    而**单个数字**(7 / 8 / 2)在这个分辨率下 RapidOCR **一个都读不出来** ——
    把盾牌裁出来放大 3x/5x、加白边再 OCR 都试过,还是空。
    用户补充:**总部血量是白 / 红 / 绿三种颜色,覆盖 1~99**。

怎么做(和 kredits 那一套同样的思路:结构化定位 + 归一化模板匹配):
    ① **定位盾牌**:总部卡**下半部**那个深色圆角方块 ——
       暗连通域里 "尺寸 28~80 见方 + 实心度>=0.55 + **横向居中**" 的那个;
    ② **抠字形**:盾牌内部取"数字像素" = `(V > max(110, 底色+22)) | (S > 100)`
       —— ★ 必须**亮或饱和取或**:白字亮但不饱和、红字饱和但不亮、绿字两者都有,
       只用亮度会把红字整类漏掉(和 §7 第 58 条徽章数字同一个坑);
       连通域 + 尺寸过滤 -> 1~2 个字形(= 1~99),按 x 排序;
    ③ **认数字**:每个字形归一化到 32x32,与模板库(`config/hq_hp_digits/<数字>/*.png`)
       做 `TM_CCOEFF_NORMED`,取最高分;低于 `MATCH_MIN` 判"读不出"(返回 None,
       **不许瞎猜** —— 血量读错会让"打中了没有"这条判据撒谎);
    ④ **颜色状态**:按字形像素的 HSV 均值判白/红/绿,一起返回(用户说有三种状态)。

★ 模板库是**人眼标定**出来的(`src/hq_hp_probe.py --action cluster` 聚类 -> 我逐个看图贴标签),
  每个数字可以有多张原型(同一数字的红色版和白色版字形不完全一样)。
  ★ 数字 `5` 的原型是**从 kredits 模板库借的**(实机语料里暂时没出现过 5):
  两套字形是同一个字体族(拿 9 个已知数字交叉验证过,kredits 银行的 argmax 全部与肉眼一致),
  但**它属于"借来的",等实机上真的读到 5 时要回来复核**。
"""
from __future__ import annotations

import glob
import os

import cv2
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANK_DIR = os.path.join(PROJECT_ROOT, "config", "hq_hp_digits")

NORM = 32                  # 模板归一化尺寸
MATCH_MIN = 0.45           # 低于这个分 -> 读不出(宁可 None,不许瞎猜)
AMBIGUOUS_MARGIN = 0.10    # 第一名与第二名(不同数字)差不到这个 -> 判"有歧义",去 OCR 复核
CONFIDENT_SCORE = 0.85     # 最高分低于这个 -> 也算"不够有把握",去 OCR 复核
#   ★ 为什么需要第二条:模板库对某些数字很薄(数字 3 只有 1 个原型)。
#     拿那一帧做**留一验证**时,'3' 在库里一个原型都不剩,于是它被认成 '8' @0.747 ——
#     而"次高分"是同一个数字 8 的另一个原型,不同数字之间差得很远 -> 靠 margin 抓不到。
#     所以再加一条"分数本身不够高"的触发条件。两条都是**触发 OCR 复核**,不是直接判死。

SHIELD_DARK_V = 120        # 盾牌是"暗"的(V < 这个)
SHIELD_W_MIN, SHIELD_W_MAX = 28, 80
SHIELD_H_MIN, SHIELD_H_MAX = 28, 80
SHIELD_FILL_MIN = 0.55     # 盾牌是实心方块
SHIELD_CENTER_TOL = 0.28   # 横向必须居中(相对卡宽)

GLYPH_W_MIN, GLYPH_W_MAX = 4, 40
GLYPH_H_MIN, GLYPH_H_MAX = 11, 44
GLYPH_AREA_MIN = 25
GLYPH_FILL_MIN = 0.25

SAT_DIGIT = 100            # 饱和像素也算"数字像素"(红字/绿字)
V_FLOOR = 110              # 亮像素的下限(白字)
V_REL_DELTA = 22           # 相对盾牌底色的增量

COLOR_WHITE_MAX_S = 70     # S 低于这个 -> 白
COLOR_RED_HUE = (165, 15)  # 红:色相绕 0
COLOR_GREEN_HUE = (35, 90)

_BANK = None


def bank(exclude=None):
    """
    载入数字模板库:`{数字: [32x32 灰度原型, ...]}`。载一次缓存。

    exclude: 子串(通常是帧名)—— 名字里含它的原型会被**跳过**。
    ★★ 这是给"**留一验证**"用的(`hq_hp_test.py`):用某一帧当测试样本时,
      必须把它自己贡献的原型从模板库里拿掉,否则就是拿训练集当测试集,
      分数会全是 1.00 —— 那种"验证"什么也证明不了。
    """
    global _BANK
    if _BANK is None:
        out = {}
        if os.path.isdir(BANK_DIR):
            for d in sorted(os.listdir(BANK_DIR)):
                p = os.path.join(BANK_DIR, d)
                if not (os.path.isdir(p) and d.isdigit()):
                    continue
                protos = []
                for f in sorted(glob.glob(os.path.join(p, "*.png"))):
                    im = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
                    if im is None:
                        continue
                    protos.append((os.path.basename(f),
                                   cv2.resize(im, (NORM, NORM),
                                            interpolation=cv2.INTER_AREA)))
                if protos:
                    out[int(d)] = protos
        _BANK = out
    if exclude is None:
        return _BANK
    return {d: [p for p in protos if exclude not in p[0]]
            for d, protos in _BANK.items()}


def find_shield(img, card):
    """
    在卡片的**下半部**找那个深色盾牌,返回 (盾牌图, 卡内 bbox) 或 (None, None)。

    ★ 判据是**结构化**的(不按比例硬切):暗块 + 够方 + 实心 + **横向居中**。
      实测盾牌 43x46、居中;卡面美术切出来的暗块要么不实心、要么不居中。
    """
    x, y, w, h = int(card["x"]), int(card["y"]), int(card["w"]), int(card["h"])
    y_low = y + int(h * 0.50)
    low = img[y_low: y + h + 2, x: x + w]
    if low.size == 0:
        return None, None
    V = cv2.cvtColor(low, cv2.COLOR_BGR2HSV)[:, :, 2]
    dark = (V < SHIELD_DARK_V).astype(np.uint8)
    n, _lab, st, _ = cv2.connectedComponentsWithStats(dark, 8)
    best = None
    for i in range(1, n):
        bx, by, bw, bh, area = (int(v) for v in st[i])
        if not (SHIELD_W_MIN <= bw <= SHIELD_W_MAX
                and SHIELD_H_MIN <= bh <= SHIELD_H_MAX):
            continue
        if area / float(bw * bh) < SHIELD_FILL_MIN:
            continue
        if abs(bx + bw / 2 - low.shape[1] / 2) > SHIELD_CENTER_TOL * low.shape[1]:
            continue
        if best is None or area > best[4]:
            best = (bx, by, bw, bh, area)
    if best is None:
        return None, None
    bx, by, bw, bh, _ = best
    x0, y0 = max(0, bx - 2), max(0, by - 2)
    x1, y1 = min(low.shape[1], bx + bw + 2), min(low.shape[0], by + bh + 2)
    # ★ 返回**整帧坐标**(调用方要拿它算"打到哪一点"),不是卡内相对坐标 ——
    #   返回相对坐标的话外面还得自己换算,很容易错(§7 第 39 条那类坐标坑)。
    return low[y0:y1, x0:x1], (x + x0, y_low + y0, x1 - x0, y1 - y0)


def extract_glyphs(shield):
    """
    从盾牌里抠出字形(1~2 个 = 1~99),按 x 排序。
    返回 [{img, x, y, w, h, n, s, v, hue}](`img` 是 BGR 小图)。
    """
    hsv = cv2.cvtColor(shield, cv2.COLOR_BGR2HSV)
    V = hsv[:, :, 2].astype(float)
    S = hsv[:, :, 1].astype(float)
    bg = float(np.percentile(V, 55))              # 盾牌底色(暗)
    mask = ((V > max(float(V_FLOOR), bg + V_REL_DELTA)) | (S > SAT_DIGIT))
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE,
                            np.ones((2, 2), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        bx, by, bw, bh, area = (int(v) for v in st[i])
        if not (GLYPH_W_MIN <= bw <= GLYPH_W_MAX
                and GLYPH_H_MIN <= bh <= GLYPH_H_MAX):
            continue
        if area < GLYPH_AREA_MIN or area / float(bw * bh) < GLYPH_FILL_MIN:
            continue
        gm = (lab[by:by + bh, bx:bx + bw] == i)
        px = shield[by:by + bh, bx:bx + bw][gm]
        hh = cv2.cvtColor(px.reshape(-1, 1, 3), cv2.COLOR_BGR2HSV).reshape(-1, 3)
        out.append({"img": shield[by:by + bh, bx:bx + bw].copy(),
                    "x": bx, "y": by, "w": bw, "h": bh, "n": int(area),
                    "s": float(hh[:, 1].mean()), "v": float(hh[:, 2].mean()),
                    "hue": float(hh[:, 0].mean())})
    out.sort(key=lambda g: g["x"])
    return out


def _match_digit(glyph_img, bank_):
    """
    把一个字形和模板库比。返回 `(数字, 最高分, 次高分(另一个数字), 次高数字)`。

    ★ 为什么要带**次高分**:模板库对某些数字很薄(实测数字 3 只采到 1 个原型),
      这时"3"和"8"这种圆形状的分数会咬得很近 —— 谁赢取决于噪声。
      调用方据此判"这次匹配**有歧义**",去做一次 OCR 复核(见 `read`)。
    """
    g = cv2.resize(cv2.cvtColor(glyph_img, cv2.COLOR_BGR2GRAY),
                   (NORM, NORM), interpolation=cv2.INTER_AREA).astype(np.float32)
    per_digit = {}
    for d, protos in bank_.items():
        best = -2.0
        for _name, p in protos:
            s = float(cv2.matchTemplate(g, p.astype(np.float32),
                                        cv2.TM_CCOEFF_NORMED)[0, 0])
            if s > best:
                best = s
        per_digit[d] = best
    if not per_digit:
        return None, -2.0, -2.0, None
    order = sorted(per_digit.items(), key=lambda kv: -kv[1])
    d1, s1 = order[0]
    d2, s2 = order[1] if len(order) > 1 else (None, -2.0)
    return d1, s1, s2, d2


def _ocr_two_digits(shield):
    """
    把盾牌放大后 OCR,只要**两位数**的结果。

    ★ 为什么只信两位数:实测这个分辨率下 RapidOCR **读不出单个数字**
      (7/8/2 全部返回空,放大 3x/5x、加白边都试过),但**两位数读得很准**
      (14/20/16/11/13 逐个人眼核对过)。所以它当"歧义时的复核"用,
      单字形的情况**不用它**(用了只会拿到空)。
    """
    try:
        from hover_card_reader import _ocr
    except Exception:
        return None
    for scale in (4, 3):
        try:
            big = cv2.resize(shield, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_CUBIC)
            for ln in _ocr(big):
                t = str(ln.get("text", "")).strip()
                if t.isdigit() and len(t) == 2 and float(ln.get("conf", 0)) >= 0.5:
                    return int(t)
        except Exception:
            continue
    return None

def _color_state(glyphs):
    """按字形像素的 HSV 均值判颜色状态:white / red / green / None。"""
    if not glyphs:
        return None
    s = float(np.mean([g["s"] for g in glyphs]))
    hue = float(np.mean([g["hue"] for g in glyphs]))
    if s < COLOR_WHITE_MAX_S:
        return "white"
    lo, hi = COLOR_RED_HUE
    if hue >= lo or hue <= hi:
        return "red"
    if COLOR_GREEN_HUE[0] <= hue <= COLOR_GREEN_HUE[1]:
        return "green"
    return None


def read(frame, card, debug=False, bank_=None):
    """
    读**一张卡**上的总部血量(自己找盾牌)。

    返回 dict 或 None(读不出):
      {"hp": int, "state": "white"/"red"/"green", "score": 最低的那个字形分数,
       "n_glyphs": 几个字形, "shield_box": 盾牌在整帧里的框, "why": ...}
    ★ 任何一个字形匹配低于 `MATCH_MIN` -> 返回 None(**不许拼一个可能是错的数**)。
    bank_: 覆盖模板库(留一验证用,见 `bank()`)。None = 用全库。
    """
    if frame is None or not card:
        return None
    shield, sbox = find_shield(frame, card)
    if shield is None:
        return None
    return read_shield(shield, sbox, debug=debug, bank_=bank_)


def read_box(frame, box, debug=False, bank_=None):
    """
    ★★ 从**已知的盾牌框**(整帧坐标)读血量 —— 给"攻击之后复核"用。

    为什么要这个入口:`read_hq_hp(after, target)` 原来是**重新找一遍总部**,
    而攻击落地那一刻画面上正放着**伤害动画/飘字**,盾牌常常被盖住 ->
    重找失败 -> `hp_after=None` -> 日志写成 `被拒绝(血量读不到)`,
    **看起来像"没打中"**(实机第一发就是:出手前读到 18,出手后读不到)。
    而"总部卡在这一回合里不会动"这件事是知道的 —— 直接照**出手前那个盾牌框**读就行。
    """
    if frame is None or not box:
        return None
    x, y, w, h = (int(v) for v in box[:4])
    if w < 8 or h < 8:
        return None
    pad = 5
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1 = min(frame.shape[1], x + w + pad)
    y1 = min(frame.shape[0], y + h + pad)
    shield = frame[y0:y1, x0:x1]
    if shield.size == 0:
        return None
    return read_shield(shield, (x, y, w, h), debug=debug, bank_=bank_)


def read_shield(shield, sbox=None, debug=False, bank_=None):
    """盾牌小图 -> 血量(供 `read` / `read_box` 共用,**判据只留一份**)。"""
    glyphs = extract_glyphs(shield)
    if not glyphs or len(glyphs) > 2:
        return None
    bank_ = bank_ if bank_ is not None else bank()
    if not bank_:
        return None
    digits, scores, ambiguous = [], [], False
    for g in glyphs:
        d, s, s2, d2 = _match_digit(g["img"], bank_)
        if d is None or s < MATCH_MIN:
            if debug:
                print(f"    [hq_hp] 字形 x{g['x']} 匹配失败(最好 {d} @ {s:.2f})")
            return None
        # ★ 歧义判据:第一名和第二名(不同数字)咬得太近 -> 这次匹配不可信。
        #   实测就是"3 vs 8"(数字 3 的原型只有 1 个)咬到 0.747 vs 0.70。
        if s2 > -1.0 and (s - s2) < AMBIGUOUS_MARGIN:
            ambiguous = True
        digits.append(d)
        scores.append(s)
    hp = int("".join(str(d) for d in digits))
    if hp < 1 or hp > 99:
        return None
    state = _color_state(glyphs)
    why = "templates"
    # ---- 不够有把握时的复核:两位数交给 OCR(单数字它读不出,所以只在 len==2 时用)----
    low_conf = min(scores) < CONFIDENT_SCORE
    if (ambiguous or low_conf) and len(glyphs) == 2:
        hp_ocr = _ocr_two_digits(shield)
        if hp_ocr is not None and hp_ocr != hp:
            if debug:
                print(f"    [hq_hp] 模板不够有把握({hp}, score={min(scores):.2f}"
                      f"{', 有歧义' if ambiguous else ''})-> OCR 复核为 {hp_ocr},采用 OCR")
            hp = hp_ocr
            why = "templates+ocr_tiebreak"
        elif hp_ocr == hp:
            why = "templates+ocr_agree"
    out = {"hp": hp, "state": state, "score": round(min(scores), 3),
           "n_glyphs": len(glyphs), "shield_box": sbox, "why": why,
           "ambiguous": ambiguous}
    if debug:
        print(f"    [hq_hp] hp={hp} state={out['state']} score={out['score']} "
              f"({why})")
    return out
