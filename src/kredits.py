"""
kredits.py - read KARDS Kredits and decide what we can afford (M3).

Why this exists
---------------
Without knowing the Kredits balance the engine happily drags cards it cannot
pay for. KARDS simply refuses the deploy and the card stays in hand, so every
attempt is wasted time and the turn ends with resources unspent. That is what
made the first live turn_test run fail every deploy.

Two layers
----------
1. `read_kredits(frame)` - best-effort numeric read of our own "N K/M" plate
   (bottom-left of the client area).

   The numeral is isolated reliably: it is the largest ORANGE connected
   component in the plate (the "K/M" badge sits to its right and is a separate
   component). What is NOT reliable is OCR of the glyph itself - RapidOCR's
   detector needs a text line and returns nothing for a single stylized stencil
   digit. So `read_kredits` only trusts OCR when it is unambiguous, and
   otherwise returns None rather than guessing a wrong number (a wrong number
   would be worse than no number: it would make us skip playable cards).

2. `Affordability` - the layer the engine actually depends on. It starts
   permissive and learns from real deploy attempts: a card that fails to
   deploy is treated as unaffordable, which caps the price we are willing to
   pay for the rest of the turn. This converges to "play the cheap cards, stop
   wasting time on the expensive ones" without needing a perfect readout.

`record_samples=True` dumps every isolated numeral to shots/kredits/numeral_*.png
so a digit template bank can be built for an exact reader later.
"""

from __future__ import annotations

import os
import re
import time

import cv2
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES_DIR = os.path.join(PROJECT_ROOT, "shots", "kredits", "numerals")

# Our own Kredits plate, in client coordinates (1280x720).
# bottom-left, left of the name plate. Covers numeral + K/M badge.
OURS_BOX = (20, 558, 82, 700)
# The opponent's plate, same layout at the top of the screen (for reference).
OPPONENT_BOX = (20, 103, 82, 245)

# ============================================================================
# 「这一块橙色是不是同一个数字的另一半」—— 合并规则(A/B 开关)
# ============================================================================
# ★★★ 2026-09-13 晚:老规则**会把 "11" 读成 "1"**,而且只在"第二个数字是 1"时发作。
#
# 地面真值(9 张真实帧,画面上明明白白写着 "11 K/11",程序读出 1):
#   shots/attack_frames/0913_191731_attack.png  等 9 帧,见 kredits_numeral_ab.py
# 逐块量出来的几何(费用区域内的橙色连通域):
#   "11": (10,12,10,25) 第 1 个 "1" | (26,12,10,25) 第 2 个 "1" | (47,10,9,13) K/M 徽章
#   "10": (10,12,10,25)         "1" | (24,12,17,25)         "0" | (47,10,9,13) K/M 徽章
#   "12": (10,12,10,25)         "1" | (23,12,18,25)         "2" | (47,10,9,13) K/M 徽章
# 老判据是 `abs(p.x - anchor.x) <= max(两个字形宽度) * 1.2` ——
# **拿字形自己的宽度当尺子**,于是:
#   "11": |26-10| = 16  >  10*1.2 = 12      -> 第二个 "1" 永远合不进来 -> 读成 1  ✗
#   "10": |24-10| = 14  <= 17*1.2 = 20.4    -> 合得进来 -> 读成 10           ✓
#   "12": |23-10| = 13  <= 18*1.2 = 21.6    -> 合得进来 -> 读成 12           ✓
# ⇒ 所以这个 bug 躲过了所有抽查:10、12 一直是对的,
#   **实测钉住读错的只有 "11"**(两个字形都窄:16 > 12)。
#   "21"/"31" 那种"第二个是 1"的数落在容差边缘(第二个字形左边缘离锚点约 21px,
#   而容差 20.4)= **同样不可靠**,只是手上没有真值帧钉它。
#   ★ 这一点也是新判据的动机:容差按"字形宽度"缩放,本来就会在窄字形上塌掉。
#
# 新判据用**数字自己的高度**当尺子,并且加一条竖向共高的闸 —— 后者才是真正
# 把 K/M 徽章挡住的那一条(徽章实测恒为 9x13,数字高 25 或 36):
#   ① 竖向重叠 >= 0.7 · 高   :徽章压在 25 高的数字上只占 11px = 44%,被挡掉;
#                              同一个数字的两个字形是 100%(实测)。
#   ② 水平空隙 <= 0.8 · 高   :实测同一个数字的两个字形之间只有 3~6px;
#                              徽章离字形右边 27px(在 25 高的尺度上)-> 也挡掉。
# ★ 老规则一条都不撤销(两条是"或"的关系)—— 这是**故意**的:
#   凡是今天能读对的帧,改完之后必须一模一样(kredits_numeral_ab.py 用全语料证这件事)。
MERGE_MODE_OLD = "width"        # 老:按字形宽度 max(w) * MERGE_WIDTH_RATIO
MERGE_MODE_STRUCT = "struct"    # 新:按数字高度(竖向共高 + 水平空隙)
MERGE_MODE = MERGE_MODE_STRUCT  # 出问题就一处退回:MERGE_MODE = MERGE_MODE_OLD
MERGE_WIDTH_RATIO = 1.2         # 老规则的宽度系数(一个字形的宽)
MERGE_MIN_VOVER = 0.7           # ① 竖向重叠 / 数字高
MERGE_MAX_GAP = 0.8             # ② 水平空隙 / 数字高

