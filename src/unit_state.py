"""
unit_state.py - 读一张场上单位卡"这回合还能不能行动"。

用户 2026-09-11 给的判据
------------------------
**单位卡左上角的费用数字:橙色 = 这回合还能移动/攻击;灰色 = 本回合已行动。**
变的是【数字本身】的颜色,小方块的底色不变(用户框了一次给我确认:
存的模板 `ui_templates/cost_num.png` 就是深色方块上的一个橙色 "1")。

为什么不能用"卡框 + 固定偏移"去取那个数字(★ 踩过两次)
-------------------------------------------------------
1. 旧代码用 `find_units()` 的卡框按比例取"左上角",实测那框偏下 ~20px、偏窄 ~15px,
   取到的是卡面美术。
2. 换成新的检测框之后我仍然取偏 —— 直到量出来才明白:
   **徽章本身是深色的**,它把卡的左上角从"亮部掩码"里挖掉了,
   所以新检测框的**左边界是从徽章右边开始的**(实测偏右 30+px)。
   → 结论:别再"按相对位置推算",**直接检测徽章本身**。

实测标定(2026-09-11 中午,`shots/badge/live.png` 人工核对过)
-------------------------------------------------------------
徽章 = 卡左上角一个 **深色小方块(实测 17~19 px 见方)**,里面一个亮色数字。
数字像素的颜色把"能行动"和"不能行动"分得非常开:

    能行动(橙)  S ≈ 160 ~ 178
    不能行动(灰) S ≈  30 ~  51

所以判据用**数字像素的平均饱和度 S**,阈值 110 / 70 之间留出灰带 ——
落在灰带里返回 None,调用方一律当"不能行动"(宁可少打一次,也不要乱拖)。

★ 实测同时发现:徽章可以直接当**我方可行动单位的定位器**(见
`actionable_units`)。这比走卡框可靠 —— 卡框在相邻卡粘连时会合并/漏掉
(实测漏过整张卡),而徽章是独立的小方块,不会被粘走。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np

import board

# ---- 徽章几何(实测) ----
BADGE_W_MIN, BADGE_W_MAX = 14, 22
BADGE_H_MIN, BADGE_H_MAX = 14, 22
BADGE_FILL_MIN = 0.55          # 深色方块的实心度
BADGE_DIGIT_V = 135            # 数字比底色亮:V 超过这个算"数字像素"
# ★★ 只靠 V 会漏掉**暗一些的橙色数字**(2026-09-11 下午实测,见下):
#   被漏掉的那个徽章(我方支援线第 4 张卡)数字是 **橙色 S=169**,但 **V 只有 141**
#   —— 只有 1 个像素过得了 V>135,于是被 `BADGE_DIGIT_MIN_PX` 挡掉,
#   整张卡在"数场上卡数"里消失,而它明明是能行动的单位。
#   同一个徽章里的橙徽章(@439)是 V=202/S=116,可见**橙色数字的亮度本身就不固定**。
#   所以"数字像素"的判据必须写成 **亮(V高) 或 饱和(S高)** —— 两者任一成立都算:
#   灰色数字走 V(它亮但不饱和),橙色数字走 S(它饱和但可能不够亮),
#   而徽章底色是**又暗又不饱和**的深灰方块,两者都进不来。
BADGE_DIGIT_S = 90             # S 超过这个也算"数字像素"(橙色数字)
BADGE_DIGIT_MIN_PX = 12        # 至少要有这么多数字像素
# ★ 从 6 提到 12:实测"卡的角"上那种假徽章正好卡在 6(它只蹭到一两条亮列),
#   而真徽章的数字像素实测 52~111,提到 12 不影响真徽章。

# ---- 数字像素判据(v3:"被暗包住的亮块",2026-09-11 晚) ----
# ★★ 修的是一个**会导致"把不能行动的牌拖出去"**的真 bug(和 §10 那条规则直接冲突):
#   旧判据 `(V>135)|(S>90)` 是**绝对**的,于是**徽章自己的底色**只要够饱和
#   就全被算成"数字像素"。实测(`badge_tile_probe.py`,`shots/deploy_probe`)抓到:
#       x877 y455 18x18 S=135.3 V=53.3 n=316 -> orange
#   n=316/324、V=53 —— 整块窗口都是"数字像素"且都很暗,说明它是**深棕底色**,
#   平均饱和度被底色拉到 135,于是一个**灰数字(已行动)**被判成橙色。
#   金边卡上徽章底色就是深棕(实测 S≈137~149),这种卡一多,"橙色徽章"就满天飞。
#
# ★ 中间还试过一版"数字 = 比底色明显更亮的像素"(相对阈值),**也翻车了**:
#   连通域给出来的包围盒里会混进卡顶边的**中间灰**(V≈99~119,刚好卡在
#   `BADGE_DARK_V=120` 下面),于是"数字"包围盒贴到窗口边框,判据整个失效
#   (实测:一个**已经检出的真徽章**被判成"没有数字",整行徽章全灭)。
#
# ★ v3 = 换一个**不依赖阈值**的说法:**数字是被深色方块围住的一块亮**。
#   实现 = 窗口里对"亮"做泛洪,能连到窗口边框的叫"外面",连不到的就是"洞"。
#   不管底色是深灰、深棕还是暗红,只要数字被围住就认得出;而"窗口没套准"
#   也自动失效(数字贴到边框 = 它连到外面,不是洞)。
DIGIT_DARK_V = 120             # "亮"的绝对线:V 高过它一定算亮
#   ★★ 但**只看绝对线不够**:金边卡上那个"灰数字"实测 **V 只有 115~119**
#     (`shots/board_samples/0911_122530_001.png` 我方支援线,人眼看就是浅灰),
#     而 CARD 的深棕底色 V≈28。差着 4 倍,眼睛一眼就看得出,绝对阈值却把它
#     和底色一起归成"暗" -> 洞里什么都没有 -> **整张卡的徽章都检不出来**。
#     所以"亮"要**相对这一块的底色**判:`V >= min(BADGE_DARK_V, 底色+45)`。
DIGIT_REL_DELTA = 45           # 比这一块的底色亮这么多也算"亮"
DIGIT_BG_PCT = 40              # 底色估计用的百分位(数字只占 10~30%)
DIGIT_MIN_PX = 20              # 洞至少这么大才算"有一个数字"
#   ★ 从 8 提到 20:实测"火焰/士兵美术上的一小块亮斑"正好卡在 n=9
#     (两例:`f014 x568 y106 n9` 是爆炸火光、`f028 x676 y465 n9` 是士兵身上),
#     而**真徽章的数字实测 n=36~85**。20 落在两者中间。
DIGIT_MAX_PX = 200             # ★ 上限:数字是深色方块里的一小块,不可能占满
DIGIT_BLOB_MIN_PX = 6          # 单个连通小块的面积下限(滤掉一两个像素的噪点)
DIGIT_BLOB_W_MAX = 18          # 数字包围盒宽度上限(容许两位数)
DIGIT_BLOB_H_MIN = 7           # 数字包围盒高度下限(数字是**竖长**的,噪点是方的)
DIGIT_BLOB_H_MAX = 19          # 数字包围盒高度上限
DIGIT_AREA_FRAC_MAX = 0.45     # 洞占窗口的比例上限
DIGIT_OFF_MAX = 0.12           # ★ 数字中心必须**靠近窗口中心**(归一化偏移上限)
#   ★★ 这一条是"窗口套准了没有"的判据,也是补检假阳性的主要过滤器。
#     实测(`badge_feat_probe.py`,正样本=连通域版 307 个 / 补检独有 67 个):
#       正样本的 off: 中位 0.03, 最大 0.16, **只有 1 个超过 0.12**
#       补检独有:     23 个 off<0.05, **6 个 off>0.10**(最大 0.29)
#     也就是说"数字不在方块正中间"的候选基本都是卡面美术/悬停面板的巧合,
#     而真徽章的数字一定被关在方块正中。取 0.12:正样本只丢 1 个,补检砍掉 6 个。

# ---- 滑窗签名判据(2026-09-11 下午,替代"连通域 + 尺寸过滤")----
# 见 find_cost_badges 的说明:徽章的深色方块**经常和旁边的暗部粘在一起**,
# 所以不能要求"深色连通域恰好是 18x18"。改成在每一个位置上问四个问题。
BADGE_WIN = 18                 # 徽章方块实测 17~19px,取 18
BADGE_DARK_V = 120             # V 低于这个算"暗"(徽章底色)
BADGE_INNER = 12               # 中间放数字的那块
BADGE_INNER_OFF = 3            # 内块相对窗口的偏移
WIN_DARK_MIN = 0.55            # ① 整个 18x18 窗口里暗像素的占比下限
INNER_DARK_MIN = 0.45          # ② 中间 12x12 里暗像素占比下限(数字之外是底色)
CONTEXT_DX = 20                # ④ 看窗口右边紧邻的这一段……
CONTEXT_OY = 4
CONTEXT_W = 10
CONTEXT_H = 10
CONTEXT_BRIGHT_MIN = 115.0     # ……它必须是**亮的卡顶条带**(徽章右边一定是浅色卡面)
# ★ 用"这一片里有多少像素够亮"的**占比**,而不是平均值 —— 平均值会被"一根亮条"
#   蒙过去:一个往左偏了 14px 的窗口,它右边那一片正好压在真徽章的**数字**上,
#   数字是亮的,均值于是也是亮的(实测 143),假窗口就这样通过了。
#   而真徽章右边是**整片**浅色卡面(实测整片 V>150),所以要求占比。
CONTEXT_BRIGHT_FRAC_MIN = 0.80
NMS_DIST = 20                  # 两个候选挨得比这近就算同一个徽章
# ★ 为什么是 20 而不是 9:滑窗会沿着真徽章的边缘**连续给出好几个候选**
#   (实测偏移到 12~16px 还在通过判据 —— 因为窗口挪出去半格时,右边/下边那两条
#   "必须是暗的"仍然盖在真徽章的方块上)。而两个真徽章之间至少隔 60px(同一行)
#   或 175px(相邻行),所以 20 远不足以把两张真卡并成一张。
# ⑤ 徽章方块的**右边 3 列**也必须是暗的。★ 这一条是用来干掉"卡的左边缘"那种
#    假徽章的:卡的左边是暗桌面、右边是亮卡面,于是"暗 + 亮"看起来很像徽章;
#    而真徽章是一个**四面都暗的方块**(实测 `V` 图里 18x18 方块的四条边都是暗的),
#    数字被关在方块中间。
RIGHT_STRIP_W = 3
RIGHT_DARK_MIN = 0.5
# ★★★ 2026-09-12 修正:徽章周围那条"必须是亮卡面"的判据**不能只看右边**。
#   旧判据(下面 ② 那一段)的假设是"徽章挂在卡的**浅色**顶边上,所以右边是卡面"。
#   实机抓到的反例(`shots/attack_frames/0912_032521_attack.png`,我方支援线):
#     那张战斗机卡的顶栏是**深橄榄绿**,徽章的深色方块右边紧挨着的就是深色标题栏 ——
#     于是 `badge_miss_diag.py` 逐条打出来是:
#       `x305 y457 18x18 数字像素 15 -> 上下文不亮`
#     **尺寸/实心度/数字像素全部合格**,只被这一条判掉。
#   后果(一局实机):我方单位整类检不出徽章 -> 看不到橙色 -> 不攻击也不上前线;
#   而且支援线单位数只能靠"行卡数−1"兜 -> 4 个单位读成 2~3
#   (用户逐条对过日志:032501-032629 / 032808 / 032846 / 033013 / 033015 全是这一条引起的)。
#   → 改成"**上 / 右 / 下 任一方向**有亮卡面即可"(亮的卡边在上下也成立)。
#   ★ A/B 开关:`BAND_CONTEXT_ANY=False` 就是旧行为,**必须**用它做 A/B
#     (换判据只看总数会同时掩盖"多收假的"和"丢掉真的"——§7 第 67 条 D)。
BAND_CONTEXT_ANY = True
CTX_UP_H = 4                   # 徽章**正上方**那几行(卡的浅色顶边)
CTX_DOWN_H = 4                 # **正下方**那几行
# ★★ 放宽"亮卡面"之后**必须**配一条横向去重(2026-09-12,同一次 A/B 里发现):
#   卡的**顶边是整条亮的**,所以"上面亮"这一条在卡的整个宽度上都成立 ——
#   滑窗于是能沿着卡顶**横向滑动**,同一张卡吐出好几个候选。
#   实测证据:`board_geom_test` 的"卡间距过小(<90px,真实卡距 125~161)"
#   从 **1 处涨到 27 处**。★ 这正是 §7 第 59 条那条纪律说的
#   "换判据不能只看总数,要看多收进来的是什么"。
#   同一条行上两张真卡的**中心距实测 125~161**,所以 90px 以内的两个候选
#   不可能是两张卡 -> 只留最暗的那个。
BAND_MIN_PITCH_PX = 90
# ⑥ 同理,**下边 3 行**也必须是暗的。★ 这一条用来干掉"卡的顶边"那种假徽章:
#    卡的顶边上下分别是"暗桌面"和"亮卡面条带",窗口里就是"上面暗、下面亮",
#    而真徽章是**一个四面都暗的方块**,数字被关在中间 —— 区别就在下边那几行。
BOTTOM_DARK_MIN = 0.5
# ⑦ 徽章正上方那 4 行必须是**亮的**。★ 这一条是"滑窗会不会整体上移"的判据:
#    徽章是**挂在卡的浅色顶边上**的(实测徽章上边距卡顶只有 ~4px),
#    所以它正上方是卡的顶边(亮);而一个"往上挪了十几像素"的窗口,
#    上面是**暗桌面** —— 这条直接把它判掉,不用再去猜中心在哪。
ABOVE_H = 4
ABOVE_BRIGHT_MIN = 115.0

# ---- 颜色阈值 ----
# ★★ 2026-09-11 晚**在新判据上重新标定了一遍**(改判据就必须重标:
#    数字像素的集合变了,旧阈值不再成立)。工具 `badge_s_calib.py`
#    —— 它把每一个徽章按 S 分档拼成小图,人眼一档一档确认。
#    实测 78 帧 / 374 个徽章:
#       S   0~ 60 : 241 个   -> 全是灰数字(白/浅灰)
#       S  60~ 90 :   6 个   -> 灰(个别偏暖)
#       S  90~105 :  35 个   -> **灰**(金边卡上的灰数字偏暖,实测 S≈90~99)
#       S 105~130 :   0 个   -> ★ **空档**
#       S 130~222 :  92 个   -> 全是橙色数字
#    所以阈值取在这个空档里:橙 >= 120(SAT_ORANGE_MIN)、灰 <= 105(SAT_GREY_MAX)。
# ★ 旧值(110 / 70)是在旧判据上标的;旧值把"金边卡上的灰数字"整类报成"读不准",
#   虽然行为上同样是"不攻击"(安全),但**日志在撒谎** —— 它说"读不准",
#   真相是"这个单位这回合已经行动过了"。诊断说谎是要付代价的(§7 反复吃过)。
SAT_ORANGE_MIN = 120           # S >= 这个 -> 能行动
SAT_GREY_MAX = 105             # S <= 这个 -> 不能行动
#                               中间(实测 105~130 是空档)= 读不准 -> None

# ★★★ 2026-09-15(实机 J9 + 200 帧语料 A/B):"**像橙又太暗**"的候选 = 这里根本没有徽章。
#   背景:木纹会被检成"橙色徽章"。证据帧 `shots/scan_frames/0915_184240_scan.png`
#   上 x706 y462 那个(band 路,S=136 V=124 n=55)—— 它就在我们总部卡右边的**空地
#   木纹**上(`shots/badge_false_ab/tiles_dim_orange.png` 里 7 张是同一个位置)。
#   ★ 为什么必须**整条丢掉**、而不是只标成"读不准":每个徽章都会反推出一张卡
#     (`unit_box_from_badge`),假徽章 = **凭空多一张卡**,照样污染"某一行有几张"。
#     实机那一轮 7 次 `[move] 没动成:我方支援 2->2,前线 X->X+1` 就是它造成的
#     (判据帧上单位其实已经站在前线)。
#   ★★ 为什么门槛**只管"高饱和 + 暗"这一族**(而不是更顺手的"数字太暗就丢"):
#     语料 A/B 里那个朴素写法一次丢掉 58 个,一大批是**真徽章** ——
#     `shots/board_samples/0911_122530_*.png`(用户当年逐张确认过的板面)整幅偏暗,
#     真的灰徽章 V 只有 104~124。所以**绝对亮度不能当全局判据**;
#     能分开的是"S≥120 且暗"这个组合:真橙徽章实测 V=154~209,
#     这族木纹 V=92~126 —— 中间是空的,门槛取 140。
ORANGE_V_MIN = 140.0


# ★★★ 2026-09-15(实机 J9):**位置守卫** —— 落在"已检出卡片的**下半部分**"的候选
#   不是费用徽章,而是卡面自己的数字/图标。
#   证据:`shots/badge_false_ab/tiles.png`(5 个被守卫丢掉的,全是卡底部那一排
#   `3 [类型图标] 6` 里的**类型图标** —— 深色圆角块 + 亮色剪影,和"徽章"长得一模一样),
#   它们都在卡框的 **81~87%** 高处;而真费用徽章长在卡**左上角**(实测 ~10%)。
#   为什么必须丢:每个徽章会反推出一张卡(`unit_box_from_badge`),假徽章 =
#   **凭空多一张卡**,直接污染"某一行有几张"的所有判据(上面前线那一族)。
#   ★ 两道限定,防止误伤:
#     ① 只在**已知卡框**里生效 —— 行带补检(`band`)存在的意义正是"卡框漏了这张卡",
#        那种情况没有卡框可比,守卫不动它;
#     ② 只在卡框高度**接近单张卡**时生效 —— 相邻两卡粘成的高框(>STAT_GUARD_H_MAX)
#        会让真徽章落到"下半部分",不能据此丢掉。
STAT_GUARD = True
STAT_REL_Y = 0.45              # 卡框内相对高度 >= 它 = 卡面数字区
STAT_GUARD_H_MAX = 200         # 卡框高过它 = 多半两张粘一起/放大悬停卡,不当容器

# ---- 板面与手牌的分界 ----
# 战场上三条线的费用徽章在 y≈105 / 280 / 455;手牌的费用徽章在 y≈565 以下。
# (实测手牌扇形会盖住我方那一行的下半部分,所以必须按 y 把两者分开。)
BOARD_BADGE_MAX_Y = 520

# ---- 从徽章推出"这张卡" ----
# 徽章在卡的左上角(实测 badge.x ≈ card.x + 3, badge.y ≈ card.y + 4),
# 单位卡约 130x146。拖动要从卡身上按下,所以取卡中心附近。
CARD_W_EST = 132
CARD_H_EST = 146
DRAG_FROM_DX = 60              # 从徽章到"卡身上可按下的一点"
DRAG_FROM_DY = 70


def _rectsum(a, h, w):
    """2D 数组里**所有** (h,w) 矩形和,用积分图 O(1) 每格。"""
    I = np.zeros((a.shape[0] + 1, a.shape[1] + 1), np.float64)
    I[1:, 1:] = a.cumsum(0).cumsum(1)
    return I[h:, w:] - I[:-h, w:] - I[h:, :-w] + I[:-h, :-w]


def enclosed_bright(Vc, dark_v=None):
    """
    在窗口里找出**被暗包住的亮块**(= 费用徽章里的那个数字)。

    做法:把"亮"的像素当成前景,从窗口外圈往里泛洪 ——
    **能连到窗口边框的亮像素属于"外面"**(卡面/桌面),**连不到的就是"洞"**。
    "洞"正是我们要的数字,而且这个说法**不需要任何"数字长什么样"的阈值**。

    "亮"的判据是**相对这一块的底色**的(`V >= min(DIGIT_DARK_V, 底色+45)`),
    不是绝对亮度 —— 理由见 `DIGIT_REL_DELTA` 那段:金边卡上的灰数字只有 V≈117。

    返回 (enclosed_mask, bright_mask),都是 bool 数组、和 Vc 同形状。
    """
    v = Vc.astype(np.float32)
    bg = float(np.percentile(v, DIGIT_BG_PCT)) if v.size else 0.0
    thr = DIGIT_DARK_V if dark_v is None else dark_v
    thr = min(thr, bg + DIGIT_REL_DELTA)
    bright = (v >= thr)
    h, w = bright.shape
    pad = np.ones((h + 2, w + 2), np.uint8)      # 外圈全部当"亮",当泛洪的种子
    pad[1:-1, 1:-1] = bright.astype(np.uint8)
    ff = pad.copy()
    mask = np.zeros((h + 4, w + 4), np.uint8)
    cv2.floodFill(ff, mask, (0, 0), 2)
    enclosed = (pad == 1) & (ff != 2)
    return enclosed[1:-1, 1:-1], bright


def analyze_digit(Vc, Sc):
    """
    "这一小块里有没有一个**被暗包住的数字**" —— 判据只写一次,两版检测器共用。

    返回 dict 或 None(这一小块不像"深色方块 + 里面一个数字")。
    Vc/Sc 是同一小块的 HSV 的 V/S 通道。

    ★★ 为什么必须共用:2026-09-11 晚那两个 bug(假橙色 / 补检漏检)都发生在这里。
      **同一个语义只留一份实现**,否则两版检测器迟早会各错一半。
    """
    if Vc.size < 64:
        return None
    enclosed, _bright = enclosed_bright(Vc)
    if not enclosed.any():
        return None
    n_lab, labels, stats, _ = cv2.connectedComponentsWithStats(
        enclosed.astype(np.uint8), 8)
    keep = np.zeros_like(enclosed)
    for i in range(1, n_lab):
        bw, bh, area = (int(stats[i, 2]), int(stats[i, 3]), int(stats[i, 4]))
        if area < DIGIT_BLOB_MIN_PX:
            continue
        if bw > DIGIT_BLOB_W_MAX or not (DIGIT_BLOB_H_MIN <= bh <= DIGIT_BLOB_H_MAX):
            continue
        keep |= (labels == i)
    total = int(keep.sum())
    if total < DIGIT_MIN_PX or total > DIGIT_MAX_PX:
        return None
    if total > DIGIT_AREA_FRAC_MAX * float(Vc.size):
        return None
    h, w = Vc.shape
    ys, xs = np.nonzero(keep)
    cy = (ys.min() + ys.max()) / 2.0 / max(1, h - 1)
    cx = (xs.min() + xs.max()) / 2.0 / max(1, w - 1)
    if max(abs(cy - 0.5), abs(cx - 0.5)) > DIGIT_OFF_MAX:
        return None
    s_mean = float(Sc[keep].mean())
    v_mean = float(Vc[keep].astype(np.float32).mean())
    # ★★★ 2026-09-15 "像橙又太暗" = 木纹一类,**这里没有徽章**(不是"读不准"):
    #   只对**高饱和**的候选生效 —— 整幅画面偏暗时真的灰徽章 V 会低到 104,
    #   那种必须留着(见 ORANGE_V_MIN 的说明)。
    if s_mean >= SAT_ORANGE_MIN and v_mean < ORANGE_V_MIN:
        return None
    if s_mean >= SAT_ORANGE_MIN:
        state = "orange"
    elif s_mean <= SAT_GREY_MAX:
        state = "grey"
    else:
        state = None
    return {"digit_n": total, "digit_s": round(s_mean, 1),
            "digit_v": round(v_mean, 1), "state": state}


def _align(grid, dy, dx, shape):
    """
    把"偏移 (dy,dx) 处的矩形和"搬到**窗口坐标**上:`out[i,j] = grid[i+dy, j+dx]`。

    ★ 符号踩过:一开始写成 `out[i,j] = grid[i-dy, j-dx]`,于是"窗口右边 20px"
      实际取到了"窗口左边 20px"(暗桌面),真徽章反而被上下文检查拒掉。
      写这种偏移时先把**一句话读法**定下来("out[i,j] 等于谁的矩形和"),
      再决定加减,别凭手感。
    """
    H, W = shape
    out = np.zeros(shape, np.float32)
    h, w = grid.shape
    y0, y1 = max(0, -dy), min(H, h - dy)
    x0, x1 = max(0, -dx), min(W, w - dx)
    if y1 > y0 and x1 > x0:
        out[y0:y1, x0:x1] = grid[y0 + dy:y1 + dy, x0 + dx:x1 + dx]
    return out


def find_cost_badges_win(frame, debug=False):
    """
    ★★ 失败的实验,**不要用**(2026-09-11 下午)。留在这里是为了别再走一遍。
    ★ 另外:它里面那个"数字像素"判据是**旧的绝对版** `(V>135)|(S>90)`,
      而那个判据本身已经证明是错的(会把金边卡的深棕底色算成数字 ->
      **灰数字被判成橙色**,见 §7 第 67 条 B)。所以这一版**连颜色都不可信**,
      别再从它身上抄任何东西。

    动机:旧版(连通域 + 尺寸过滤)在徽章和旁边暗部粘连时会漏检,于是想改成
    "滑窗签名" —— 在**每个位置**上问几个问题(窗口够暗吗 / 中间有数字吗 /
    右边是亮卡面吗 / 上下两条边暗吗),完全不看连通域。

    结果:`unit_state_test.py` 的 13 项合成用例**全部通过**,但在真实帧上是灾难 ——
    实测(`badge_ab_test.py`):
        连通域版 4~8 个/帧,滑窗版 **44~68 个/帧**(`shots/board_samples` 5 帧:
        33 -> 290 个)。卡面美术里到处是"暗块 + 亮点 + 旁边有亮面"的组合。
    **连通域"必须是一个孤立的 18x18 深色方块"这条约束,恰恰是最强的先验**,
    去掉它换来的不是鲁棒,而是把整个卡面美术都当成了徽章。

    ★ 教训(比结论值钱):**合成用例全绿不等于能用。** 合成帧里画面是"桌布 + 卡",
      暗块和亮点都只有我画的那几个,判据当然怎么改都过。凡是图像判据,
      最后一步必须是**真实帧上的逐帧计数**,而且要拿"另一个判据"做 A/B,
      不能只看它"能跑出结果"。这一条和 §7 里"数一数最容易骗人"是同一个道理。

    参数/判据的细节留在下面的实现里,想再试的话:先在 `badge_ab_test.py` 里
    把真实帧的假阳性数压到和连通域版同一个量级,再谈替换。
    """
    if frame is None or not hasattr(frame, "shape"):
        return []
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    V = hsv[:, :, 2].astype(np.float32)
    S = hsv[:, :, 1].astype(np.float32)
    H, W = V.shape

    dark = (V < BADGE_DARK_V).astype(np.float32)
    digit = ((V > BADGE_DIGIT_V) | (S > BADGE_DIGIT_S)).astype(np.float32)

    win = BADGE_WIN
    gh, gw = H - win + 1, W - win + 1
    if gh <= 0 or gw <= 0:
        return []
    shape = (gh, gw)
    dark_cnt = _align(_rectsum(dark, win, win), 0, 0, shape)
    inner_dark = _align(_rectsum(dark, BADGE_INNER, BADGE_INNER),
                        BADGE_INNER_OFF, BADGE_INNER_OFF, shape)
    inner_digit = _align(_rectsum(digit, BADGE_INNER, BADGE_INNER),
                         BADGE_INNER_OFF, BADGE_INNER_OFF, shape)
    ctx = _align(_rectsum((V > CONTEXT_BRIGHT_MIN).astype(np.float32),
                          CONTEXT_H, CONTEXT_W),
                 CONTEXT_OY, CONTEXT_DX, shape) / float(CONTEXT_H * CONTEXT_W)
    # ★ 参数顺序是 (dy, dx):右边 3 列 = dy 0 / dx 15。
    #   (我第一版把 15 传给了 dy,于是量的是"左下角"那一块,判据整个反了 ——
    #    真徽章被测成亮、卡的左边缘被测成暗,正好把好人和坏人调了个头。)
    right_dark = _align(_rectsum(dark, win, RIGHT_STRIP_W),
                        0, win - RIGHT_STRIP_W, shape) / float(win * RIGHT_STRIP_W)
    bottom_dark = _align(_rectsum(dark, RIGHT_STRIP_W, win),
                         win - RIGHT_STRIP_W, 0, shape) / float(win * RIGHT_STRIP_W)
    above = _align(_rectsum(V, ABOVE_H, win), -ABOVE_H, 0, shape) / float(ABOVE_H * win)

    win_area = float(win * win)
    inner_area = float(BADGE_INNER * BADGE_INNER)
    ok = ((dark_cnt / win_area >= WIN_DARK_MIN)
          & (inner_dark / inner_area >= INNER_DARK_MIN)
          & (inner_digit >= BADGE_DIGIT_MIN_PX)
          & (ctx >= CONTEXT_BRIGHT_FRAC_MIN)
          & (right_dark >= RIGHT_DARK_MIN)
          & (bottom_dark >= BOTTOM_DARK_MIN)
          & (above >= ABOVE_BRIGHT_MIN))
    # 只在战场范围内找:上方避开状态栏,下方避开手牌(y 上限),左右避开 HUD
    ys = np.arange(gh)[:, None]
    xs = np.arange(gw)[None, :]
    ok &= (ys >= board.FIELD_Y0) & (ys + win <= BOARD_BADGE_MAX_Y)
    ok &= (xs >= board.FIELD_X0) & (xs + win <= board.FIELD_X1)

    cand = np.argwhere(ok)                 # [(y, x), ...]
    # ★ 去重时"谁留下"要用**像不像一个暗方块**来排,不能用"数字像素多"排 ——
    #   实测一个偏出真徽章 7px 的候选反而数字像素更多(它把徽章上方那条亮卡边
    #   也算成了数字),于是把真徽章挤掉,徽章位置反而错 7px。
    #   真徽章的暗占比明显更高(实测 0.76 vs 0.63),所以按暗占比排。
    score = dark_cnt / win_area + 0.5 * (inner_dark / inner_area)
    order = np.argsort(-score[ok]) if len(cand) else []
    out = []
    for i in order:
        y, x = int(cand[i][0]), int(cand[i][1])
        if any(abs(y - b["y"]) <= NMS_DIST and abs(x - b["x"]) <= NMS_DIST
               for b in out):
            continue
        ys0, xs0 = y + BADGE_INNER_OFF, x + BADGE_INNER_OFF
        Vc = V[ys0:ys0 + BADGE_INNER, xs0:xs0 + BADGE_INNER]
        Sc = S[ys0:ys0 + BADGE_INNER, xs0:xs0 + BADGE_INNER]
        m = (Vc > BADGE_DIGIT_V) | (Sc > BADGE_DIGIT_S)
        n = int(m.sum())
        s_mean = float(Sc[m].mean()) if n else 0.0
        v_mean = float(Vc[m].mean()) if n else 0.0
        if s_mean >= SAT_ORANGE_MIN:
            state = "orange"
        elif s_mean <= SAT_GREY_MAX:
            state = "grey"
        else:
            state = None
        out.append({"x": x, "y": y, "w": win, "h": win, "cx": x + win // 2,
                    "cy": y + win // 2, "digit_s": round(s_mean, 1),
                    "digit_v": round(v_mean, 1), "digit_n": n, "state": state})
    out.sort(key=lambda b: (b["y"], b["x"]))
    if debug:
        for b in out:
            print(f"    徽章 x{b['x']:4d} y{b['y']:4d} {b['w']}x{b['h']}  "
                  f"S={b['digit_s']:5.1f} n={b['digit_n']:4d} -> {b['state']}")
    return out


def _badges_cc(frame, debug=False):
    """
    **连通域版**徽章检测:要求"徽章是一个孤立的 18x18 深色小方块"。

    这条约束是整套判据里最强的一条(去掉它就会把整个卡面美术当成徽章 ——
    `find_cost_badges_win` 的教训,§7 第 59 条)。所以它保留为**首选**判据,
    只在它看不见的地方用 `find_cost_badges_band` 补检。
    """
    if frame is None or not hasattr(frame, "shape"):
        return []
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    V, S = hsv[:, :, 2], hsv[:, :, 1]
    dark = (V < BADGE_DARK_V).astype(np.uint8) * 255
    dark[:board.FIELD_Y0, :] = 0
    dark[BOARD_BADGE_MAX_Y:, :] = 0
    dark[:, :board.FIELD_X0] = 0
    dark[:, board.FIELD_X1:] = 0

    n, labels, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = (int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]),
                            int(stats[i, 3]), int(stats[i, 4]))
        if not (BADGE_W_MIN <= w <= BADGE_W_MAX
                and BADGE_H_MIN <= h <= BADGE_H_MAX):
            continue
        if area / float(w * h) < BADGE_FILL_MIN:
            continue
        Vc, Sc = V[y:y + h, x:x + w], S[y:y + h, x:x + w]
        d = analyze_digit(Vc, Sc)
        if d is None:
            continue
        right = V[y:y + h, min(frame.shape[1] - 1, x + w + 3):
                  min(frame.shape[1], x + w + 10)]
        above = V[max(0, y - 7):max(1, y - 2), x:x + w]
        ok_ctx = ((right.size and right.mean() > 110)
                  or (above.size and above.mean() > 110))
        if not ok_ctx:
            continue
        out.append({"x": x, "y": y, "w": w, "h": h, "cx": x + w // 2,
                    "cy": y + h // 2, "from": "cc", **d})
    out.sort(key=lambda b: (b["y"], b["x"]))
    if debug:
        for b in out:
            print(f"    [cc] 徽章 x{b['x']:4d} y{b['y']:4d} {b['w']}x{b['h']}  "
                  f"S={b['digit_s']:5.1f} V={b['digit_v']:5.1f} n={b['digit_n']:3d}"
                  f" -> {b['state']}")
    return out


# ---------------------------------------------------------------------------
# ★★ 补检:沿着"每条战线的卡顶那条 18px 带"扫徽章(2026-09-11 晚新增)
#
# 为什么必须补:连通域法要求"徽章是一个**孤立**的深色方块"。而**金边卡**上
# 徽章的深色方块的左/上两边直接连着卡自己的深色边框、再连到暗桌面 ——
# 整块连通域变成 770x440(实测 `shots/board_samples/0911_122530_001.png`),
# 被尺寸过滤丢掉。那一帧**我方支援线上 3 张带徽章的单位卡一个都没检出**
# (肉眼看得清清楚楚),于是 `attack.ALLOW_BOX_FALLBACK=False` 让攻击一次都发不出去。
#
# 做法:**完全不看连通域**,只在"已知的行带"上问几个问题:
#   ① 这个 18x18 窗口够暗吗            ② 右边紧邻那一段是**亮的卡面**吗
#   ③ 里面有一个**被暗包住的亮块**吗    ④ 那个亮块**靠近窗口正中**吗(不在边上)
#   ⑤ 这一行**本身是真的战线**吗(不是放大悬停卡凭空撑出来的一行)
#
# ★ 为什么不干脆全图滑窗:`find_cost_badges_win` 就是这么做的,真实帧上
#   44~68 个/帧(§7 第 59 条)。**"限制在行带上"是这次和那次唯一的区别,
#   也是它能成立的关键** —— 行带的 y 来自 `card_boxes` 的行结构,不是猜的。
BAND_H = 18                    # 窗口高(徽章实测 17~19px)
BAND_DARK_FRAC = 0.60          # ① 窗口里暗像素占比下限
BAND_RIGHT_DX = 20             # ② 右边那一段的起点(相对窗口左边缘)
BAND_RIGHT_W = 12
BAND_RIGHT_FRAC = 0.70         # ② 那一段里"亮卡面"像素占比下限
BAND_Y_OFFS = (0, 2, 4, 6, 8, 10, 12, 14)
# ★ 徽章顶边相对"行里最高那张卡的顶边"实测偏移 0~8px(行里可能有更高的总部卡),
#   所以把可能的位置都试一遍,再用 NMS 合并 —— 这一步很便宜(积分图),不用省。
BAND_NMS = 20                  # 两个候选中心离得比这近 = 同一个徽章
BAND_BRIGHT_V = 115            # "亮卡面"的亮度下限
BAND_ROW_H_MAX = 168           # ★ 行里出现这么高的"卡" -> 那是**放大悬停卡**,不是战线

# ---------------------------------------------------------------------------
# ★★★ `BAND_DIGIT_MIN_PX` —— 补检这条路上"数字块面积"的下限(2026-09-12 第六个会话新增)
#
# 为什么需要它(实机 + 语料 A/B,证据在 PROJECT_STATE §7 第 77 条):
#   这一轮把"亮卡面"判据放宽成"上/右/下任一方向"之后,补检开始在一些**根本不是徽章**
#   的东西上出假阳性,而且两个方向都吃到了:
#     · `0912_153308` `x857 y453`(蓝图桌上的圆圈)—— 引擎把支援线 **4 个单位读成 5**;
#     · `0912_154321` `x706 y462`(**木桌木纹,而且是橙色**)—— 引擎把它当成"能行动的
#       我方单位"(被类型检查兜住,没真的拖出去);
#     · `0912_154730` `x571 y107`(敌方格总部卡旁边那个"深色小方块 + 亮色齿轮图标"的
#       **卡上图标牌**,橙色)—— §7 第 67 条预言过的"暗底假橙色",实机第一例。
#
# 量出来的分界(语料 = `shots/attack_frames` + `shots/board_samples`,300 个徽章):
#     · `cc`(连通域,主判据)244 个:digit_n **最小 35**(p5 41、中位 47);
#     · `band`(补检)56 个:最小 21、p5 25 —— **小的那些全在补检这条路上**;
#     · 把 `band` 上 `digit_n <= 29` 的 7 个**逐个放大看过**:7/7 全是假阳性,没有一个真徽章。
#   → `<=29` 与 `>=35` 之间是一条空档,阈值取 **32** 落在空档正中。
#
# ★ 为什么只加在补检这条路(而不是改 `analyze_digit` 里的 `DIGIT_MIN_PX`):
#   主判据(连通域)那 244 个样本最低是 35,它本来就不产生这种小亮块;
#   而 `analyze_digit` 是**两版共用**的,动它等于同时改两条路的召回 —— 没有证据支持那么做。
#
# ★★ 两个方向的代价不对称,而且偏向安全的那一边:
#   真徽章被误杀 -> 少认一个徽章 = 少打一次 / 支援线少数一个(**fail-closed,安全**);
#   假阳性留下来 -> **白拖一次**,正是本项目头号要消除的"乱拖"。
#   ★ 真出问题时的表现很好认:日志里我方那一行的徽章数**总是比人眼少 1~2 个** ——
#     那就说明这个下限定高了,回头做 A/B 再调(工具:`badge_band_probe.py --tiles`)。
# ---------------------------------------------------------------------------
BAND_DIGIT_MIN_PX = 32

#   ★ 为什么要有这条:鼠标悬停手牌时,屏幕中部会出现一张**放大的卡**(约 250x450)。
#     它也是一块亮的规整矩形,于是 `card_boxes` 会把它当成"卡",`rows_from_boxes`
#     就凭空多出一整行 —— 而补检会照着这一行扫,把放大卡左上角那个**大号费用数字**
#     当成徽章(实测 `shots/deploy_probe/f003.png` 扫出 `x669 y329 orange`)。
#     这不是"判据不够严",而是**输入的行本身是假的**;所以要在行这一层拦掉。
#     实测:战线上的卡高 142~152px,而放大悬停卡高 **179px**;取 168 两者都容得下。
#     代价:万一某个行因为粘连被撑到 168 以上,那一行**不补检**(方向是"少检",安全)。


def _row_rect_sums(DI, y, h, w, x0, x1):
    """积分图 DI 上,固定 y 的一行里所有 (h,w) 矩形和(对 x 向量化)。"""
    return (DI[y + h, x0 + w:x1 + w] - DI[y, x0 + w:x1 + w]
            - DI[y + h, x0:x1] + DI[y, x0:x1])


def find_cost_badges_band(frame, rows, debug=False, context_any=None,
                          digit_min=None):
    """
    在**已知的行带**上补检费用徽章(见上面那段说明)。rows 来自
    `board.rows_from_boxes(board.card_boxes(frame))`;没有行信息就返回 []。

    context_any: 覆盖模块级 `BAND_CONTEXT_ANY`(A/B 用)。None = 用模块值。
    digit_min:   覆盖模块级 `BAND_DIGIT_MIN_PX`(A/B 用)。None = 用模块值;
                 **传 0 就是旧行为**(不做这道下限),`unit_state_test` CASE 8 靠它做 A/B。
    """
    if context_any is None:
        context_any = BAND_CONTEXT_ANY
    if digit_min is None:
        digit_min = BAND_DIGIT_MIN_PX
    if frame is None or not hasattr(frame, "shape") or not rows:
        return []
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    V = hsv[:, :, 2].astype(np.float32)
    S = hsv[:, :, 1]
    H, W = V.shape
    dark = (V < BADGE_DARK_V).astype(np.float32)
    bright = (V > BAND_BRIGHT_V).astype(np.float32)
    DI_d = cv2.integral(dark)
    DI_b = cv2.integral(bright)

    # ② 的"右侧那一段"从 x+BAND_RIGHT_DX 起算,所以扫描右边界要给它留出位置。
    # ★ 早先把这一步写成"越界时再把 rx_hi 夹回来",结果两个数组长度会差
    #   BAND_RIGHT_DX(一个按 x 索引、一个按 x+DX 索引)—— 现在改成**先把扫描
    #   右界收进来**,后面两个数组天然同长、逐项对齐,不存在夹回来的分支。
    x_lo = max(board.FIELD_X0, 0)
    x_hi = min(board.FIELD_X1 - BAND_H,
               W - BAND_H - BAND_RIGHT_DX - BAND_RIGHT_W)
    if x_hi <= x_lo:
        return []
    win_area = float(BAND_H * BAND_H)

    cands = []                      # [(score, y, x)]
    for r in rows:
        # ★ 行本身是不是"真战线"(见 BAND_ROW_H_MAX):放大悬停卡会凭空多出一行
        if any(int(b["h"]) > BAND_ROW_H_MAX for b in r.get("boxes", [])):
            if debug:
                print(f"    [band] 跳过行 cy≈{r.get('cy')}:"
                      f"里面有 {BAND_ROW_H_MAX}px 以上的'卡' -> 是放大悬停卡")
            continue
        y_base = int(r["y0"])
        for off in BAND_Y_OFFS:
            y = y_base + off
            if y < board.FIELD_Y0 or y + BAND_H > BOARD_BADGE_MAX_Y:
                continue
            cnt = _row_rect_sums(DI_d, y, BAND_H, BAND_H, x_lo, x_hi)
            ok = cnt / win_area >= BAND_DARK_FRAC
            if not ok.any():
                continue
            # ② 窗口**周围**必须有亮卡面(徽章挂在卡的左上角)。
            #   ★ 2026-09-12:默认看"上/右/下任一方向"(见 BAND_CONTEXT_ANY 的说明);
            #     旧行为只看右边。上面/下面那两条各取 4 行,宽度同窗口。
            rcnt = _row_rect_sums(DI_b, y + 2, BAND_H - 4, BAND_RIGHT_W,
                                  x_lo + BAND_RIGHT_DX, x_hi + BAND_RIGHT_DX)
            bright_ok = (rcnt / float((BAND_H - 4) * BAND_RIGHT_W)
                         >= BAND_RIGHT_FRAC)
            if context_any:
                if y - CTX_UP_H >= 0:
                    ucnt = _row_rect_sums(DI_b, y - CTX_UP_H, CTX_UP_H, BAND_H,
                                          x_lo, x_hi)
                    bright_ok = bright_ok | (ucnt / float(CTX_UP_H * BAND_H)
                                             >= BAND_RIGHT_FRAC)
                if y + BAND_H + CTX_DOWN_H <= BOARD_BADGE_MAX_Y:
                    dcnt = _row_rect_sums(DI_b, y + BAND_H, CTX_DOWN_H, BAND_H,
                                          x_lo, x_hi)
                    bright_ok = bright_ok | (dcnt / float(CTX_DOWN_H * BAND_H)
                                             >= BAND_RIGHT_FRAC)
            ok = ok & bright_ok
            for xi in np.nonzero(ok)[0]:
                x = x_lo + int(xi)
                score = float(cnt[xi]) / win_area
                cands.append((score, y, x))

    # 按"暗得像不像一个方块"排序,逐个做精确判据 + NMS
    cands.sort(key=lambda c: -c[0])
    out = []
    for _score, y, x in cands:
        if any(abs(y - b["y"]) <= BAND_NMS and abs(x - b["x"]) <= BAND_NMS
               for b in out):
            continue
        # ★ 同一行内**横向去重**(见 BAND_MIN_PITCH_PX 的说明):
        #   放宽"亮卡面"之后,滑窗会沿卡顶横滑,同一张卡出好几个候选。
        if any(abs(y - b["y"]) <= BAND_H
               and abs(x - b["x"]) < BAND_MIN_PITCH_PX for b in out):
            continue
        Vc = V[y:y + BAND_H, x:x + BAND_H]
        Sc = S[y:y + BAND_H, x:x + BAND_H]
        d = analyze_digit(Vc, Sc)
        if d is None:
            continue
        # ★ 2026-09-12(第六个会话):补检这条路上再加一道"数字块面积"下限 ——
        #   上面 `BAND_DIGIT_MIN_PX` 那一整段说明了为什么(木纹 / 蓝图圆圈 / 卡上图标牌)。
        if digit_min > 0 and d["digit_n"] < digit_min:
            if debug:
                print(f"    [band] 丢掉 x{x} y{y}: digit_n={d['digit_n']} "
                      f"< BAND_DIGIT_MIN_PX={digit_min}(像图标牌/木纹,不是数字)")
            continue
        out.append({"x": x, "y": y, "w": BAND_H, "h": BAND_H,
                    "cx": x + BAND_H // 2, "cy": y + BAND_H // 2,
                    "from": "band", **d})
    out.sort(key=lambda b: (b["y"], b["x"]))
    if debug:
        for b in out:
            print(f"    [band] 徽章 x{b['x']:4d} y{b['y']:4d} 18x18  "
                  f"S={b['digit_s']:5.1f} V={b['digit_v']:5.1f} n={b['digit_n']:3d}"
                  f" -> {b['state']}")
    return out


def _dedup_badges(badges, dist=None):
    """按中心距离去重:连通域版优先(它的方块边界是**量出来的**)。"""
    dist = NMS_DIST if dist is None else dist
    order = {"cc": 0, "band": 1}
    out = []
    for b in sorted(badges, key=lambda b: order.get(b.get("from"), 9)):
        if any(abs(b["cx"] - o["cx"]) <= dist and abs(b["cy"] - o["cy"]) <= dist
               for o in out):
            continue
        out.append(b)
    out.sort(key=lambda b: (b["y"], b["x"]))
    return out


def badge_on_card_body(badge, boxes, debug=False):
    """
    这个徽章是不是落在某张**已检出卡片的下半部分**(= 卡面自己的数字/图标)?

    判据只有一句话:费用徽章长在卡**左上角**;落在卡的下半部分的深色方块 +
    亮数字,是卡底部那一排 `攻击力 [类型图标] 防御力`。

    为什么用**徽章方块自己的中心**判、而不是它反推出的卡框中心:假徽章反推出的
    卡框会**错开半张卡**(实测 (771,217)+22x22 -> 卡框 (768,213)),把它往真实
    卡框里套是套不进去的;而方块中心 (782,228) 稳稳落在敌方那张卡的 (728..860,
    101..247) 里、相对高度 87% —— 一句话就说清了它是什么。

    ★ 只拿**接近单张卡高**的框当"容器"(STAT_GUARD_H_MAX):两卡粘连成的高框、
      放大悬停卡的大框都会让真徽章落到"下半部分",不能据此丢。
    """
    cx, cy = badge.get("cx"), badge.get("cy")
    for bx in boxes or []:
        if not (isinstance(bx, dict) and {"x", "y", "w", "h"} <= set(bx)):
            continue
        if int(bx["h"]) > STAT_GUARD_H_MAX:
            continue
        if not (bx["x"] <= cx <= bx["x"] + bx["w"]
                and bx["y"] <= cy <= bx["y"] + bx["h"]):
            continue
        rel = (cy - bx["y"]) / float(max(1, bx["h"]))
        if rel >= STAT_REL_Y:
            if debug:
                print(f"    [守卫] 徽章 x{badge.get('x')} y{badge.get('y')} 落在卡框 "
                      f"x{bx['x']} y{bx['y']} {bx['w']}x{bx['h']} 的 "
                      f"{rel * 100:.0f}% 高处 -> 是**卡面数字/图标**,不是费用徽章")
            return True
    return False


def _drop_on_card_body(badges, rows, debug=False):
    """
    位置守卫(第一道):拿**调用方给的那套行/卡框**筛一遍(见 `badge_on_card_body`)。

    ★★ 2026-09-15 试过、并且**被 A/B 否掉**的第二条判据(留在这里当教训):
       原来还想加"徽章必须贴着**行带上沿**"(费用徽章在卡左上角,而卡的上边缘
       就是行带上沿;实测真徽章 d=cy−y0=4~14px,卡底部的类型图标 d=124px)。
       这一条不需要卡框,看起来正好补上"卡框锚点漏检"的洞 ——
       但 200 帧 A/B 立刻抓到反例 `shots/deploy_drag/0913_211151_kredits_mismatch.png`:
       那一帧有放大悬停卡 + 相邻卡粘连,`card_boxes` 出来的框又高又乱,
       行带 y0 本身就错了(197/352),于是**两个真徽章**(x589y281 橙 S=156 V=200、
       x823y453 灰 S=79 V=148)被误杀。
       ⇒ 结论:**行带这个东西本身就不可靠,不能拿它当守卫的依据**。
         正确的做法是在**并集**(卡框锚点 ∪ 徽章锚点)上跑上面那一条 ——
         见 `board.merged_card_boxes` 里的调用:那里两张锚点互相补,
         敌方那张"卡框没检出来"的卡,由它自己**真的费用徽章**提供了卡框。
    """
    rows = [r for r in (rows or []) if r.get("boxes")]
    if not rows:
        return badges
    boxes = []
    for r in rows:
        boxes += [b for b in (r.get("boxes") or []) if isinstance(b, dict)]
    if not boxes:
        return badges
    return [b for b in badges
            if not badge_on_card_body(b, boxes, debug=debug)]


def find_cost_badges(frame, rows=None, debug=False, stat_guard=None):
    """
    找出场上所有的**费用徽章**(深色小方块 + 里面一个亮色数字)。

    返回 [{'x','y','w','h','cx','cy','digit_s','digit_v','digit_n','state','from'}]。
    state: 'orange'(能行动) / 'grey'(不能行动) / None(读不准)。
    from:  'cc'(连通域找到的) / 'band'(行带补检找到的)。

    ★ 只找**板面上**的徽章(手牌区排除,见 BOARD_BADGE_MAX_Y):
      手牌卡也显示费用,而且那儿的颜色是另一套规则,混进来会污染判据。

    两段式:
      1. `_badges_cc` —— 连通域 + 尺寸过滤。**首选**,假阳性最低
         (实测 `badge_ab_test.py` + `shots/board_samples` 4~8 个/帧,和画面对得上)。
      2. `find_cost_badges_band` —— 行带补检。**只在第 1 步看不见的地方出手**
         (金边卡的徽章和桌面粘成一片时,连通域整个被尺寸过滤丢掉)。

    ★★ 2026-09-11 晚同时修了两个真 bug,两个都会让"能不能行动"判错:
      ① **补检**:见 `find_cost_badges_band` 的说明。实测一帧里我方支援线
         3 张带徽章的单位卡**一个都检不出** -> 攻击被自己拒掉。
      ② **假橙色**:数字像素的判据原来是**绝对**的 `(V>135)|(S>90)`,会把
         **徽章自己的深棕底色**算成数字,平均饱和度被拉到 135+ -> 一个
         **已行动的灰数字**被判成"能行动"。实测抓到
         `18x18 S=135.3 V=53.3 n=316 -> orange`(n=316/324 = 整块都是)。
         现在改成**相对底色**(`analyze_digit`),并且要求数字**被关在窗口中间**。

    ★★★ 2026-09-15(实机 J9):再加一道**位置守卫**(`STAT_GUARD` / `stat_guard`)。
      stat_guard=None 就用模块值(默认开);传 False 是旧行为,**留着做 A/B**。

    rows: 可选,直接传 `board.rows_from_boxes(...)` 的结果(热路径上避免重复算);
          不传就自己算一份。位置守卫也要用它,所以不传就得在这里算。
    """
    if frame is None or not hasattr(frame, "shape"):
        return []
    out = _badges_cc(frame, debug=debug)
    if rows is None:
        try:
            rows = board.rows_from_boxes(board.card_boxes(frame))
        except Exception:
            rows = []
    out += find_cost_badges_band(frame, rows, debug=debug)
    out = _dedup_badges(out)
    if stat_guard is None:
        stat_guard = STAT_GUARD
    if stat_guard:
        out = _drop_on_card_body(out, rows, debug=debug)
    return out


def unit_box_from_badge(badge):
    """从徽章推出它所属那张卡的框(估算,用于认类型/取拖动落点)。"""
    x, y = badge["x"] - 3, badge["y"] - 4
    return {"x": x, "y": y, "w": CARD_W_EST, "h": CARD_H_EST,
            "cx": x + CARD_W_EST // 2, "cy": y + CARD_H_EST // 2}


def drag_from_point(badge):
    """从徽章推出"拖动这张卡时应该按下的客户区坐标"。"""
    return (badge["x"] + DRAG_FROM_DX, badge["y"] + DRAG_FROM_DY)


def actionable_units(frame, templates=None, debug=False):
    """
    我方**这回合还能行动**的单位(橙色徽章),返回 [{badge, box, src, type}]。

    src = 拖动时按下/起手的客户区坐标。
    type = 卡面类型图标认出来的类型(认不出就是 None;调用方据此决定要不要攻击)。

    ★ 为什么用徽章而不是卡框来找"我方单位":
      卡框在相邻卡粘连/被手牌挡住时会合并或漏掉(实测漏过整张卡),
      而徽章是独立小方块,不受影响。而且"能行动"本来就是我们要的信息。
    """
    badges = find_cost_badges(frame, debug=debug)
    out = []
    for b in badges:
        if b["state"] != "orange":
            continue
        box = unit_box_from_badge(b)
        u = {"badge": b, "box": box, "src": drag_from_point(b), "type": None}
        if templates:
            u["type"] = board.classify_unit_type(frame, box, templates)
        out.append(u)
    if debug:
        for u in out:
            print(f"    可行动单位 x{u['badge']['x']} y{u['badge']['y']} "
                  f"类型={u['type']} 起手点={u['src']}")
    return out


# ---------------------------------------------------------------------------
# 兼容层:老接口(卡框 + 固定偏移)已经不可靠,这里改成"找最近的徽章"。
# turn_sampler.py 还在用 _search_crop,所以保留它。
# ---------------------------------------------------------------------------
SEARCH_X = (-0.06, 0.42)
SEARCH_Y = (-0.22, 0.16)


def _search_crop(frame, unit, xr=SEARCH_X, yr=SEARCH_Y):
    """兼容 turn_sampler:在卡框的左上角一带裁一小块(仅供采样调试用)。"""
    x, y, w, h = unit["x"], unit["y"], unit["w"], unit["h"]
    x0 = max(0, int(x + xr[0] * w))
    x1 = min(frame.shape[1], int(x + xr[1] * w))
    y0 = max(0, int(y + yr[0] * h))
    y1 = min(frame.shape[0], int(y + yr[1] * h))
    if x1 <= x0 or y1 <= y0:
        return None
    return frame[y0:y1, x0:x1]


def nearest_badge(badges, unit, max_dist=70):
    """找离某张卡的左上角最近的徽章。"""
    if not badges:
        return None
    best, bestd = None, None
    for b in badges:
        d = abs(b["x"] - unit["x"]) + abs(b["y"] - unit["y"])
        if bestd is None or d < bestd:
            best, bestd = b, d
    if best is None or (max_dist is not None and bestd > max_dist):
        return None
    return best


def read_cost_color(frame, unit):
    """
    兼容老接口:返回 (state, detail)。
    state ∈ {'orange','grey',None};判据现在是**徽章里数字的饱和度**。
    """
    b = nearest_badge(find_cost_badges(frame), unit)
    if b is None:
        return None, {"reason": "这个卡框附近没有找到费用徽章"}
    return b["state"], b


def can_attack(frame, unit, actionable_when="orange"):
    """
    这个单位这回合能不能行动。
    ★ 读不准一律返回 False(宁可少打一次,也不要乱拖)。
    """
    state, _detail = read_cost_color(frame, unit)
    if state is None:
        return False
    return state == actionable_when


def can_move_to_front(frame, unit):
    """能不能"上前线" —— 和能不能攻击用的是同一个判据。"""
    return can_attack(frame, unit)


if __name__ == "__main__":
    """自检:用存档的真实帧量一遍,看橙/灰是不是两个峰。"""
    import glob

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = (sorted(glob.glob(os.path.join(ROOT, "shots", "board_samples",
                                           "0911*.png")))
             + sorted(glob.glob(os.path.join(ROOT, "shots", "deploy_probe",
                                             "f0*.png"))))
    files = [f for f in files if "_mask" not in f and "_annot" not in f]
    print(f"扫 {len(files)} 帧,统计费用徽章的饱和度分布")
    allb = []
    for fp in files[:20]:
        img = cv2.imread(fp)
        if img is None:
            continue
        for b in find_cost_badges(img):
            allb.append((os.path.basename(fp), b["state"], b["digit_s"]))
    if not allb:
        print("没找到任何徽章")
        raise SystemExit(1)
    ss = sorted(s for _f, _st, s in allb)
    print(f"共 {len(allb)} 个徽章")
    hist, edges = np.histogram(ss, bins=10, range=(0, 200))
    for i, c in enumerate(hist):
        print(f"  S {int(edges[i]):3d}-{int(edges[i+1]):3d}: {c:4d} " + "#" * c)
    for st in ("orange", "grey"):
        v = [s for _f, s2, s in allb if s2 == st]
        if v:
            print(f"  {st}: {len(v)} 个, S {min(v):.1f}~{max(v):.1f}")
    unk = [s for _f, s2, s in allb if s2 is None]
    if unk:
        print(f"  读不准: {len(unk)} 个, S {sorted(round(x) for x in unk)}")
