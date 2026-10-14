"""
mobile_board.py —— 手机端**板面**上的"谁在哪儿":能行动的自家单位、敌方总部、卡框。

为什么要有它:`unit_state.find_cost_badges`(电脑端那套)在手机帧上**一个徽章都找不到**
(实测 0 个)—— 它要求徽章是 14~22px 的深色方块,手机端实测 **28px**;卡框检测
(`board.card_boxes`)同样几乎全空(0~1 张)。但**判据本身**是同一个语义,所以这里
**不另写判据**,只是"换一把尺子"再调一次共用件:

  · 数字分析:`unit_state.analyze_digit(..., limits=DIGIT_LIMITS_MOBILE)`(2026-09-19 为手机端加的)
  · 血量盾牌:`hq_hp.read`(纯图像处理,**在手机帧上直接可用**,实测 22/26/20/20 全对)

★ 手机端板面的解剖(全部是在真机帧上用坐标网格量出来、并**裁出来看过**的):
  · 单位卡左上角那个方块 = **费用徽章**(深色底 + **橙色**数字 = 这回合还能行动);
    它**贴着卡的左上角**(徽章框 = 卡的左上角),卡约 **112x140**;
  · 卡底部一排三个深色小牌子 = `攻击力 | 类型图标 | 防御力`;
  · 前线那条虚线在 **y≈340~360**(`config/board_android.json`);
  · 总部卡是唯一**卡面很亮**(羊皮纸地图)的那种,亮卡检测能稳定抓到
    (敌总部在上半场、我总部在下半场)。
  · ★ 一个**踩过的坑**:徽章方块和卡顶那条深色带**是连在一起的**(同一个连通域,
    实测 28x25 的小方块右边直接连着深色卡条),所以**按"孤立方块"找徽章必然漏** ——
    只能像手牌那样**用橙色数字当锚点**。

存帧:`shots/android/probe/_cards_*.png`(亮卡画框)、`_grid_*.png`(量几何用的坐标网格)。
"""

from __future__ import annotations

import os
import sys
import json
from functools import lru_cache

import cv2
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import hq_hp                      # noqa: E402
import unit_state as us          # noqa: E402

# ---------------------------------------------------------------------------
# 几何(客户区 1280x720;设备分辨率由平台层归一)
# ---------------------------------------------------------------------------

#: 前线虚线中心(`config/board_android.json`:y 340~360)。
FRONTLINE_Y = 350

#: ★★★ "站在前线"的判据 = **徽章中心 y 落在这一段里**。
# 这一段是**实机量出来的**(2026-09-19,一次真的"上前线"之后):
#   我方支援线上的单位  徽章中心 y≈452
#   **挪到前线之后**     徽章中心 y≈284   ← 卡站在虚线上方,不是压在线上
#   敌方支援线上的单位  徽章中心 y≈117
# 所以:前线那一行取 (230, 340);>340 是支援线;<230 是敌方支援线。
# ★ 一开始我按"虚线 y=350 ± 55"去判,于是**挪上去之后被判成 enemy_side**,
#   验证直接报"没动成" —— 而游戏画面上明明弹着「友方占领了前线」。
#   教训还是那句:**几何要用眼睛从渲染图上读,不要拿"线在哪"当"卡在哪"**。
FRONT_BAND = (230, 340)

# 已保存真支援徽章中心约449/450；留出缩放/小幅抖动余量，不能把
# 前线下方全部当支援区（抽牌展示曾经过359/379）。越界保持待定。
SUPPORT_BAND = (410, 490)
BOARD_SAMPLE_GAP = 0.25
BOARD_SAMPLE_MAX_AGE = 3.0
BOARD_MOTION_MAX = 0.008

#: 徽章窗口边长。手机端实测 28px(电脑端 18)。
BADGE_WIN = 28

#: 单位卡尺寸(量出来的:徽章贴着卡左上角,卡约 112x140)。
CARD_W, CARD_H = 112, 140

#: 战场范围(避开两侧 HUD、顶上的牌堆、底下的手牌)。
FIELD = (200, 40, 1120, 560)

#: 亮卡检测:卡面是羊皮纸(亮),桌面是暗木头。
CARD_BRIGHT_V = 135
CARD_W_RANGE = (75, 150)
CARD_H_RANGE = (105, 230)

#: 橙色数字这个"锚点"本身的尺寸范围(**实测出来的**)。
# 真费用数字:8x19 / 8x20 / 14x19(两位数也在这个量级);
# 而**卡面美术**上的橙色块会大得多 —— 实测一处假阳性是 **25x32(a=366)**,
# 是虎式坦克的沙色装甲。⇒ 卡住宽高就把它挡掉了(比"暗占比"干净:
# 实测真徽章 vs 坦克美术的暗占比是 0.64/0.64/0.56 vs 0.54,**分不开**)。
ANCHOR_W_RANGE = (5, 22)
ANCHOR_H_RANGE = (10, 26)
ANCHOR_MIN_AREA = 40

#: ★ 判"这个橙色块就是**费用数字**"的饱和度下限。
# 实测(真机帧):真费用数字 **S=202 / 202 / 207**;卡面美术上那块橙色 **S=167**。
# 语义上也站得住:电脑端那边"能行动"的实测区间是 S≈186~220,灰数字 ≤105 ——
# 170 落在"明显是橙"和"不是橙"之间,两边都有余量。
ORANGE_S_MIN = 170

#: NMS:两个候选中心挨得比这近就是同一张牌。
NMS_DIST = 22

#: ★★★ "这一定是自家单位"的 y 下界。
# 为什么要有它:**橙色数字只说明"这个单位这回合还能行动",不说明是谁的** ——
# 对手回合里对手的单位也是橙的(实测:`live_train_board.png` 是对方回合,
# 就在敌方支援线 y≈117 上检出一个橙色数字)。
# 引擎虽然只在自己回合动作,但判据本身不该依赖"调用方记得先看回合" ——
# 所以这里再卡一道:敌方**支援线**那一行在 y≈100~145,取 250 是它的两倍余量;
# 前线仍须单独核验归属，不能用橙字或调用方的回合判断代替。
UNIT_MIN_Y = 250


def _hsv(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    return hsv[:, :, 0].astype(int), hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)