# ★★★ 2026-09-13 晚:**段数 × 高度必须自洽**(两条方向相反,依据都是同一份实测)。
# 实测(窗口客户区被 main_loop 强制成 1280x720,所以这些像素值是稳定的):
#   单位数:1 段,高 **33~37px**;两位数(游戏把数字整体缩小):2 段,高 **25px**;
#   "K/M" 徽章那一块恒为 9x13。
# 全语料高度直方图(612 帧,见 kredits_numeral_ab.py --verbose):
#   {25: 30 帧(其中 2 段 21 / 1 段 9), 33: 7 帧, 36: 405 帧, 43+: 4 帧}
# 于是两个方向的自相矛盾都不许猜:
#   ① **1 段 + 高 <= 30px** —— 那只能是两位数的**第一个字**被单独圈出来
#      (实测就是 "11" 读成 1 的那个 bug)。猜出来的 1 会让整回合只剩 1 费预算,
#      叠加用户规则 MIN_KREDITS_TO_SCAN=2 就是**整回合不扫手牌**。
#   ② **2 段 + 高 >= 33px** —— 单位数尺度下不可能有第二个字形,那是把别的块
#      (徽章/墨迹) 圈进来了;那会读出一个**偏高**的两位数,而偏高恰恰是这个类
#      唯一拦不住的方向(见类文档"剩余风险":偏高 -> 乱拖买不起的牌)。
# 两种都返回 None,让上层退回保守兜底(回合开始 = 上次采用值 +1)。
TWO_DIGIT_H_MAX = 30    # ① 高 <= 这个数 = 两位数尺度(25)
SINGLE_DIGIT_H_MIN = 33  # ② 高 >= 这个数 = 单位数尺度(33~37)

#: 最近一次 read_kredits 为什么没给出数字(诊断用;正常给数时是 None)。
#: 每次调用都会重置,所以读完之后它说的就是**这一次**的原因。
LAST_REJECT = None
#: 上面那条高度护栏的开关(A/B 用 —— kredits_numeral_ab.py 会把"关 / 开"都跑一遍):
#:   关 = 老行为(把截断的 "1" 当真值 1 -> 整回合只剩 1 费预算)
#:   开 = 自相矛盾时返回 None(上层退回"上次采用值 +1"这种保守兜底)
HEIGHT_GUARD = True


def _merge_ok(anchor, p, mode=None) -> bool:
    """
    这一块橙色是不是**同一个数字**的另一半?(判据与实测依据见上面的常量区)

    两条规则是"或"的关系(老规则一条都不撤销);但**竖向必须有重叠**是两条
    共同的底线 —— 竖向不沾边的两块,不可能是同一个数字的上下两半。
    """
    mode = mode or MERGE_MODE
    # 竖向重叠(不是"沾一点就算":下面的 ② 会按高度要求共高)
    ay1, ay2 = anchor["y"], anchor["y"] + anchor["h"]
    py1, py2 = p["y"], p["y"] + p["h"]
    vover = min(ay2, py2) - max(ay1, py1)
    if vover <= 0:
        return False

    # 老规则:横向在"一个字形宽"之内
    if abs(p["x"] - anchor["x"]) <= max(anchor["w"], p["w"]) * MERGE_WIDTH_RATIO:
        return True
    if mode == MERGE_MODE_OLD:
        return False

    # 新规则:按数字高度定尺(竖着共高 + 横向一个步距以内)
    taller = max(anchor["h"], p["h"])
    if vover < taller * MERGE_MIN_VOVER:
        return False
    gap = max(0, max(anchor["x"], p["x"])
              - min(anchor["x"] + anchor["w"], p["x"] + p["w"]))
    return gap <= taller * MERGE_MAX_GAP


def isolate_numeral(frame, box=OURS_BOX, merge_mode=None):
    """
    Return (numeral_bgr, numeral_mask, (fx, fy, fw, fh)) for the big Kredits
    numeral inside `box`, or (None, None, None) when nothing plausible is there.

    The numeral is orange, like the "K/M" badge to its right, but much taller.
    We therefore pick the tallest orange component as the anchor and then merge
    in every component that belongs to the same numeral - the stencil font can
    be cut into pieces by the HUD's ink-splatter decoration, and taking only the
    largest piece yields a truncated glyph (seen live: a 25x18 half-digit
    instead of a 25x36 numeral).

    ★ 2026-09-13 晚:合并判据换成 `_merge_ok`(两条规则,见常量区的实测依据)
      —— 老判据会把 "11" 读成 "1"(9 张真值帧)。`merge_mode` 只给 A/B 工具用。
    """
    x1, y1, x2, y2 = box
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None, None, None
    b, g, r = (crop[:, :, i].astype(int) for i in range(3))
    orange = ((r > 130) & (r - b > 50) & (g > 50)).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(orange, 8)
    if n <= 1:
        return None, None, None

    # gather plausible glyph pieces (drop specks and the wide "K/M" badge)
    pieces = []
    for i in range(1, n):
        px = int(stats[i, cv2.CC_STAT_LEFT])
        py = int(stats[i, cv2.CC_STAT_TOP])
        pw = int(stats[i, cv2.CC_STAT_WIDTH])
        ph = int(stats[i, cv2.CC_STAT_HEIGHT])
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < 40:
            continue
        pieces.append({"i": i, "x": px, "y": py, "w": pw, "h": ph})
    if not pieces:
        return None, None, None

    anchor = max(pieces, key=lambda p: p["h"])
    if anchor["h"] < 18:
        return None, None, None

    merged = [anchor]
    for p in pieces:
        if p is anchor:
            continue
        if _merge_ok(anchor, p, merge_mode):
            merged.append(p)

    mx1 = min(p["x"] for p in merged)
    my1 = min(p["y"] for p in merged)
    mx2 = max(p["x"] + p["w"] for p in merged)
    my2 = max(p["y"] + p["h"] for p in merged)
    cw, ch = mx2 - mx1, my2 - my1
    if ch < 18 or cw < 6 or cw > ch * 2.0:
        return None, None, None

    keep = np.zeros_like(orange)
    for p in merged:
        keep[labels == p["i"]] = 255
    return (crop[my1:my2, mx1:mx2],
            keep[my1:my2, mx1:mx2],
            (x1 + mx1, y1 + my1, cw, ch))