# ---------------------------------------------------------------------------
# ① 亮卡:总部卡是唯一稳定"很亮"的那种
# ---------------------------------------------------------------------------

def bright_cards(frame, field=FIELD):
    """卡面很亮的矩形(手机端实测:总部卡稳定命中,单位卡只在美术亮时命中)。"""
    if frame is None or not hasattr(frame, "shape"):
        return []
    _H, _S, V = _hsv(frame)
    x0, y0, x1, y1 = field
    m = (V > CARD_BRIGHT_V).astype(np.uint8)
    keep = np.zeros_like(m)
    keep[y0:y1, x0:x1] = 1
    m &= keep
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _lab, st, _c = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = (int(st[i, 0]), int(st[i, 1]), int(st[i, 2]),
                         int(st[i, 3]), int(st[i, 4]))
        if not (CARD_W_RANGE[0] <= w <= CARD_W_RANGE[1]
                and CARD_H_RANGE[0] <= h <= CARD_H_RANGE[1]):
            continue
        if a < 0.5 * w * h:
            continue
        out.append({"x": x, "y": y, "w": w, "h": h, "cx": x + w // 2,
                    "cy": y + h // 2})
    out.sort(key=lambda c: (c["y"], c["x"]))
    return out


# HQ在双方支援行，前线卡中心约342，绝不能按 cy<350 当成敌HQ。
# 真HQ中心敌174–178/我497–499；这里只支持已归一的1280×720布局。
HQ_CENTER_BANDS = {"enemy": (140, 220), "our": (460, 530)}
# 在连通域/闭运算之前隔离支援行。亮色桌面痕迹可能把前线卡与正下方HQ
# 连成292px高的块，事后按中心/卡高筛选会把真实HQ一起丢掉。
# 不扩大调用方FIELD，也不放宽卡体、盾牌或数字的授权门槛。
HQ_SCAN_BANDS = {"enemy": (70, 260), "our": (425, 590)}


def _support_row_bright_cards(frame, side, field=FIELD):
    """仅隔离已标定支援行；亮卡是布局证据，还不代表HQ身份。"""
    lo, hi = HQ_CENTER_BANDS[side]
    row_top, row_bottom = HQ_SCAN_BANDS[side]
    x0, y0, x1, y1 = field
    row_field = (x0, max(y0, row_top), x1, min(y1, row_bottom))
    return [c for c in bright_cards(frame, row_field) if lo <= c["cy"] <= hi]


def _hq_shield_geometry(card, box):
    """HQ的大盾牌必须与单位底部的小类型图标区分开。"""
    if not box:
        return False
    x, y, w, h = box
    cw, ch = card["w"], card["h"]
    # 已存HQ宽/卡宽约.50、高/卡高.34–.43；类型图标仅.24–.31/.22–.23。
    # 我方亮卡被FIELD下沿裁短，盾牌高比例仍应保留.30起的余量。
    return (0.42 <= w / cw <= 0.62 and 0.30 <= h / ch <= 0.50
            and 0.40 <= (x + w / 2 - card["x"]) / cw <= 0.60
            and 0.65 <= (y + h / 2 - card["y"]) / ch <= 0.90)


@lru_cache(maxsize=1)
def _hq_red3_auxiliary():
    """独立手机旧局红3原型；不加入共享PC数字库，资源缺失时拒绝补证。"""
    root = os.path.dirname(_HERE)
    try:
        with open(os.path.join(root, "config", "templates.android.hq_aux.json"),
                  encoding="utf-8") as stream:
            config = json.load(stream)
        path = os.path.join(root, config["templates"]["hq_red3_aux"]["path"])
        with open(path, "rb") as stream:
            data = np.frombuffer(stream.read(), np.uint8)
        template = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        if template is None or template.shape != (hq_hp.NORM, hq_hp.NORM):
            return None
        return template
    except (OSError, ValueError, KeyError, TypeError, cv2.error):
        return None


def _hq_red3_confirmation(shield, got):
    """仅补证原库清晰胜出的单红3；原始读数、score和共享阈值保持不变。"""
    if (not got or got.get("hp") != 3 or got.get("state") != "red"
            or got.get("n_glyphs") != 1 or got.get("ambiguous")
            or not 0.83 <= got.get("score", 0) < 0.85):
        return None
    glyphs = hq_hp.extract_glyphs(shield)
    if len(glyphs) != 1 or hq_hp._color_state(glyphs) != "red":
        return None
    digit, score, next_score, next_digit = hq_hp._match_digit(
        glyphs[0]["img"], hq_hp.bank())
    if digit != 3 or not 0.83 <= score < 0.85 or score - next_score < 0.10:
        return None
    template = _hq_red3_auxiliary()
    if template is None:
        return None
    _, aux_score, _, _ = hq_hp._match_digit(
        glyphs[0]["img"], {3: [("mobile_old_g5_183", template)]})
    if aux_score < 0.95:
        return None
    return {"method": "android_red3_independent_prototype", "aux_score": aux_score,
            "original_score": score, "original_margin": score - next_score,
            "original_next_digit": next_digit}


def hq_card(frame, side="enemy", field=FIELD):
    """支援行中的唯一亮HQ：行位置、大盾牌结构及可信数字均须通过。

    读得出数字不等于HQ：坦克类型图标曾被匹配成4。多候选时返回未知，
    不能再用面积大小猜身份；每帧重新定位以适应单位死亡后的行重排。
    """
    if (frame is None or not hasattr(frame, "shape")
            or frame.shape[:2] != (720, 1280) or side not in HQ_CENTER_BANDS):
        return None
    pool = _support_row_bright_cards(frame, side, field)
    structures = []
    for c in pool:
        try:
            shield, box = hq_hp.find_shield(frame, c)
            if shield is None or not _hq_shield_geometry(c, box):
                continue
            structures.append((c, shield, box))
        except Exception:                         # noqa: BLE001
            continue
    matches = []
    for c, shield, box in structures:
        try:
            got = hq_hp.read_shield(shield, box)
        except Exception:                         # noqa: BLE001
            continue
        if not got or got.get("hp") is None:
            continue
        # 通用读数最低分.45不足以授权HQ目标；单字形无OCR复核尤其要保守。
        minimum = 0.85 if got.get("n_glyphs") == 1 else 0.75
        verified_ocr = got.get("why") in ("templates+ocr_agree", "templates+ocr_tiebreak")
        corroboration = None
        if got.get("ambiguous") and not verified_ocr:
            continue
        if got.get("score", 0) < minimum:
            # 补证只能用于唯一完整HQ结构，不以读数成功数量消除结构歧义。
            if len(structures) == 1:
                corroboration = _hq_red3_confirmation(shield, got)
            if corroboration is None:
                continue
        c = dict(c, hp=got["hp"], shield=got.get("shield_box"),
                 hp_state=got.get("state"), hp_score=got.get("score"))
        if corroboration is not None:
            c["hp_corroboration"] = corroboration
        matches.append(c)
    return matches[0] if len(matches) == 1 else None


# ---------------------------------------------------------------------------
# ③ 敌方**单位卡**:靠卡底那排深色小牌子定位
#
# ★★★ 2026-09-19 **一条被我搞错、又被用户当场纠正的事**(记下来别再犯):
#   我一度把卡头的那个标记(德国黑十字 / 苏联红星 / 美国蓝圈)当成"敌我归属",
#   还量了红像素占比(6.2~6.4% vs ≤0.2%)准备拿它认敌人。
#   **用户原话:「那个敌我阵营标记是错的,那只是卡牌的**国家归属**」** ——
#   双方都能用任何国家的卡,我自己打一张苏联卡时头上也是红星。
#   ⇒ **它跟"是谁的"毫无关系**,拿它认敌人等于把国籍当阵营。
#
# ★ 那"这一行是谁的"到底该怎么判?**项目里本来就有正路**(`frontline_line.py` 文件头):
#   用户给的判据是「**前线那条黑线靠上 = 友方,在下 = 敌方**」,
#   而且游戏自己会**用文字说出来**(实测:我方挪上去时弹出「友方占领了前线」,
#   敌方占着时是「前线已被敌方占领。」)。
#
# ★★ 所以这一版**干脆不碰那个歧义**:只认**顶排(敌方支援线)**的卡 ——
#   我方单位只会在底下的支援线和中间那条前线,**顶排永远不可能是我的**。
#   这正好也是 `attack.py` 那句警告要我们做的事(判不出归属就别打,判错是去打自己人)。
# ---------------------------------------------------------------------------

#: 卡底那排小牌子:深色方块 + 里面一个**亮**的字形(攻击力/图标/防御力)。
STAT_DARK_V = 90
STAT_SIZE = (22, 36)
STAT_BRIGHT_V = 150
STAT_BRIGHT_MIN = 25
#: 一张卡的尺寸(从小牌子那一排反推出来的,和"徽章贴着卡左上角"那套量法互相印证)。
CARD_W2, CARD_H2 = 100, 152
#: 顶排(敌方支援线)的 y 上界:卡顶比它小 = 不可能是我方单位。
ENEMY_SUPPORT_MAX_Y = 200

#: ★ "三选一"类**选择框**的判据(见 `choice_modal`):中间那一带的亮像素占比。
#: 实测:框里 40.0~47.5%,正常对局 4.0~16.4% -> 阈值 28% 两边都留着大空档。
CHOICE_BAND = (140, 1150, 120, 520)
CHOICE_BRIGHT_V = 120
CHOICE_BRIGHT_FRAC = 0.28


def _colored_stat_digit(hsv):
    """Recognize only a centered red/green numeral inside an existing dark plate.

    Buffed attack is green and damaged defense is red; neither satisfies the
    old bright/low-saturation test. Color alone is not enough to add a plate.
    """
    import kredits_templates as kt
    h, s, v = (hsv[:, :, i] for i in range(3))
    color = ((s >= 120) & (v >= 90) &
             ((h <= 12) | (h >= 170) | ((h >= 35) & (h <= 85))))
    mask = color.astype(np.uint8) * 255
    mask[:2] = 0
    mask[-2:] = 0
    mask[:, :3] = 0
    mask[:, -3:] = 0
    ys, xs = np.where(mask > 0)
    if len(xs) < 50 or len(xs) > 0.42 * mask.size:
        return False
    gh, gw = int(ys.max()-ys.min()+1), int(xs.max()-xs.min()+1)
    if not (12 <= gh <= 25 and 5 <= gw <= 22 and
            abs((xs.min()+xs.max())/2-mask.shape[1]/2) <= 5 and
            abs((ys.min()+ys.max())/2-mask.shape[0]/2) <= 5):
        return False
    glyph = kt.normalize_glyph(mask)
    bank = kt.build_templates()
    scores = sorted((max(kt.score_against(glyph, t) for t in templates)
                     for templates in bank.values()), reverse=True)
    return len(scores) >= 2 and scores[0] >= .86 and scores[0]-scores[1] >= .12


def _type_stat_plate(frame, box):
    # Pure glyph matching, deliberately not inspect_unit_type (which calls
    # stat_boxes). This corroborates a colored digit with an adjacent real type.
    import mobile_combat_vision as combat
    bank = combat._bank()
    if not all(t in bank for t in combat.TYPES):
        return False
    x, y, w, h = box
    glyph = combat._normalized_icon(frame[y:y+h, x:x+w])
    scores = sorted((float(cv2.matchTemplate(glyph, combat._normalized_icon(bank[t]),
                                              cv2.TM_CCOEFF_NORMED)[0, 0])
                     for t in combat.TYPES), reverse=True)
    return scores[0] >= .90 and scores[0]-scores[1] >= combat.TYPE_MARGIN


def stat_boxes(frame, field=FIELD):
    """卡底那排深色小牌子(攻击力 | 类型图标 | 防御力)。"""
    if frame is None or not hasattr(frame, "shape"):
        return []
    x0, y0, x1, y1 = field
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    V, S = hsv[:, :, 2], hsv[:, :, 1]
    dark = (V < STAT_DARK_V).astype(np.uint8)
    keep = np.zeros_like(dark)
    keep[y0:y1, x0:x1] = 1
    dark &= keep
    n, _l, st, _c = cv2.connectedComponentsWithStats(dark, 8)
    out, colored = [], []
    for i in range(1, n):
        x, y, w, h, a = (int(st[i, 0]), int(st[i, 1]), int(st[i, 2]),
                         int(st[i, 3]), int(st[i, 4]))
        if not (STAT_SIZE[0] <= w <= STAT_SIZE[1]
                and STAT_SIZE[0] <= h <= STAT_SIZE[1]):
            continue
        if a < 0.55 * w * h:
            continue
        sub, subs = V[y:y + h, x:x + w], S[y:y + h, x:x + w]
        if int(((sub > STAT_BRIGHT_V) & (subs < 120)).sum()) < STAT_BRIGHT_MIN:
            if _colored_stat_digit(hsv[y:y+h, x:x+w]):
                colored.append((x, y, w, h))
            continue
        out.append((x, y, w, h))
    type_cache = {}
    white_boxes = tuple(out)
    for box in colored:
        x, y, w, h = box
        for adjacent in white_boxes:
            ax, ay, aw, ah = adjacent
            if abs(ay-y) > 5 or not 27 <= abs(ax+aw/2-x-w/2) <= 40:
                continue
            if adjacent not in type_cache:
                type_cache[adjacent] = _type_stat_plate(frame, adjacent)
            if type_cache[adjacent]:
                out.append(box)
                break
    out.sort(key=lambda t: (t[1], t[0]))
    return out


def cards_from_stats(frame, field=FIELD):
    """把同一张卡的几个小牌子并成一个**卡框**(按 y 分排、按 x 聚簇)。"""
    boxes = stat_boxes(frame, field)
    rows = []
    for b in boxes:
        for r in rows:
            if abs(r["y"] - b[1]) <= 22:
                r["items"].append(b)
                break
        else:
            rows.append({"y": b[1], "items": [b]})
    cards = []
    for r in rows:
        items = sorted(r["items"])
        cur = [items[0]]
        for b in items[1:]:
            if b[0] - (cur[-1][0] + cur[-1][2]) <= 24:
                cur.append(b)
            else:
                cards.append(cur)
                cur = [b]
        cards.append(cur)
    out = []
    for cur in cards:
        left = min(b[0] for b in cur) - 6
        bottom = max(b[1] + b[3] for b in cur) + 4
        # With a missing colored attack, the two remaining plates are TYPE and
        # DEFENSE, not ATTACK and TYPE. Use the same high-confidence local type
        # glyph anchor as guard geometry; never shift from color or digits alone.
        # Three-plate and single-plate groups keep their existing geometry.
        if len(cur) == 2:
            types = [b for b in cur if _type_stat_plate(frame, b)]
            if len(types) == 1:
                tx, ty, tw, th = types[0]
                other = next(b for b in cur if b != types[0])
                ox, oy, ow, oh = other
                center = tx + tw / 2
                if (abs(oy - ty) <= 5
                        and 27 <= abs(ox + ow / 2 - center) <= 40
                        and 12 < abs(center - (left + CARD_W2 / 2)) <= 40):
                    left = int(round(center - CARD_W2 / 2))
        card = {"x": left, "y": bottom - CARD_H2, "w": CARD_W2, "h": CARD_H2,
                "cx": left + CARD_W2 // 2, "cy": bottom - CARD_H2 // 2,
                "stat_boxes": cur, "n_stats": len(cur)}
        if card["y"] < field[1] or card["y"] + card["h"] > field[3]:
            continue                        # 卡框跑到场地外面 -> 不认(宁可少认)
        out.append(card)
    out.sort(key=lambda c: (c["y"], c["x"]))
    return out


def cards_from_types(frame, field=FIELD):
    """Calibrated unit footprints from a complete, independently read type plate.

    Existing complete stat groups keep their coordinates. Numerals are optional
    corroboration; neither a missed digit nor an unrelated row blocks a type.
    """
    import mobile_combat_vision as combat
    if (not combat._valid(frame) or not isinstance(field, (tuple, list))
            or len(field) != 4 or any(type(value) is not int for value in field)):
        return []
    x0, y0, x1, y1 = field
    if not (0 <= x0 < x1 <= 1280 and 0 <= y0 < y1 <= 720):
        return []
    try:
        complete = [card for card in cards_from_stats(frame, field) if card["n_stats"] >= 2]
    except (cv2.error, ValueError, TypeError, KeyError):
        complete = []
    anchors = combat.type_stat_plates(frame, field)
    rejected = set()
    for original in complete:
        group = [anchor for anchor in anchors
                 if tuple(anchor["box"]) in [tuple(box) for box in original["stat_boxes"]]
                 and abs(anchor["box"][0]+anchor["box"][2]/2-original["cx"]) <= 12
                 and original["y"]+original["h"]-47 <= anchor["box"][1] <= original["y"]+original["h"]-13]
        if len(group) > 1:
            rejected.add((original["x"], original["y"]))
    out = []
    for anchor in anchors:
        bx, by, bw, bh = anchor["box"]
        matching = [card for card in complete
                    if (bx, by, bw, bh) in [tuple(box) for box in card["stat_boxes"]]]
        if len(matching) == 1:
            card = dict(matching[0])
            key = (card["x"], card["y"])
            if (key in rejected or abs(bx+bw/2-card["cx"]) > 12
                    or not card["y"]+card["h"]-47 <= by <= card["y"]+card["h"]-13):
                continue
        elif matching:
            continue
        else:
            left = int(round(bx + bw / 2 - CARD_W2 / 2))
            bottom = by + bh + 4
            card = {"x": left, "y": bottom-CARD_H2, "w": CARD_W2, "h": CARD_H2,
                    "cx": left+CARD_W2//2, "cy": bottom-CARD_H2//2,
                    "stat_boxes": [(bx, by, bw, bh)], "n_stats": 1}
        if not (x0 <= card["x"] and y0 <= card["y"]
                and card["x"]+card["w"] <= x1 and card["y"]+card["h"] <= y1
                and (70 <= card["y"] <= 130 or 235 <= card["y"] <= 315
                     or 425 <= card["y"] <= 470)):
            continue
        card.update(type=anchor["type"], type_evidence=anchor)
        out.append(card)
    # Retain the original .80 local glyph path for already complete cards.
    for original in complete:
        if (original["x"], original["y"]) in rejected:
            continue
        if any(original["x"] == card["x"] and original["y"] == card["y"] for card in out):
            continue
        if not (70 <= original["y"] <= 130 or 235 <= original["y"] <= 315
                or 425 <= original["y"] <= 470):
            continue
        observed = combat.inspect_unit_type(frame, original)
        if observed["type"] != "unknown":
            out.append(dict(original, type=observed["type"], type_evidence=observed))
    # Two independently inferred, overlapping footprints cannot both describe
    # a normal row unit. Refuse this local ambiguity instead of counting twice.
    ambiguous = set()
    for index, first in enumerate(out):
        for other_index, second in enumerate(out[index+1:], index+1):
            if (abs(first["y"]-second["y"]) <= 22
                    and max(first["x"], second["x"]) < min(first["x"]+first["w"], second["x"]+second["w"])):
                ambiguous.update((index, other_index))
    return sorted((card for index, card in enumerate(out) if index not in ambiguous),
                  key=lambda card: (card["y"], card["x"]))


def enemy_support_cards(frame, field=FIELD):
    """
    **敌方支援线那一排**的单位卡(顶排)。

    ★ 为什么只认这一排:**它永远不可能是我的** —— 我方单位只会在底下的支援线
      (y≈450)和中间那条前线(y≈240~330);顶排(y<200)是敌方专有。
      这样"这一行是谁的"这个歧义就**不需要**判了(判错就是去打自己人)。
    """
    return [c for c in cards_from_types(frame, field) if c["y"] < ENEMY_SUPPORT_MAX_Y]


def _front_cards(frame, field=FIELD):
    """前线行的卡体候选，不包含任何敌我推断。"""
    return [c for c in cards_from_stats(frame, field)
            if 235 <= c["y"] <= 315 and c["n_stats"] >= 2]


def frontline_state(frame):
    """1280×720 手游布局的黑线归属；不读国家图标、不由橙灰推归属。

    沿用 frontline_line 的上下参考行结构判据，但不导入其 Windows 采集依赖。
    当前手机存帧黑线：友方 y≈259、空 y≈347/353、敌方 y≈425；
    相对于已标定前线中心350比较。强横线独立读出归属；类型卡体只作
    居中空前线的补充检查，不要求攻防数字或总部及支援行完整。
    未覆盖其它分辨率、UI缩放或布局漂移；不成立就 unknown。
    """
    evidence = {"reference_y": FRONTLINE_Y, "line_y": None,
                "line_score": 0.0, "other_score": 0.0, "front_cards": None}
    def result(owner, reason):
        return {"owner": owner, "reason": reason, "evidence": evidence}
    reason = board_transition_reason(frame)
    if reason:
        return result("unknown", reason)
    # Turn/button/result classification belongs to the caller. The calibrated
    # black line supplies ownership independently of HQ, bright rows or digits.
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.int16)
    x0, x1, y0, y1, dy = 325, 955, 235, 448, 16
    center = gray[y0:y1, x0:x1]
    reference = (gray[y0-dy:y1-dy, x0:x1] + gray[y0+dy:y1+dy, x0:x1]) // 2
    fractions = ((reference - center) > 25).mean(axis=1)
    peak = int(np.argmax(fractions))
    score = float(fractions[peak])
    others = fractions.copy()
    others[max(0, peak-12):peak+13] = 0
    other = float(others.max())
    # A clear, long primary line can reject weak fragments of card edges as
    # competitors. Strong competing lines and long weaker lines still count;
    # a short primary keeps the original ambiguity decision.
    if score >= .80 and score-other < .20:
        dark = (reference-center) > 25
        transitions = np.diff(np.pad(dark.astype(np.int8), ((0, 0), (1, 1))), axis=1)
        longest = []
        for edge_row in transitions:
            lengths = np.flatnonzero(edge_row == -1)-np.flatnonzero(edge_row == 1)
            longest.append(int(lengths.max()) if lengths.size else 0)
        if longest[peak] >= 2*CARD_W2:
            competitors = others.copy()
            competitors[(fractions < .80) & (np.asarray(longest) < 2*CARD_W2)] = 0
            other = float(competitors.max())
        else:
            joined = []
            for edge_row in transitions:
                starts = np.flatnonzero(edge_row == 1)
                ends = np.flatnonzero(edge_row == -1)
                longest_joined = 0
                segment_start = 0
                for index in range(len(starts)):
                    if index == 0 or starts[index] - ends[index - 1] > 3:
                        segment_start = starts[index]
                    longest_joined = max(longest_joined, int(ends[index] - segment_start))
                joined.append(longest_joined)
            if joined[peak] >= 2*CARD_W2:
                competitors = others.copy()
                competitors[(fractions < .80) & (np.asarray(joined) < 2*CARD_W2)] = 0
                other = float(competitors.max())
    line_y = peak + y0
    evidence.update(line_y=line_y, line_score=round(score, 4),
                    other_score=round(other, 4),
                    delta=line_y-FRONTLINE_Y)
    if score < .80 or score-other < .20:
        return result("unknown", "前线横线不足或存在竞争横线")
    if 245 <= line_y <= 275:
        return result("our", "已确认归属黑线在前线上方")
    if 410 <= line_y <= 440:
        return result("enemy", "已确认归属黑线在前线下方")
    if 335 <= line_y <= 365:
        import mobile_combat_vision as combat
        front_types = [anchor for anchor in combat.type_stat_plates(frame, (200, 350, 1120, 470))
                       if 235 <= anchor["box"][1]+anchor["box"][3]+4-CARD_H2 <= 315]
        evidence["front_cards"] = len(front_types)
        if not front_types:
            return result("empty", "居中前线横线且前线未见卡体")
    return result("unknown", "横线不在已确认归属位置或与前线卡体矛盾")


def enemy_front_cards(frame, field=FIELD):
    """只有敌方归属已确认时才返回前线攻击目标。"""
    if frontline_state(frame)["owner"] != "enemy":
        return []
    return [card for card in cards_from_types(frame, field) if 235 <= card["y"] <= 315]


def _orange_anchor_centers(frame, field=FIELD):
    """橙色像素连通域的中心(只是"去哪儿看",不是结论)。"""
    H, S, V = _hsv(frame)
    x0, y0, x1, y1 = field
    m = ((H >= us.ANCHOR_HUE[0] if hasattr(us, "ANCHOR_HUE") else H >= 6)
         & (H <= 28) & (S >= 140) & (V >= 130)).astype(np.uint8)
    keep = np.zeros_like(m)
    keep[y0:y1, x0:x1] = 1
    m &= keep
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, _lab, st, _c = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = (int(st[i, 0]), int(st[i, 1]), int(st[i, 2]),
                         int(st[i, 3]), int(st[i, 4]))
        if a < ANCHOR_MIN_AREA:
            continue
        if not (ANCHOR_W_RANGE[0] <= w <= ANCHOR_W_RANGE[1]
                and ANCHOR_H_RANGE[0] <= h <= ANCHOR_H_RANGE[1]):
            continue
        out.append((x + w // 2, y + h // 2, w, h, a))
    return out


def _nms(items, dist=NMS_DIST):
    out = []
    for it in sorted(items, key=lambda t: -t.get("digit_n", 0)):
        if any(abs(it["cx"] - o["cx"]) <= dist and abs(it["cy"] - o["cy"]) <= dist
               for o in out):
            continue
        out.append(it)
    out.sort(key=lambda b: b["cx"])
    return out


def _badge_candidates(frame, field=FIELD, debug=False):
    """费用橙字小窗候选；尚未证明处于战场卡的有效行。"""
    if frame is None or not hasattr(frame, "shape"):
        return []
    _H, _S, V = _hsv(frame)
    _h2, S2, _v2 = _hsv(frame)
    cands = []
    for (cx, cy, w, h, a) in _orange_anchor_centers(frame, field):
        if cy < UNIT_MIN_Y:                    # 敌方支援线那一行,不是我们的(见 UNIT_MIN_Y)
            if debug:
                print(f"    [丢] 橙锚点 ({cx},{cy}) 在 y<{UNIT_MIN_Y}(敌方支援线)")
            continue
        win = BADGE_WIN
        wx = int(min(max(cx - win // 2, 0), frame.shape[1] - win))
        wy = int(min(max(cy - win // 2, 0), frame.shape[0] - win))
        d = us.analyze_digit(V[wy:wy + win, wx:wx + win],
                             S2[wy:wy + win, wx:wx + win],
                             limits=us.DIGIT_LIMITS_MOBILE)
        if d is None or d["state"] != "orange" or d["digit_s"] < ORANGE_S_MIN:
            if debug:
                why = ("无数字" if d is None
                       else f"{d['state']} S={d['digit_s']:.0f}")
                print(f"    [丢] 橙锚点 ({cx},{cy}) {w}x{h} a={a} -> {why}")
            continue
        cands.append({"x": wx, "y": wy, "w": win, "h": win,
                      "cx": wx + win // 2, "cy": wy + win // 2, **d})
    return _nms(cands)


def _ordinary_overlay_anchors(frame, value):
    """Ordinary card envelopes, used only to explain a merged bright component.

    Type plates are complete raw components, independent of stat recognition.
    A large raw shield must satisfy the original HQ geometry in a support band;
    this layout evidence neither reads HQ health nor authorizes an attack.
    """
    import mobile_combat_vision as combat
    radius = 4  # The original 9x9 closing kernel can extend a card by this much.
    max_w, max_h = CARD_W_RANGE[1], CARD_H_RANGE[1]
    anchors = []
    for anchor in combat.type_stat_plates(frame):
        x, y, w, h = anchor["box"]
        bottom, center = y+h+4, x+w/2
        top = bottom-CARD_H2
        if not (70 <= top <= 130 or 235 <= top <= 315 or 425 <= top <= 470):
            continue
        anchors.append((anchor["box"], center,
                        (int(center-max_w/2)-radius, bottom-max_h-radius,
                         int(center+max_w/2)+radius, bottom+radius)))
    _, _, dark, _ = cv2.connectedComponentsWithStats((value < 120).astype(np.uint8), 8)
    for x, y, w, h, area in dark[1:]:
        if not (28 <= w <= 80 and 28 <= h <= 80 and area >= .55*w*h):
            continue
        cx, cy = x+w/2, y+h/2
        for side, top_range in (("enemy", (70, 130)), ("our", (425, 470))):
            lo, hi = HQ_CENTER_BANDS[side]
            minimum = max(top_range[0], cy-.90*CARD_H2, lo-CARD_H2/2)
            maximum = min(top_range[1], cy-.65*CARD_H2, hi-CARD_H2/2)
            if minimum > maximum:
                continue
            card = {"x": cx-CARD_W/2, "y": (minimum+maximum)/2,
                    "w": CARD_W, "h": CARD_H2}
            if not _hq_shield_geometry(card, (x, y, w, h)):
                continue
            row_top, row_bottom = HQ_SCAN_BANDS[side]
            anchors.append(((int(x), int(y), int(w), int(h)), cx,
                            (int(cx-max_w/2)-radius, row_top-radius,
                             int(cx+max_w/2)+radius, row_bottom+radius)))
    return anchors


def _large_card_overlay(frame):
    """保守识别战场中超出正常卡尺寸的亮色卡体/展示层。"""
    if frame is None or not hasattr(frame, "shape"):
        return False
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    value, saturation = hsv[:, :, 2], hsv[:, :, 1]
    mask = np.zeros_like(value, dtype=np.uint8)
    # 只看战场至手牌顶边上方，避免把普通扇形手牌并成大卡。
    mask[40:610, 200:1120] = ((value[40:610, 200:1120] > CARD_BRIGHT_V) &
                             (saturation[40:610, 200:1120] < 100))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    _n, labels, stats, _centers = cv2.connectedComponentsWithStats(mask, 8)
    candidates = [(index, tuple(int(v) for v in component))
                  for index, component in enumerate(stats[1:], 1)
                  if component[2] >= 160 and component[3] >= 190
                  and component[4] >= .22*component[2]*component[3]]
    if not candidates:
        return False
    anchors = _ordinary_overlay_anchors(frame, value)
    for index, (x, y, w, h, _area) in candidates:
        available = [(center, envelope) for (bx, by, bw, bh), center, envelope in anchors
                     if x <= bx and y <= by and bx+bw <= x+w and by+bh <= y+h]
        # A single ordinary card cannot explain a large presentation of itself.
        centers = sorted(set(center for center, _envelope in available))
        if not any(132 <= b-a <= 156 for a in centers for b in centers if b > a):
            return True
        covered = np.zeros((h, w), dtype=np.uint8)
        for _center, (a, b, c, d) in available:
            covered[max(0, b-y):min(h, d-y), max(0, a-x):min(w, c-x)] = 1
        component = labels[y:y+h, x:x+w] == index
        if np.any(component & (covered == 0)):
            return True
    return False


def _center_text_banner(frame):
    """占领/失去前线等横幅的大白字；不识别文字语义，不授权任何动作。"""
    hsv = cv2.cvtColor(frame[320:398, 400:880], cv2.COLOR_BGR2HSV)
    white = hsv[:, :, 1] < 100
    orange = ((hsv[:, :, 0] >= 6) & (hsv[:, :, 0] <= 28)
              & (hsv[:, :, 1] >= ORANGE_S_MIN))
    mask = ((hsv[:, :, 2] > 170) & white).astype(np.uint8)
    _n, _labels, stats, _centers = cv2.connectedComponentsWithStats(mask, 8)
    # White text must be vertically contained in the banner band. Card art
    # cut by the band's edge cannot supply a complete text component.
    glyphs = [(int(x), int(y), int(w), int(h), int(area)) for x, y, w, h, area in stats[1:]
              if 8 <= w <= 75 and 28 <= h <= 70 and area >= 90
              and 0 < y and y+h < mask.shape[0]]
    # Split strokes can have different tops while sharing a text baseline.
    # Separate bottom layers must not combine into a single text row.
    for bottom in {g[1]+g[3] for g in glyphs}:
        row = [g for g in glyphs if bottom <= g[1]+g[3] <= bottom+8]
        if (len(row) >= 4 and sum(g[4] for g in row) >= 1800
                and max(g[0]+g[2] for g in row)-min(g[0] for g in row) >= 220):
            return True
    # Orange turn text has disconnected strokes (e.g. the top/bottom of 合).
    # Combine only overlapping text columns; retain the original glyph size,
    # count, area and span requirements instead of treating a cost as a banner.
    mask = ((hsv[:, :, 2] > 170) & orange).astype(np.uint8)
    _n, _labels, stats, _centers = cv2.connectedComponentsWithStats(mask, 8)
    columns = []
    for x, y, w, h, area in sorted(stats[1:], key=lambda box: int(box[0])):
        x, y, w, h, area = (int(v) for v in (x, y, w, h, area))
        if columns and x < columns[-1][2]:
            left, top, right, bottom, old_area = columns[-1]
            columns[-1] = (left, min(top, y), max(right, x+w), max(bottom, y+h), old_area+area)
        else:
            columns.append((x, y, x+w, y+h, area))
    glyphs = [(left, right-left, area) for left, top, right, bottom, area in columns
              if 8 <= right-left <= 75 and 28 <= bottom-top <= 70 and area >= 90]
    return (len(glyphs) >= 4 and sum(g[2] for g in glyphs) >= 1800
            and max(g[0]+g[1] for g in glyphs)-min(g[0] for g in glyphs) >= 220)


def board_transition_reason(frame):
    """单帧展示/几何异常必须等待；空单位列表不能表达这种待定。"""
    if frame is None or not hasattr(frame, "shape") or frame.shape != (720, 1280, 3):
        return "板面尺寸未确认"
    if _center_text_banner(frame):
        return "存在中央状态文字横幅"
    if _large_card_overlay(frame):
        return "存在放大卡牌/展示层"
    return ""


def board_motion(previous, current):
    """归一战场ROI的变化占比；小模糊抑制采样噪声，保留卡体移动。"""
    if (previous is None or current is None or not hasattr(previous, "shape")
            or not hasattr(current, "shape") or previous.shape != current.shape):
        return 1.0
    def sample(frame):
        crop = frame[40:610, 200:1120]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(cv2.resize(gray, (230, 143),
                               interpolation=cv2.INTER_AREA), (3, 3), 0)
    change = cv2.absdiff(sample(previous), sample(current))
    return float((change > 18).mean())


class BoardStability:
    """两次独立观察之间确实稳定才放行；不保存单位已行动身份。"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = None
        self.observed_at = None
        self.last_motion = None

    def observe(self, frame, now):
        reason = board_transition_reason(frame)
        if reason:
            self.reset()
            return False, reason
        age = now - self.observed_at if self.observed_at is not None else None
        if self.previous is None or age is None or age > BOARD_SAMPLE_MAX_AGE or age < 0:
            self.previous, self.observed_at = frame.copy(), now
            return False, "等待第二张板面观察帧"
        if age < BOARD_SAMPLE_GAP:
            return False, "板面观察间隔不足"
        self.last_motion = board_motion(self.previous, frame)
        self.previous, self.observed_at = frame.copy(), now
        if self.last_motion > BOARD_MOTION_MAX:
            return False, f"战场仍在变化({self.last_motion:.3%})"
        return True, f"战场连续观察稳定({self.last_motion:.3%})"


def actionable_units(frame, field=FIELD, debug=False):
    """当前橙色且位于已确认战场行的候选；灰色可能压制，不推断已行动。"""
    if board_transition_reason(frame):
        return []
    units = []
    front_owner = None
    for b in _badge_candidates(frame, field, debug):
        if not (FRONT_BAND[0] <= b["cy"] <= FRONT_BAND[1] or
                SUPPORT_BAND[0] <= b["cy"] <= SUPPORT_BAND[1]):
            continue
        card = {"x": b["x"], "y": b["y"], "w": CARD_W, "h": CARD_H,
                "cx": b["x"] + CARD_W // 2, "cy": b["y"] + CARD_H // 2}
        # ★ 按下的点取**卡身中间偏上**:别贴边(贴边可能按在卡外),也别压到卡底的
        #   那排小牌子(那里是攻击力/图标/防御力,不是"抓住卡"的位置)。
        frm = (int(card["cx"]), int(b["y"] + CARD_H * 0.42))
        row = ("front" if FRONT_BAND[0] <= b["cy"] <= FRONT_BAND[1]
               else "support")
        if row == "front":
            if front_owner is None:
                front_owner = frontline_state(frame)["owner"]
            if front_owner != "our":
                continue
        units.append({"badge": b, "card": card, "from": frm, "row": row})
    if debug:
        for u in units:
            print(f"    可行动单位 徽章 x{u['badge']['x']} y{u['badge']['y']} "
                  f"S={u['badge']['digit_s']:.0f} n={u['badge']['digit_n']} "
                  f"行={u['row']} 起手点={u['from']}")
    return units


def unit_combat_type(frame, unit):
    """类型只来自卡底图标；未知不授予远程或移动权限。"""
    from mobile_combat_vision import unit_combat_type as classify
    return classify(frame, unit)


def combat_guard_info(frame, hq=None):
    from mobile_combat_vision import combat_guard_info as inspect
    return inspect(frame, hq=hq)


def choice_modal(frame, band=CHOICE_BAND):
    """
    屏幕上是不是出现了**"三选一"那类选择框**(用户:一张卡的**特效是从三张卡里抽一个**)。

    返回 `(是不是, 该点哪儿)`。判据 = **中间那一带被几张大亮卡铺满**:
      实测(真机存帧):那个框 **40.0 / 47.1 / 47.0 / 47.5%**,正常对局 **4.0~16.4%** ——
      中间空档很大,阈值取 28% 两边都有余量。
    ★ 为什么要专门认它:引擎遇到**认不出的画面**时是 fail-closed(什么都不做),
      实测在那个框上**静坐了 13 分钟**。用户那次的原话是"**点一下卡牌就行了**" ——
      所以兜底不该"随便点一下",要**认出这个框、去点中间那张卡**。
    """
    if frame is None or not hasattr(frame, "shape"):
        return False, None
    x0, x1, y0, y1 = band
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(frame.shape[1], x1), min(frame.shape[0], y1)
    if x1 - x0 < 100 or y1 - y0 < 100:
        return False, None
    V = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)[:, :, 2]
    if float((V > CHOICE_BRIGHT_V).mean()) < CHOICE_BRIGHT_FRAC:
        return False, None
    # 光"亮"还不够 —— 顺便把**中间那张卡**的中心找出来当落点(找不到就用画面正中偏上)。
    m = (V > CHOICE_BRIGHT_V).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, _l, st, _c = cv2.connectedComponentsWithStats(m, 8)
    cards = []
    for i in range(1, n):
        x, y, w, h, a = (int(st[i, 0]), int(st[i, 1]), int(st[i, 2]),
                         int(st[i, 3]), int(st[i, 4]))
        if w >= 180 and h >= 220 and a > 0.5 * w * h:
            cards.append((x + x0, y + y0, w, h))
    cards.sort()
    if cards:
        x, y, w, h = cards[len(cards) // 2]
        return True, (x + w // 2, y + h // 2)
    return True, ((x0 + x1) // 2, (y0 + y1) // 2)


#: ★★ "结束回合"按钮的**两种配色**(用户 2026-09-19 的观察,原话):
#:   「**费用用完后结束回合标才会变成橙色,没用完是白色状态**」。
#:   而且**它只在轮到我们时才显示**(用户另一句:"轮到敌方的时候他就不显示结束回合了")。
#:   ⇒ 两条都能用:
#:     ① 按钮在不在 = **是不是我的回合**(`ui_state` 的 in_game 规则就是这个);
#:     ② 颜色 = **我这回合还有没有余量**(白 = 还有费用/还能动;橙 = 用完了)。
#:   ★ 为什么这条重要:引擎"没动作"时,光看日志分不清是"没得打"还是"判据瞎了";
#:     有这一条就能一眼看出来(白着还不动 = 有问题;橙着不动 = 正常,该结束回合了)。
END_TURN_TPL_ORANGE = "end_turn_btn"
END_TURN_TPL_WHITE = "end_turn_btn_white"
END_TURN_MIN = 0.82


def end_turn_state(frame, templates=None):
    """结束回合按钮:**'white'**(还有余量)/ **'orange'**(费用用完了)/ None(没显示)。"""
    from mobile_end_button import end_turn_state as observed_color
    return observed_color(frame, templates, min_score=END_TURN_MIN)


def overlay(frame, units=None, hq=None, our_hq=None, note=""):
    vis = frame.copy()
    cv2.line(vis, (FIELD[0], FRONTLINE_Y), (FIELD[2], FRONTLINE_Y), (255, 0, 255), 1)
    for u in (units or []):
        c = u["card"]
        col = (0, 255, 0) if u.get("row") == "front" else (0, 200, 255)
        cv2.rectangle(vis, (c["x"], c["y"]), (c["x"] + c["w"], c["y"] + c["h"]),
                      col, 1)
        b = u["badge"]
        cv2.rectangle(vis, (b["x"], b["y"]), (b["x"] + b["w"], b["y"] + b["h"]),
                      (0, 0, 255), 2)
        cv2.drawMarker(vis, u["from"], (255, 255, 0), cv2.MARKER_CROSS, 11, 1)
        cv2.putText(vis, f"{u.get('row', '?')[:2]}", (b["x"] - 2, b["y"] - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1)
    for card, col, tag in ((hq, (0, 0, 255), "HQ-E"), (our_hq, (255, 0, 255), "HQ-O")):
        if card:
            cv2.rectangle(vis, (card["x"], card["y"]),
                          (card["x"] + card["w"], card["y"] + card["h"]), col, 3)
            cv2.putText(vis, f"{tag} hp={card.get('hp')}",
                        (card["x"], max(14, card["y"] - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)
    cv2.putText(vis, note, (FIELD[0] + 2, FIELD[3] - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
    return vis


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ROOT = os.path.dirname(_HERE)
    for rel in (sys.argv[1:] or ["shots/android/hand/live_attack_recon.png"]):
        img = cv2.imread(os.path.join(ROOT, rel))
        if img is None:
            print("读不到", rel)
            continue
        print(f"\n=== {rel}")
        us_ = actionable_units(img, debug=True)
        e = hq_card(img, "enemy")
        o = hq_card(img, "our")
        print(f"  可行动 {len(us_)} 个 | 敌总部 {e} | 我总部 {o}")
        out = os.path.join(ROOT, "shots", "android", "probe",
                           "_board_" + os.path.basename(rel))
        cv2.imwrite(out, overlay(img, us_, e, o, note=os.path.basename(rel)))
        print("★ 画出来了:", out)