def read_kredits(frame, box=OURS_BOX, record_samples=False, _sample_counter=[0],
                 merge_mode=None, height_guard=None):
    """
    Current Kredits as an int, or None when not confidently readable.

    None is a deliberate, safe answer: the engine then falls back to learning
    affordability from refused drags. A wrong number would be worse than no
    number, because it would make us skip cards we can actually pay for.

    Reading pipeline: isolate the numeral -> split into digit glyphs -> match
    each glyph against the recorded template bank (kredits_templates).

    ★ 两个 A/B 参数只给 kredits_numeral_ab.py 用,生产路径一律用默认值。
    """
    global LAST_REJECT
    LAST_REJECT = None
    if height_guard is None:
        height_guard = HEIGHT_GUARD
    numeral, mask, bbox = isolate_numeral(frame, box, merge_mode=merge_mode)
    if numeral is None:
        LAST_REJECT = "费用区域里没圈到橙色数字"
        return None

    if record_samples:
        os.makedirs(SAMPLES_DIR, exist_ok=True)
        idx = _sample_counter[0]
        _sample_counter[0] += 1
        big = cv2.resize(numeral, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        cv2.imwrite(os.path.join(SAMPLES_DIR, f"numeral_{idx:05d}.png"), big)
        cv2.imwrite(os.path.join(SAMPLES_DIR, f"numeral_{idx:05d}_mask.png"),
                    cv2.resize(mask, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST))

    try:
        import kredits_templates as kt

        segments = kt.split_glyphs(mask)
        if not segments:
            LAST_REJECT = "字形切不出任何一段"
            return None
        if len(segments) > 2:
            LAST_REJECT = f"切出 {len(segments)} 段(上限是 2)"
            return None                      # 上限 24,最多两位
        # ★★★ 2026-09-13 深夜:**段数 × 高度必须自洽**(两条方向相反,见常量区的实测)。
        #   ① 只圈到一个字形、高度却是两位数尺度 -> 判为圈漏了第二个字,不猜
        #      (实测就是 "11" 读成 1 那个 bug:猜出来的 1 会让整个回合只剩 1 费预算,
        #       叠加用户规则 MIN_KREDITS_TO_SCAN=2 就是**整回合不扫手牌**)。
        #   ② 圈到两个字形、高度却是单位数尺度 -> 判为多圈进了别的块,不猜
        #      (那会读出一个**偏高**的两位数 —— 偏高是这个类唯一拦不住的方向)。
        if bbox is not None and height_guard:
            gh = bbox[3]
            if len(segments) == 1 and gh <= TWO_DIGIT_H_MAX:
                LAST_REJECT = (f"只切出一个字形,高度却只有 {gh}px"
                               f"(两位数尺度;单位数是 {SINGLE_DIGIT_H_MIN}~37px)"
                               f"-> 判为圈漏了第二个字,不猜")
                return None
            if len(segments) == 2 and gh >= SINGLE_DIGIT_H_MIN:
                LAST_REJECT = (f"切出两个字形,高度却有 {gh}px"
                               f"(单位数尺度;两位数是 {TWO_DIGIT_H_MAX}px 以下)"
                               f"-> 判为多圈进了别的块(徽章/墨迹),不猜")
                return None
        digits = []
        for x1, x2 in segments:
            glyph = kt.normalize_glyph(mask[:, x1:x2])
            d, _score = kt.match_digit(glyph)
            if d is None:
                LAST_REJECT = "有字拒识(模板分低于阈值)-> 整体不猜"
                return None                  # 有字拒识 -> 整体不猜
            digits.append(str(d))
        return int("".join(digits))
    except Exception as e:
        LAST_REJECT = f"读取出错 {type(e).__name__}: {e}"
        return None


class KreditsTracker:
    """
    把"读一帧数字"变成"一个不会抖、也不会被一次误读带偏的回合预算"。

    ★ 为什么必须去抖(PROJECT_STATE §8 待办 10,实测):
      同一秒内 `read_kredits` 会在 unknown 和 5 之间来回跳
      (日志 02:21:46 / 02:21:47)。后果不是"偶尔少读一个数",而是一条
      把整个回合毁掉的连锁:

          费用 unknown
            -> 惰性扫描不知道"现在出得起什么"(budget=None)
            -> 退回全量扫描(14 秒,而且实测常常扫回 0 张牌)
            -> 整回合不出牌

      也就是说:读数抖动直接吃掉了惰性扫描的 3 倍提速,还顺带把回合打空。

    ============ 规则只有两条,每条都对应一条能确认的游戏规则 ============

      R1 **连续采样,两帧读到同一个值才采信。**
         抖动正是"读到 / 读不到"交替,两帧一致就能过滤掉;代价 0.1-0.4 秒,
         比退回全量扫描(14 秒)便宜两个数量级。

      R2 **回合开始时的剩余费用 = 本回合上限,而上限只会涨、不会跌。**
         所以"读到的值 < 上一次采用的值"是**物理上不可能**的,只能是读错了:
         这种读数不采信,改用 `上次采用值 + 1`(上限至少涨了 1,这是下限,
         不会高估),并且**锚点不被这次误读改动** —— 下一回合读到真值立刻追上。

    ============ 为什么【不做】上界检查(做过两版,都被实机打脸) ============

      第一版把"上限每回合只 +1"当上界,越界就压回区间。两个问题:
        ① 假设**本身是错的**:特殊卡可以额外增加上限,一回合涨 2 以上是合法的;
        ② 它会**把误差永久固化**:一次误读被压到 `prev` 后锚点就落后 1,
           下一回合真实值 `prev+2` 又被压成 `prev+1`…… 从此**每个回合都少
           1 费、少出一个单位**。实测日志:
             12:05:47 读出 1(真值 11)-> 被压回 10
             12:06:25 读出 12(真值 12)-> 又被压成 11
      第二版为了修①又引入"**第 N 回合上限就是 N**"来给出上界 —— 同样是错的
      假设(特殊卡能加上限),而且进程重启 / 中途接管一局时回合数根本对不上:
        实测重启后日志 `第 3 回合 | kredits read: 12`。

      → **结论:只拒绝物理上不可能的读数,其余一律相信读数本身。**
        唯一的硬上界是游戏的 24。这样一次误读的代价被限制成"这一回合少 1 费",
        下一回合读到真值自动追上,**不会累积**。

      ★ 顺带说清一件事:**这个类不需要知道"现在是第几回合"**。
        `turns_seen` 只是诊断计数器(本进程看到第几个我方回合),不参与决策。

    ============ 剩余风险(明确记下来,不装作没有) ============
      两帧一致但**读得偏高**的误读不会被拦住(没有可靠上界可用)。代价有界:
      本回合多拖几次(每次约 2 秒,被拒绝的牌留在手上),而且
      `Affordability.note_deploy_failed` 会立刻把可负担上限压下来。
      实测至今**没出现过**偏高误读(出现的是把 11 读成 1)。
      日志里会把涨幅写出来(`较上次 +2`),真出现了一眼能看见。

    方向:只有"读低了"会被拒绝,所以系统在怀疑时**永远偏低**,不会偏高 ——
    高估才会让引擎去拖一张出不起的牌(白拖,正是用户看到的"乱拖")。

    用法(只在**回合开始**用;回合中费用会因为出牌下降,R2 不适用):

        t = KreditsTracker(capture=lambda: capture_client_bgr(hwnd))
        t.start_turn()                      # 每进入一个我方回合调一次(诊断计数)
        info = t.read_turn_start(frame)     # {'value','source','measured',...}
    """

    #: source 取值 -> 这个值有多可信
    #:   agree/majority    两帧以上读到同一个值并被采信(measured=True)
    #:   single            只读出一帧(measured=True,但没被第二帧确认)
    #:   settled           等到费用数字**停止滚动**之后的读数(回合开始用,最可信)
    #:   settled-timeout   等超时了 -> 用滚动过程中见过的最大值(可能有偏小)
    #:   读低了不采信       读数低于上次采用值(不可能)-> 用 上次值+1
    #:   prev+1            一帧都没读到 -> 用 上次采用值+1(下限)
    #:   estimate          连历史都没有 -> 用 1(KARDS 第一回合就是 1 费)
    MEASURED_SOURCES = ("agree", "majority", "single", "settled",
                        "settled-timeout")
    MAX_KREDITS = 24        # 游戏硬上限(见 §5 游戏机制要点)

    # ★★★ 2026-09-13(第十个会话):**回合开始时那个费用数字是"滚"上去的。**
    #
    # 实机证据(只读探针,0.07s 采一次,整个回合转折都拍下来了):
    #   `17:33:00.35 kredits=None` -> `17:33:01.16 kredits=6`
    #   -> `17:33:01.30 kredits=7` -> `17:33:01.44 None` -> `17:33:01.93 kredits=7`
    #   另一次:`17:31:22.7 None` -> `17:31:23.3 5` -> 稳定 5,
    #   而引擎在 `17:31:21` 读到的是 **3** —— 也就是说**数字正从低往高滚**,
    #   引擎读的是滚动途中的中间值。
    #
    # 后果(**这正是用户报的"有费用却没下"**):
    #   预算被读小 -> 惰性扫描按小预算挑牌 -> 便宜的挑不到就不出了;
    #   而 `MIN_KREDITS_TO_SCAN=2`(用户要求"剩不到 2 费就别扫手牌")叠上去,
    #   **读到 1 就把整个回合的手牌识别都跳过**。
    #   实测这一局(2026-09-13 17:29 起)连续两个回合读到 1、1 而画面是 3/3,
    #   于是连着两个回合"出牌结束(尝试 0 次)"。
    #
    # 判据:**数字不再变大 + 稳住这么久**才算停住。
    #   ★ 只要求"稳"是不够的:滚动途中每个值都会短暂稳定;
    #     所以还要求它是**到目前为止见过的最大值**(计数器只会往上滚)。
    #   ★ 为什么是 1.0 秒:实机逐帧看到滚动途中相邻两个值之间的间隔约
    #     0.14~0.5 秒(17:33:01.16=6 -> 01.30=7),取 1.0s 就比"任何一步的
    #     停顿"都长。
    TURN_START_SETTLE = 1.0     # 不再变大之后,再稳这么多秒
    TURN_START_MAX_WAIT = 3.5   # 最多等这么久(超时就用见过的最大值)
    # ★★ 还嫌不够 —— 实机把整段滚动拍下来了(`shots/kredits_anim2/_strip.png`):
    #     我方回合一开始,费用牌是 **0 K/9 -> 1 K/10 -> 2 K/10 -> 4 K/10 -> 10 K/10**,
    #     也就是说**滚动途中的第一个值(1)可以稳定地停 1 秒以上**,
    #     而"稳 1.0 秒"这条规则正好会在那个 1 上停下来(实机日志
    #     `kredits read: 6 [settled->不采信] 采样 [1,1,1,1,1,1,1,1]`)。
    #     ⇒ 再加一条**最短观察窗**:不管多稳,先看够这么久再说。
    #     2.0 秒覆盖了实测的整段滚动(0.8~1.4 秒)+ 起始那一段停顿。
    #   ★ 代价:每个回合开始多花约 2 秒。换来的是"预算到底是多少"这件事
    #     不再依赖"上一次的值恰好对"(`_plausible` 的 R2 只能挡住偏低,
    #     挡不住偏高 —— 偏高会白白多拖一次)。
    TURN_START_MIN_WINDOW = 2.0

    def __init__(self, capture=None, read_one=None, attempts: int = 4,
                 gap: float = 0.10, log=None, debug: bool = False,
                 sleep=time.sleep, turn_start_settle=None,
                 turn_start_max_wait=None, turn_start_min_window=None,
                 clock=None, trunc_guard: bool = True):
        self.capture = capture          # () -> frame or None
        self.read_one = read_one or read_kredits
        self.attempts = max(1, int(attempts))   # 最多再补采几帧
        self.gap = gap
        self.log = log
        self.debug = debug
        self._sleep = sleep
        # ★ 两位数"截断误读"的护栏(见 _plausible)。关掉它只是日志变糊,
        #   取值不变(理由写在那条护栏的注释里),留着一键退回。
        self.trunc_guard = bool(trunc_guard)
        # ★★★ 阶段 2("等数字停止滚动")的两个参数。`turn_start_settle=0`
        #   就是**一键退回老行为**(只做阶段 1 的"两帧一致"),单测里用得上。
        self.turn_start_settle = (self.TURN_START_SETTLE
                                  if turn_start_settle is None
                                  else turn_start_settle)
        self.turn_start_max_wait = (self.TURN_START_MAX_WAIT
                                    if turn_start_max_wait is None
                                    else turn_start_max_wait)
        self.turn_start_min_window = (self.TURN_START_MIN_WINDOW
                                      if turn_start_min_window is None
                                      else turn_start_min_window)
        # 时钟可注入 —— 否则那个"等它稳 0.6 秒"的判据在离线用例里**只能靠真等**。
        self._clock = clock or time.monotonic
        # ★ 诊断计数:本进程看到第几个我方回合。
        #   **不参与任何决策** —— 回合数不等于费用上限(特殊卡能加上限,
        #   重启后计数也不等于真实进度)。
        self.turns_seen = 0
        # ★ 锚点:**上一次采用**的值(不是"实测"值)。
        #   只有在采信了一个读数时才推进;被拒绝的读数不动它,
        #   这样"一次误读"只会影响这一个回合。
        self.last_value = None
        self.last_measured = None       # 上一次真正读出来的值(纯诊断)
        self.history = []               # [(turns_seen, value, source)] 诊断/单测

    # --- 生命周期 ---
    def start_turn(self) -> int:
        """进入一个新的我方回合(只用于诊断计数,不参与决策)。"""
        self.turns_seen += 1
        return self.turns_seen

    def reset(self):
        self.turns_seen = 0
        self.last_value = None
        self.last_measured = None
        self.history = []

    # --- 读一次 ---
    def _one(self, frame):
        try:
            return self.read_one(frame)
        except Exception as e:                  # 读不出来不该弄崩一个回合
            if self.debug and self.log:
                self.log(f"[kredits] 读取出错: {type(e).__name__}: {e}")
            return None

    def read_turn_start(self, frame=None) -> dict:
        """
        读本回合的费用。返回 dict:
          value     int 或 None
          source    见 MEASURED_SOURCES 注释
          measured  这个值是不是真的从画面读出来的
          samples   这次读到的原始值序列(诊断用)
          note      人话说明(直接可以打进日志)
        """
        samples = []
        if frame is not None:
            v = self._one(frame)
            if v is not None:
                samples.append(v)

        extra = 0
        while extra < self.attempts:
            if len(samples) >= 2 and samples[-1] == samples[-2]:
                break                            # 两帧一致 -> 够了
            extra += 1
            self._sleep(self.gap)
            if self.capture is None:
                continue
            f = self.capture()
            if f is None:
                continue
            v = self._one(f)
            if v is not None:
                samples.append(v)

        # ★★★ 阶段 2:等费用数字**停止往上滚**(见 TURN_START_SETTLE 的实机证据)。
        #   为什么"两帧一致"不够:滚动途中同样会出现两帧一致 ——
        #   实机就是这么把 3 当成真值采信的(真值 5),而这一次采信直接
        #   决定了整个回合的预算。
        settled, via = self._wait_until_settled(samples)
        if settled is not None:
            value, source, note = self._plausible(settled, via, samples)
        else:
            value, source, note = self._decide(samples)
        if value is not None:
            # 采用值成为下一回合的锚点。★ 注意:被拒绝的读数**不动锚点** ——
            # 这是"误读不会累积"的关键(见类文档 R2)。
            self.last_value = value
        if source in self.MEASURED_SOURCES:
            self.last_measured = value
        self.history.append((self.turns_seen, value, source))
        return {"value": value, "source": source, "measured":
                source in self.MEASURED_SOURCES, "samples": samples,
                "note": note}

    # --- 判定 ---
    def _wait_until_settled(self, samples):
        """
        等费用数字**不再往上滚**为止,返回"停住的那个值"(等不到/被关掉就返回 None)。

        判据(两条都要满足,理由见 `TURN_START_SETTLE`):
          ① 当前读数 == **到目前为止见过的最大值**(计数器只会往上滚,
             所以没到最大值就说明它还在滚);
          ② 这个值已经稳了 `TURN_START_SETTLE` 秒(排除"滚动途中短暂停顿")。
        超时(`TURN_START_MAX_WAIT`)时返回见过的**最大值** —— 计数器只涨不跌,
        所以那是当下最合理的估计;`_plausible` 还会再拿锚点过一道。

        ★ `turn_start_settle<=0` 就是**一键退回老行为**(A/B 开关)。
        ★ 读不到帧(None)不重置"稳定计时" —— 滚动途中本来就会有几帧读不出来。
        """
        settle = self.turn_start_settle
        if settle <= 0 or self.capture is None:
            return None, None
        max_wait = self.turn_start_max_wait
        clock = self._clock
        t0 = clock()
        min_window = self.turn_start_min_window
        last = samples[-1] if samples else None
        last_change = t0
        while clock() - t0 < max_wait:
            self._sleep(self.gap)
            f = self.capture()
            if f is None:
                continue
            v = self._one(f)
            if v is None:
                continue
            samples.append(v)
            now = clock()
            if last is None or v != last:
                last, last_change = v, now
                continue
            top = max(samples)
            # ★ 两道闸都要过:① 最短观察窗(挡住"滚动刚开始那段停得久的低值")
            #                  ② 已经稳了 settle 秒,而且它是见过的最大值
            if (now - t0) >= min_window and last >= top \
                    and (now - last_change) >= settle:
                return last, "settled"
        if not samples:
            return None, None
        # 超时:数字一直在滚(或一直读不到稳定值)-> 用**见过的最大值**
        # (计数器只涨不跌,所以那是当下最合理的估计)。日志里用不同的 source
        # 标出来,免得事后分不清"真稳住了"和"等超时了"。
        return max(samples), "settled-timeout"

    def _decide(self, samples):
        if not samples:
            return self._fallback()
        counts = {}
        for v in samples:
            counts[v] = counts.get(v, 0) + 1
        # 出现次数最多;平票取**更小**的值(保守方向)
        top, n = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if n >= 2:
            label = "agree" if n == len(samples) else "majority"
        else:
            label = "single"
        return self._plausible(top, label, samples)

    def _plausible(self, value, source, samples):
        """
        ★★ 只拒绝**物理上不可能**的读数,其余一律相信读数本身。

        可以确认的游戏规则只有两条(用它们当判据,不引入任何额外假设):
          - 回合开始时的剩余费用 = 本回合上限;
          - 上限**只会涨、不会跌**,而且每回合**至少** +1。

        所以唯一"不可能"的情况是:**读到的值 < 上一次采用的值**。
        这种读数一定是错的(实测:第 11 回合把 11 读成了 1),
        这时用 `上次采用值 + 1`(上限至少涨了 1),并且**不更新锚点**
        —— 于是下一回合读到真值就能立刻追上,误差不会累积。

        ★ 这里**故意不做上界检查**(例如"每回合只 +1"):
          那是错的假设(特殊卡可以额外增加上限),而且会把一次误读的误差
          **永久固化**成"每个回合都少 1 费"(见类文档里的实机日志)。
          唯一的硬上界是游戏的 24。
        """
        prev = self.last_value
        if prev is None:
            if not (1 <= value <= self.MAX_KREDITS):
                return self._fallback(
                    extra=f"读到的 {value} 不在 1..{self.MAX_KREDITS} 之内")
            return value, source, f"{source} {samples}(首次读数,直接采信)"

        # ★★★ 2026-09-13 晚:**两位数"截断误读"的护栏,从回合中途搬到回合开始。**
        #   回合中途那条在 `turn_engine._resync_kredits_after_actions`(§7 第 93 条,
        #   判据完全一样:读数正好是账本的首位数字 -> 判为截断)。这里补上回合开始
        #   这条路 —— 实机证据(19:27:48):
        #     `kredits read: 11 [settled-timeout->不采信] 采样 [1,3,5,1,1,1,1,1,…]`
        #   真值 11,读取一路给出 1,靠 R2 的"上次 +1 = 11"才补回来(**那次是运气**:
        #   正好每回合涨 1)。
        #   ★ 说清楚它买到的是什么:取值上和下面的 R2 **结论相同**(都用 prev+1,
        #     因为回合开始的费用只会涨,prev+1 是不会高估的下限),
        #     它买到的是**日志里说得清说不清** —— 同一行 `不采信`,现在能一眼看出
        #     是"读到了两位数的首位数字",而不是"读数抖动"。
        #   ★ 判据成立的前提(可确认的游戏规则):回合开始时 值 >= prev+1 >= 11,
        #     所以读到 prev 的首位数字**不可能是真值**。
        if self.trunc_guard and prev >= 10 and value == prev // 10:
            return self._reject(prev, source, samples,
                                f"读数 {value} 正好是上次采用值 {prev} 的"
                                f"**首位数字** -> 判为两位数的截断误读"
                                f"(两位数只圈到一个字形;见 kredits.MERGE_MODE)")
        if value < prev:
            # 唯一能确认的"读错了":回合开始时的费用绝不会下降
            return self._reject(prev, source, samples,
                                f"低于上一次采用值 {prev}"
                                f"(回合开始时费用只会涨不会跌)")
        if value > self.MAX_KREDITS:
            return self._reject(prev, source, samples,
                                f"超过游戏上限 {self.MAX_KREDITS}")
        jump = value - prev
        tail = f",较上次 +{jump}" if jump > 0 else ",与上次持平"
        return (value, source,
                f"{source} {samples}(上次采用值 {prev}{tail})-> 采信")

    def _reject(self, prev, source, samples, why: str):
        """
        读数不可信 -> 用**下限** `上次采用值 + 1`。

        为什么是 +1 而不是沿用上次的值:上限每回合**至少**涨 1,所以
        `prev + 1` 是不会高估的下限;而沿用 `prev` 会让锚点停在原地,
        把"落后"一路带下去(那正是 §7 第 54 条那个永久滞后的坑)。
        锚点跟着推进到下限,下一回合只要读到真值(必然 ≥ 下限)就原样采信,
        误差**不会累积**。
        """
        used = min(prev + 1, self.MAX_KREDITS)
        return (used, f"{source}->不采信",
                f"{source} {samples} {why} -> 这次不采信,"
                f"用下限 {used}(上次采用值 {prev} +1,取小不会高估)")

    def _fallback(self, extra: str = ""):
        """
        一帧都没读出来。

        有历史:用 `上次采用值 + 1`(上限至少涨了 1,这是个**下限**,
                所以不会高估)。
        没历史:用 1(KARDS 第一回合就是 1 费,这是唯一不需要假设的值)。
        """
        if self.last_value is not None:
            used = min(self.last_value + 1, self.MAX_KREDITS)
            return (used, "prev+1",
                    f"一帧都没读到 -> 用下限 {used}(上次采用值 "
                    f"{self.last_value} +1;上限至少涨 1,取小不会高估)"
                    + (f" [{extra}]" if extra else ""))
        return (1, "estimate",
                "一帧都没读到且没有历史 -> 取 1"
                "(游戏第一回合上限就是 1,不需要任何假设)"
                + (f" [{extra}]" if extra else ""))

    def describe(self):
        if not self.history:
            return "还没读过"
        return " ".join(f"T{t}={v}({s})" for t, v, s in self.history[-6:])


class Affordability:
    """
    Tracks how much we are willing to spend, learned from real deploys.

    two independent limits, whichever is tighter:
      observed  - last numeric Kredits read from the HUD, when it was readable
      max_cost  - cap learned from a refused deploy (cost N failed -> N-1)

    turn started        -> nothing learned yet (optimistic)
    read Kredits = 2    -> only cards costing <= 2 are attempted
    deploy of cost 3    -> refused -> max_cost = 2
    """

    def __init__(self):
        self.max_cost = None       # None = no upper bound learned yet
        self.observed = None       # last successful read_kredits value

    def reset_turn(self):
        self.max_cost = None
        self.observed = None

    def note_read(self, value):
        if value is not None:
            self.observed = value

    def can_afford(self, cost, allow_unknown: bool = False):
        """
        allow_unknown=True 时,cost 未知(None)也允许尝试 —— 这是故意的。

        以前 None 一律返回 False,后果是:一张卡名读不出的牌(PROJECT_STATE
        第 35 条:纯英文+数字卡名、被 HUD 横幅挡住的卡名)费用也读不出,
        于是引擎永远不碰它,整局压在手牌里出不去,而它很可能只是个 1 费小兵。

        现在引擎对"未知牌"传 allow_unknown=True:试一次。KARDS 对买不起的牌
        是静默拒绝(牌留在手上),最坏结果只是白拖一次,而 note_deploy_failed
        会立刻把可负担上限压下来,不会反复试。已知 cost 时行为完全不变。
        """
        if cost is None:
            return bool(allow_unknown)
        if self.max_cost is not None and cost > self.max_cost:
            return False
        if self.observed is not None and cost > self.observed:
            return False
        return True

    def note_deploy_failed(self, cost):
        """A deploy that did not happen was almost certainly too expensive."""
        if cost is None:
            return
        cap = cost - 1
        self.max_cost = cap if self.max_cost is None else min(self.max_cost, cap)

    def note_deploy_ok(self, cost):
        if cost is not None:
            self.max_cost = None   # we know at least this much was affordable

    def describe(self):
        parts = []
        if self.observed is not None:
            parts.append(f"kredits read {self.observed}")
        if self.max_cost is not None:
            parts.append(f"learned cap {self.max_cost}")
        return "affordable: " + (", ".join(parts) if parts else "unknown (optimistic)")
