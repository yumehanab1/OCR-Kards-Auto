"""
mobile_hand.py —— 手机端手牌:**这一回合哪几张牌现在能打**(判据 = 费用数字的颜色)。

██████████████████████████████████████████████████████████████████████████████
★★★ 判据(2026-09-17 在真设备帧上量出来的,不是猜的):

    **手牌左上角费用数字:橙色提示当前可用候选,灰色提示当前不可用。**

  手牌和场上单位复用数字颜色分析,但不能把颜色直接解释成唯一原因:
  手牌灰色可能与费用、合法目标或其他限制有关;场上灰色表示当前不可行动,
  不能仅凭灰色判断本回合已行动,亦可能受压制等状态/限制影响。

  实测(`shots/android/hand/live_k3_6cards.png`,我方费用 **3**,手上 6 张
  费用 2/3/3/2/**6**/1):五张下得起的数字 **S=203~208 V=143~153**,
  那张下不起的(费用 6)**S=60 V=114** —— **S 差了 3 倍多**,分得干干净净。
  存帧对照图 `shots/_probe/playable_cmp.png`(四个放大徽章并排,肉眼看:三个橙、一个灰)。

★★★ 为什么**不**去认牌名(用户的原话:7 张以上牌名会被盖住)——
   **2026-09-19 实机把这条量死了,别再来一遍**:
   | 手牌张数 | 牌距 | 名条可见宽度 | ≈ 几个汉字 |
   |---|---|---|---|
   | 6 | 119px | 94px | 6.3 |
   | 7 |  98px | 73px | 4.9 |
   | 8 |  80px | 56px | 3.7 |
   | **9** | **61px** | **34px** | **2.3** |
   而且**只有最右边那一张**名字是完整的(没人压它)。
   真机 9 张那局现抓的一帧(`shots/android/hand/live_hand_now.png`)上,
   每张只露"三号""Fw 19""虎式""步兵""Ju 87""第 4"这种两三个字 ——
   而"三号坦克 L 型"和"三号突击炮 F 型"前两个字一样 ⇒ **认不出是哪张**。
   ⇒ 名条 OCR 认卡名这条路**不成立**(我试过:转正 + 放大 4 倍送 rapidocr,
     22 个候选只查出 3 个卡名,而且都是残句)。
   ★ 但**名条存在与否**仍然有用(指令没有名条)—— 见 `card_kind` 的辅助信号。
   对照图:`shots/android/probe/_hand_percard.png`(9 张牌一张一格)。

★★★ 为什么不是"把电脑端那张表抄一份"(这一条决定了整个做法):
  电脑端 `hand_scanner_v2` 的整条链是**悬停驱动**的:把鼠标挪到安全点让扇形收起、
  再悬停到手上让扇形展开,然后在展开态按列采样。
  **触摸屏上没有悬停** —— `AndroidPlatform.mouse_move` 在没按下时**故意什么都不做**。
  而手机端**本来就更简单**:手牌**一直是摊开的**,每张牌左边那条(费用徽章)直接看得见。
  ⇒ 所以这里做的是**从一帧静态画面里直接找"橙色的费用数字"**。
██████████████████████████████████████████████████████████████████████████████

██████████████████████████████████████████████████████████████████████████████
★★★ **判据待定的一处(2026-09-17,没查清,别当成已解决)**:

  上面那条判据在 `live_k3_6cards.png`(我方费用 3、手上费用 2/3/3/2/6/1)上**完全成立**:
  五张下得起的数字 S=203~208,那张**下不起的(费用 6)S=60** —— 灰得干干净净。
  `hand_n6.png`(用户的截图,同一副手牌)上同样:**费用 6 那张是灰的**,别的橙。

  **但 `shots/android/ingame/f0..f5.png` 这 6 张上对不上**(我逐张放大看过):
    费用徽章显示 **1**(f0/f1/f2)或 **2**(f3/f4/f5),
    手牌是 1(灰)/4(橙)/2(橙)/2(橙)(f4/f5 还多一张 3,橙)。
    费用 1 而 kredits 也是 1 —— 按"下得起才橙"它该是橙的,**它是灰的**;
    费用 4 而 kredits 只有 1 —— 按判据它该是灰的,**它是橙的**。**方向正好反过来。**
  能想到、但**都没验证**的解释:f0..f5 可能是**训练模式**(那个模式里费用规则未必一样)、
  或者别的版本/别的窗口比例。**在查清之前不下结论。**

  ⇒ **所以 `find_hand()` 的返回只能当「候选」,不能当「结论」。**
    引擎拖完一张牌**必须验证**(手牌变了没有),这正是本项目一贯那条纪律:
    "报告成功、其实什么都没干"是头号敌人。见 `PROJECT_STATE.md` 里这一轮的记录。
██████████████████████████████████████████████████████████████████████████████

★ 这一版**复用 `unit_state.analyze_digit`**,不另写一套判据。
  为什么:那个函数里攒着本项目最贵的几条教训 ——
    · 判"橙"必须看**数字像素的饱和度 S**,不能只看亮度(暗橙色数字 V 只有 141);
    · `S>=120` 但 `V<140` 的是**木纹一类的假橙色**,要**整块丢掉**(不是"读不准");
    · 数字必须**被暗底包住、而且靠近窗口正中**(否则牌面美术/名字白字全会进来)。
  两条路(场上 / 手牌)共用数字像素的颜色分析实现。
  颜色只提供当前可用性候选,行动历史和受限原因需要各自的局面证据。

██████████████████████████████████████████████████████████████████████████████
★ 这个文件里所有阈值都配着 `debug_overlay()`:
  写检测的人(我)已经**连着两轮**把检测锁到过错的特征上(玩家名/玩家 ID/`DANZIG` 那行字)。
  ⇒ 规矩:**任何检测都必须能一键画出"它看到了什么"**,人看一眼才算数。

★ 还没做、也**没假装做了**的:
  · **牌的数量/牌名** —— 本文件只找"能打的"。要找全部手牌(含灰色的),
    锚点得换一个(灰数字 = 暗底上的亮低饱和块,和名字白字**同色**,现在分不开),
    所以**没做**,也没拿它当结论。
  · **打出去(拖到战场)** —— 那是 deploy 那一步,见 `deploy.py`;手牌这一层只给"按哪儿"。
██████████████████████████████████████████████████████████████████████████████
"""

from __future__ import annotations

import json
import os
import random
import sys

import cv2
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import unit_state as us          # noqa: E402  —— 共用 analyze_digit(见文件头)

PROJECT_ROOT = os.path.dirname(_HERE)

#: 客户区尺寸(引擎的基准空间)。`grab_point` 靠它把落点夹在画面内。
CLIENT_W, CLIENT_H = 1280, 720

# ---------------------------------------------------------------------------
# 几何(客户区 1280x720)
# ---------------------------------------------------------------------------

#: 手牌那条带子(**量出来的**)。来自 `config/board_android.json`。
DEFAULT_BAND = (200, 610, 1100, 720)

#: 搜索区:比上面那条带子**往上放宽**。
#: ★ 为什么:徽章挂在牌的**左上角**,而牌的上边缘不一定正好落在 610
#:   (实测 live 帧上第一张徽章在 y=675、中间那张在 y=615;牌一多扇形会把中间的牌顶高)。
#: ★ 上界 560 是**卡死的**:电脑端/手机端"我方场上单位"的费用徽章都在 y<540
#:   (`unit_state.BOARD_BADGE_MAX_Y = 520`),再往上就要和自己的单位抢了。
#:   放宽到 560 既兜住手牌,又不会把场上单位的橙色徽章当成手牌。
DEFAULT_ZONE = (200, 560, 1100, 720)

#: 数字窗口边长。★ 手机端手牌的费用徽章比电脑端**大一圈**:
#:   电脑端 `unit_state.BADGE_WIN = 18`(徽章方块实测 17~19px);
#:   手机端实测徽章方块 **24x24**、里面数字 **17x18**。
#:   ⇒ 用 18 的窗口套手机徽章,数字会**顶到窗口边缘**,"被暗底包住 + 居中"两条同时失效
#:     → 真徽章一个都过不了(2026-09-17 就是这么白跑了一轮)。
#:   24/26/28 三个值都试过,结果一样;取 26 留一点余量。
DIGIT_WIN = 26

#: 窗口里"暗底"的占比下限(徽章是一块**深色方块**)。
DIGIT_DARK_MIN = 0.55

#: 窗口里"数字像素"的个数下限。
#: ★ 实测:能下的那几张 **n=104~144**;下面这一版把 60 留着 —— 因为**细数字**
#:   (比如 "1")本身就窄,实测那一张 `1` 只有 **n=82**,卡在 90 上就被丢掉了。
#: ★ 代价不对称(和 `unit_state.BAND_DIGIT_MIN_PX` 那段同一个道理):
#:   丢掉一个真徽章 = 少打一张牌(fail-closed,安全);放进一个假的 = **白拖一次**。
DIGIT_N_MIN = 60

#: 两个候选挨得比这近就算同一张牌(NMS)。
NMS_DIST = 22

#: 锚点用的橙像素色域。★ 比 `analyze_digit` 的判定线**松一点**:
#:   锚点只负责"去哪儿看",判定(`analyze_digit`)才决定是不是真徽章。
#:   锚紧了会把细数字整条漏掉;锚松了只是多跑几次 analyze_digit(实测 <100ms)。
ANCHOR_S_MIN = 140
ANCHOR_V_MIN = 130
ANCHOR_HUE = (6, 28)      # OpenCV 色相(180 制);实测橙色数字在 H=16

#: 锚点连通域的形状门槛(滤掉牌面美术里的大色块)。
ANCHOR_W = (5, 32)
ANCHOR_H = (7, 28)
ANCHOR_MIN_AREA = 25

# ---------------------------------------------------------------------------
# ★★★ 单位 / 指令 的判别(2026-09-17 用户提醒后加的,这一块**必须**先有)
#
# 用户原话:
#   "当前卡组里有**指向性指令**(拖到特定敌方/友方卡/总部才能打出去),有**瞬时生效的指令**,
#    有**反制**(根本打不出去),他们**费用数字都是橙色的** —— 如果你现在开跑绝对会卡在上边,
#    建议先做指令判断。"
# ⇒ "橙色 = 能下"这条判据**不够**:它对指令同样成立。必须先分出"这张是不是单位"。
#
# **判据(用户先说的,我在帧上量到了)**:
#   **单位卡的名条(名字那条深色横带)在费用徽章右边一直铺开;指令卡那儿直接就是牌面美术。**
#   用户原话:"只有单位卡的名字会在上边显示,指令不会显示。"
#   放大存帧:`shots/android/hand/` 里那几张证据图(c1/c2/c3/c5 有绿/棕名条,c4/c6 没有)。
#
# **量什么**:徽章右边那一条(高 = 徽章高,宽 18px)里,
#   **逐行**算"暗像素(V<125)占比",再取**中位数** -> `bar_dark`。
#   名条是"整行都暗"(深绿/深棕底),美术不是。名字白字只会毁掉个别行,所以取中位数。
#
# **实测(生产几何:x+徽章宽+3 起、宽 18px;y+2..y+h-2;V<125;逐行占比取中位)**:
#     单位 10 张 -> 0.89 0.89 0.89 0.89 0.89 0.86 0.86 0.83 0.78 0.75
#     指令  6 张 -> 0.06 0.06 0.00 **0.61 0.61 0.64**
#   ★ 分不开的是**最右那张指令卡**:它的美术本来就是深灰蓝(降落伞/伞兵),
#     所以"右边那一条暗"这条判据在它身上也成立。**这不是阈值能修的。**
#
# ⇒ 所以做成**三段**,中间留一条**死区**,"拿不准"就**不碰**:
#     bar_dark >= 0.74  -> unit
#     bar_dark <  0.68  -> order
#     中间              -> unknown(**不碰**)
#   代价与收益是**不对称的**,方向偏安全那一侧:
#     把单位判成 unknown -> 少打一张牌(退化成现在"一直过牌"的行为,**安全**);
#     把指令判成 unit   -> **拖出去卡住**(用户明确警告过的那种),**必须避免**。
#   实测这条规则:**假"单位" 0 张**;余量 = 最"像单位"的指令(0.64) 到阈值 0.74 差 **0.10**。
# ★★ **一个已知的漏检**(如实记):苏联那两张**棕红名条**的单位实测只有 **0.64**,
#   会被判成 order -> **不打**。方向是安全的(少打一张),但要知道有这回事。
#   德国橄榄绿名条的卡实测 0.78~0.89,不受影响。
# ★ 这套阈值是**一次会话、十来张卡**标出来的,**样本很薄**。真跑起来要拿日志回来看:
#   `mobile_hand.py --live` 会把每张卡的 `bar_dark` 和类别都打出来;
#   日志里老是 "unknown" 说明阈值该往下调 —— **但要先看帧,别凭感觉**。
#   真正的解法是**多标几帧**(让引擎跑的时候顺手把每帧存下来)。
# ---------------------------------------------------------------------------
# ★★ **一次真漏判(2026-09-18,用户当场看出来的,必须记着)**:
#   引擎在实机上**把一条指令当单位拖了出去** —— 那条指令的效果是"从三张单位里选一个",
#   于是画面停在一个选择框上、`classify` 认不出、**引擎卡住了**。
#   ⇒ **"指令不显示名字"这句话不是对所有指令都成立** —— 至少有一条指令**是有名条的**,
#     所以 `bar_dark` 这一条判据**会漏**。代价正是用户早就警告过的那个(拖出去卡住)。
#   ⇒ 补的两道防线(都在 `deploy_one_unit` / `turn_engine_mobile` 里):
#       ① **打完必须画面还是 `in_game`** —— 弹出选择框就当场判定"这不是普通部署";
#       ② 出牌上限 / 一次只做一个决定,免得一口气拖一串。
#   ⇒ **当时以为还欠的**是"真正的单位 vs 指令判据",并且只在**事后**发现打错了。
#   ★★ 2026-09-19 **这个洞补上了**:主判据换成**徽章底板右下角那个攻/防小数字**
#      (见下面 `AD_*` 那一段)。它在徽章内部、不靠卡面美术 ——
#      上面那次漏判(铁锤)重放一遍:铁锤徽章只有 `3 K`、没有攻/防数字 -> 当场拒掉。
#      另一条曾经想走的路(卡类型图标模板)仍然不需要:图标长在卡面底部,
#      手机端手牌被屏幕下沿切掉。
# ---------------------------------------------------------------------------
BAR_STRIP_W = 18          # 徽章右边取多宽。★ 上限受**牌距**约束:9 张时牌距只有 ~60px,
                          #   而 26(徽章) + 3 + 18 = 47 < 60,不会伸到下一张牌身上。
BAR_DARK_V = 125          # "暗像素"的亮度线(名条底色实测 V 50~115)
UNIT_BAR_DARK = 0.74      # >= 这个 -> 名条像单位
ORDER_BAR_DARK = 0.68     # <  这个 -> 指令;中间 -> unknown(不碰)

#: 名条带里"这一行有字"的行占比 —— ★ 2026-09-19 起**降级成辅助信号**
#  (主判据是徽章里那个攻/防小数字,见下面的 `AD_*` 段)。留着它的用处有两个:
#   ① 真单位万一测不出攻/防数字时,它还能把这张牌标成 unknown 而不是 order
#      (两者都不拖,但日志里说得清);
#   ② 两个信号**打架**时(lines 高、却没有攻/防数字)-> 判 unknown,**不碰**。
# ★★★ 2026-09-18 加的,起因是用户第二次复现"把非洲军团当单位拖出去":
#   那张指令的卡面是**暗色黄昏天空**,又暗又平,`bar_dark`(暗像素占比)照样很高
#   → 判成单位 → 拖出去 → 弹出"三选一"选择框 → 引擎认不出(state=None)
#   → 空转两分钟。**根子是 `bar_dark` 只是"名条"的代理,而代理会被美术骗过。**
#
#   改成直接量"名条上有没有字" —— 也就是用户最早给的那条判据:
#     「只有单位卡的名字会在上边显示,指令不会显示」。
#   量法:带子里逐行看,**这一行既有深色底(V<125 过半)、又有明显亮于底的像素
#   (V >= 125+BAR_LINE_LIFT 至少 2 个)**,就算"有字的一行";取这种行的占比。
#
#   实测 81 个候选(全部存帧 + 真机帧),零重叠:
#     · 真单位(名条上有白字)      0.136 ~ 0.682
#     · 真指令 / 固定位置的假阳性  0.000 ~ 0.045
#   顺带它还修掉两个**反向**错误:`bar_dark` 把「步兵第 89 团」(0.639)和
#   「第 432 步兵」(0.528)这两张**有清楚名条的真单位**判成了指令 ——
#   它们的 lines 是 0.682 / 0.409,新判据认对了。
UNIT_LINES_MIN = 0.10

#: 判定"这一行有字"时,亮像素要比暗底线(V<125)亮出多少。
BAR_LINE_LIFT = 25

#: **强信号线**:`lines` 到了这里就是单位,不再看 `k_below`。
# ★ 2026-09-18 加,起因是用户第二次报"把铁锤(单位指向性指令)打出去了":
#   铁锤的卡面是"工人+农妇"的人物美术,**没有名条**,可它的人物亮部把
#   `lines` 喂到了 0.136 —— 刚过 0.10 那条线,于是被当成单位拖了出去。
#   而同一个判据在**另一个方向**也错:伊尔-2M 是真单位、名条上白字清清楚楚,
#   偏偏字太大导致"暗底不过半",`lines` 只有 0.045,被判 unknown(漏了)。
#
#   实测那一帧 7 张(用户当场确认过真身份)两两对照后发现 `k_below` 恰好互补:
#       铁锤(指令)      lines=0.136  k_below=0
#       伊尔-2M(单位)   lines=0.045  k_below=4
#   但 `k_below` **不能单独用** —— 真单位「三号坦克 L 型」的 k_below 也是 0
#   (而且第 10 回合那次 6 张牌的 k_below 全 0,启用它会把真单位全判成指令)。
#   所以只把它当**弱信号时的佐证**:
#
#       lines >= 0.25                        -> unit
#       0.10 <= lines < 0.25 且 k_below >= 1 -> unit
#       其余                                  -> 非 unit
#
#   效果(同 7 张):错 2 -> 错 1,而且剩下那个错是**漏真单位**(少打一张牌),
#   不是**放行指令**(拖出去弹选择框、卡死整局)。
UNIT_LINES_STRONG = 0.25

#: 弱信号时 `k_below` 至少要这么多才肯认(见上)。
WEAK_NEEDS_K_BELOW = 1

# ---------------------------------------------------------------------------
# ★★★ 主判据(2026-09-19 起):徽章底板右下角那个**攻/防小数字**
#
# 判据本身是用户早说过的:「单位卡徽章里 K 下面还有一个攻/防数字,指令没有」。
# 2026-09-18 试过一版(叫 `k_below`),**失败了** —— 框的位置做不稳:
# 那个小数字长在**底板右下角**,实测能伸到 `x+29`,而窗口只有 26px 宽,
# 于是它有一部分在窗口外面;窗口又是**居中在橙色数字碎片**上的,一偏就切到美术上。
# 代价很实在:第 10 回合那 6 张牌全部判成指令,**一张单位都打不出去**。
#
# ★★★ 2026-09-19 想明白两件事,这一版才立住(两件缺一不可):
#   ① **牌是扇形歪的** —— 水平切的窗口必然错位。倾角**不用另找检测器**:
#      **相邻两张牌的徽章中心连线方向 = 这张牌自身的 x 轴方向**
#      (徽章在每张牌的同一个相对位置)。实测 9 张手牌:最左 -12.0° -> 中间 -0.7°
#      -> 最右 +5.4°,正好是一条弧。见 `_fan_angles()`。
#   ② 判据不能只认"白色"(那个小数字**也能是灰的**,不可下的时候就是灰的),
#      要比**底板底色**亮才算笔画;而且必须先**往里收 3px** ——
#      底板的浅色描边和牌边都是亮线,不收进来就会被当成"笔画"。
#      实测(不inset):连"只有费用没有攻/防"的指令都测出 0.3+,两边分不开。
#
# **验收(全部有存帧,判据是"和现场看到的对上",不是"看起来合理")**:
#   · 真机 9 张手牌(2026-09-19 用户那局):7 单位 + 2 指令 -> **9/9 对**
#     (用户当场确认:左边那两张只有 `1 K`/`3 K` 的是指令);
#   · 实战 dump 71 个里,**两条判据打架的那 20 张** —— 老 `lines` 只对 3 张、
#     老 `k_below` 对 17 张,**这一版 20/20**:
#       8 张真指令(含**铁锤 ×4** —— 就是用户报的"又被拖出去"那张)全部拒掉,
#       12 张真单位(含老 k_below 漏掉的 `3 K 2`/`6 K 2`/`8 K 3` 三张)全部认出来;
#   · 被引擎真拖出去过的 29 张:29/29 与新查明的真相一致 ——
#     ★ 其中 2 张原来按"部署成功"当成单位,**裁出来一看是指令**
#       (铁锤 / 一张 `2 K` 无攻防的),说明"手牌少了+画面还是对局"**不能**证明
#       "部署的是单位" —— 瞬时指令也会这样。这一条要记住。
#   存帧:`shots/android/hand/kind/`(冻结帧)+ `shots/android/probe/_disagree_{A,B}.png`。
#
# 方向仍然偏安全:单位万一测不出这个小数字 -> 判 unknown/order -> **少打一张**;
# 反过来(指令被放行)才是要避免的(拖出去弹选择框、整局卡住)。
AD_INK_LIFT = 40          # 比**底板 25 分位亮度**亮这么多才算笔画(灰数字/橙数字都算)
AD_MIN_AREA = 4           # ★ 小于这个像素数是噪点。★ 2026-09-19 从 3 提到 4:
                          #   实机上一处假阳性正是 `a=3` 的 **2x2** 小块,贴在底板**最右下角**
                          #   —— 那是**底板边框漏进来的像素**,不是笔画(代价:把一张指令当单位拖了,
                          #   弹出"三选一"把整局卡住)。真数字被切成两半时最小也有 `2x3 / a=4`。
AD_MAX_AREA = 60          # 太大了就不是那个小数字(是大数字或 K 的一部分)
AD_MIN_W = 2              # ★ 笔画**至少 2px 宽** —— 底板右侧那道亮边只有 1px,
                          #   实测它单独成块、紧贴右边,把"只有 1 K 的道具卡"判成了单位
AD_MAX_W = 12             # 小数字的框不会比这更宽
AD_MAX_H = 10             # ★ 高**不超过 10px** —— 底板那圈浅色描边漏进来是**一整条**
                          #   (高度顶满分析区),而那个小数字只有 8px 上下
AD_MAX_SLENDER = 4.0      # ★ 高/宽 不许超过这个倍数 —— 细长条是**边框**,不是笔画
#: ★ 那个小数字**一定比它自己宽更高**(实测真笔画: 3x7 / 4x7 / 5x7 / 2x3 / 3x8)。
#: 反过来"**宽比高还大**"的块是**底板的上下边框**(实测那处假阳性就是 `8x4`:
#: 倾角估歪之后把卡片边框甩进了分析区)。这一条比倾角更值钱 —— 倾角估歪时它兜得住。
AD_NEEDS_TALLER = True
#: 判据区(相对底板):右半 x 下半。
#: ★★ 右/下边界**各留一点**:真数字实测最远到 `rx=0.95 / ry=0.88`,
#:    而漏进来的边框像素在 `(0.96, 0.96)`、`(0.98, 0.72)` 这种**贴边**位置。
#:    (2026-09-19:一处 `2x2 @ (0.96,0.96)` 的假阳性把一张指令当单位拖出去、
#:     弹出"三选一"卡住整局 —— 这条边界就是为它留的。)
AD_ROI = (0.55, 0.97, 0.50, 0.93)
#: 分析前往里收几像素(躲开底板描边/牌边那些亮线)。
#: ★ 实测**只收 1px 最好**:收 3px 会把**真数字**切掉一角,于是它只剩 1px 细条
#:   -> 被"细长条守卫"拒掉 -> **真单位漏判**。网格搜索(68 张有真值的牌)给了 4 组并列最优,
#:   这一组(1/2/10/4.0)是其中之一;**收 3px 那组错 4 张**(3 假阴 + 1 假阳)。
PLATE_INSET = 1
PLATE_DARK_V = 110        # 底板是暗方块



def hand_zone(cfg_path: str = "") -> tuple:
    """手牌搜索区:优先读 `config/board_android.json` 里的 `hand.search_zone`。"""
    p = cfg_path or os.path.join(PROJECT_ROOT, "config", "board_android.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            h = json.load(f)["hand"]
        z = h.get("search_zone") or h["box"]
        return tuple(z)
    except (OSError, ValueError, KeyError):
        return DEFAULT_ZONE


def hand_box(cfg_path: str = "") -> tuple:
    """手牌那条带子(**量出来的**,给调试叠图画框用)。"""
    p = cfg_path or os.path.join(PROJECT_ROOT, "config", "board_android.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return tuple(json.load(f)["hand"]["box"])
    except (OSError, ValueError, KeyError):
        return DEFAULT_BAND


# ---------------------------------------------------------------------------
# 检测
# ---------------------------------------------------------------------------

def _orange_anchors(frame, zone):
    """橙像素 -> 连通域。返回 [(x, y, w, h, area)] —— 只是"去哪儿看",不是结论。"""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    H = hsv[:, :, 0].astype(int)
    S = hsv[:, :, 1]
    V = hsv[:, :, 2]
    m = ((H >= ANCHOR_HUE[0]) & (H <= ANCHOR_HUE[1])
         & (S >= ANCHOR_S_MIN) & (V >= ANCHOR_V_MIN)).astype(np.uint8)
    keep = np.zeros_like(m)
    if zone:
        keep[zone[1]:zone[3], zone[0]:zone[2]] = 1
        m = cv2.bitwise_and(m, keep)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, _lab, st, _c = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = (int(st[i, 0]), int(st[i, 1]), int(st[i, 2]),
                         int(st[i, 3]), int(st[i, 4]))
        if a < ANCHOR_MIN_AREA:
            continue
        if not (ANCHOR_W[0] <= w <= ANCHOR_W[1] and ANCHOR_H[0] <= h <= ANCHOR_H[1]):
            continue
        out.append((x, y, w, h, a))
    return out


def _verify(frame, V, S, DI_dark, x, y, w, h):
    """
    把候选放到一个 `DIGIT_WIN` 窗口里,问 `unit_state.analyze_digit`:
    "这块暗底里有没有一个橙色数字?"—— 有就返回徽章 dict,没有就 None。
    """
    fh, fw = frame.shape[:2]
    cx, cy = x + w // 2, y + h // 2
    wx = int(np.clip(cx - DIGIT_WIN // 2, 0, fw - DIGIT_WIN))
    wy = int(np.clip(cy - DIGIT_WIN // 2, 0, fh - DIGIT_WIN))
    df = (DI_dark[wy + DIGIT_WIN, wx + DIGIT_WIN] - DI_dark[wy, wx + DIGIT_WIN]
          - DI_dark[wy + DIGIT_WIN, wx] + DI_dark[wy, wx]) / float(DIGIT_WIN ** 2)
    if df < DIGIT_DARK_MIN:
        return None
    vc = V[wy:wy + DIGIT_WIN, wx:wx + DIGIT_WIN]
    sc = S[wy:wy + DIGIT_WIN, wx:wx + DIGIT_WIN]
    d = us.analyze_digit(vc, sc)
    if d is None:
        # A narrow cost 1 and the separate lower-right operation 1 can shift
        # their combined bounding box away from this cost-centered window.
        # Only a confirmed hand badge may retry with those small glyphs removed;
        # the shared digit size/color/centering limits remain unchanged.
        candidate = {"x": wx, "y": wy, "w": DIGIT_WIN, "h": DIGIT_WIN,
                     "cx": wx + DIGIT_WIN // 2, "cy": wy + DIGIT_WIN // 2}
        _plate, confirmed = _badge_plate(frame, candidate, V, with_confirmation=True)
        if confirmed:
            d = _primary_cost_digit(vc, sc)
    if d is None or d["digit_n"] < DIGIT_N_MIN:
        return None
    return {"x": wx, "y": wy, "w": DIGIT_WIN, "h": DIGIT_WIN,
            "cx": wx + DIGIT_WIN // 2, "cy": wy + DIGIT_WIN // 2,
            "dark_frac": round(float(df), 3), "anchor": [x, y, w, h], **d}


def _primary_cost_digit(vc, sc):
    """Retry a confirmed mobile hand badge using its tall cost numeral only.

    Require a separate operation-sized component to the lower right before
    removing short glyphs. This handles the mobile cost/K/operation layout,
    without weakening the shared center test or inventing a missing numeral.
    """
    enclosed, _bright = us.enclosed_bright(vc)
    n, labels, stats, _centers = cv2.connectedComponentsWithStats(
        enclosed.astype(np.uint8), 8)
    primary = np.zeros_like(enclosed)
    for i in range(1, n):
        bx, by, bw, bh, area = map(int, stats[i])
        if (area >= us.DIGIT_BLOB_MIN_PX and bw <= us.DIGIT_BLOB_W_MAX
                and AD_MAX_H < bh <= us.DIGIT_BLOB_H_MAX):
            primary |= labels == i
    if int(primary.sum()) < DIGIT_N_MIN:
        return None
    _ys, xs = np.nonzero(primary)
    right = int(xs.max())
    has_operation = any(
        int(st[0]) > right and int(st[1]) >= vc.shape[0] / 2
        and AD_MIN_W <= int(st[2]) <= AD_MAX_W
        and int(st[2]) <= int(st[3]) <= AD_MAX_H
        and int(st[3]) <= AD_MAX_SLENDER * int(st[2])
        and AD_MIN_AREA <= int(st[4]) <= AD_MAX_AREA
        for st in stats[1:])
    if not has_operation:
        return None
    isolated = vc.copy()
    # Keep the original background percentile/brightness threshold: filling
    # with a darker value would change it and could recruit extra pixels.
    background = float(np.percentile(vc, us.DIGIT_BG_PCT))
    threshold = min(us.DIGIT_DARK_V, background + us.DIGIT_REL_DELTA)
    isolated[enclosed & ~primary] = threshold - 1
    return us.analyze_digit(isolated, sc)


def _nms(badges, dist=None):
    """按中心距离去重,留下数字像素最多的那个。"""
    dist = NMS_DIST if dist is None else dist
    out = []
    for b in sorted(badges, key=lambda b: -b["digit_n"]):
        if any(abs(b["cx"] - o["cx"]) <= dist and abs(b["cy"] - o["cy"]) <= dist
               for o in out):
            continue
        out.append(b)
    out.sort(key=lambda b: b["cx"])
    return out


def _bar_lines(v) -> float:
    """
    名条带子里"**这一行有字**"的行占多大比例。

    ★ 判据来自用户最早那句话:「只有单位卡的名字会在上边显示,指令不会显示」。
      所以这里不去量"暗不暗"(那是代理,会被暗色美术骗过),而是直接问:
      **这一行上有没有字?**

    "有字的一行"= 同时满足两条:
      · 深色底:`V < BAR_DARK_V` 的像素过半 —— 名条是一条深色横带;
      · 有笔画:至少 2 个像素亮到 `V >= BAR_DARK_V + BAR_LINE_LIFT` ——
        那是白色的字。纯暗的美术没有这么亮的点。

    ★ 为什么要求"至少 2 个"而不是 1 个:单个亮点可能就是噪点或高光。
    """
    if v.size == 0:
        return 0.0
    dark_line = (v < BAR_DARK_V).mean(axis=1) >= 0.5
    bright_px = (v >= BAR_DARK_V + BAR_LINE_LIFT).sum(axis=1) >= 2
    return float((dark_line & bright_px).mean())


def _badge_plate(frame, badge, V=None, *, with_confirmation=False) -> tuple:
    """
    找徽章底板。默认仍返回 `(x,y,w,h)`，供旧几何调用者使用。
    `with_confirmation=True` 返回 `(box, confirmed)`；回退窗口只能诊断，不能授权单位。

    底板 = **包含徽章中心的那块暗连通域**(深色方牌 + 浅色描边,所以它一般是孤立的)。
    尺寸不像徽章(18~36px)时不能把卡面美术中的局部暗块当作底板。
    左侧倾斜真徽章的浅描边可能在 V<110 下连到名字条；仅当两个更暗阈值
    都独立找出同一块有界底板时恢复它，不把固定26px窗口当作结构证据。

    ★★ 2026-09-19 改了选取方式(原来选"含最多橙锚像素的那块"):
      现在按**包含徽章中心**选。理由:橙色数字可能只是数字的**一块碎片**
      (例如 "4" 的那一竖),按"含最多橙像素"会选到偏的那块;
      而徽章窗口本身就是居中在这个数字上的,**中心一定落在底板里**,更稳。
    """
    if V is None:
        V = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2].astype(int)
    fh, fw = V.shape[:2]
    pad = 12
    x0 = max(0, badge["x"] - pad)
    y0 = max(0, badge["y"] - pad)
    x1 = min(fw, badge["x"] + badge["w"] + pad)
    y1 = min(fh, badge["y"] + badge["h"] + pad)
    cx, cy = badge["cx"] - x0, badge["cy"] - y0
    def component(threshold):
        sub = (V[y0:y1, x0:x1] < threshold).astype(np.uint8)
        n, _lab, st, _c = cv2.connectedComponentsWithStats(sub, 8)
        best, best_a = None, 0
        for i in range(1, n):
            bx, by, bw, bh, a = (int(st[i, 0]), int(st[i, 1]), int(st[i, 2]),
                                 int(st[i, 3]), int(st[i, 4]))
            if not (18 <= bw <= 36 and 18 <= bh <= 36):
                continue
            if not (bx <= cx <= bx + bw and by <= cy <= by + bh):
                continue
            if a > best_a:
                best, best_a = (x0 + bx, y0 + by, bw, bh), a
        return best
    best = component(PLATE_DARK_V)
    if best is None:
        darker, darkest = component(95), component(75)
        if darker is not None and darkest is not None:
            ax, ay, aw, ah = darker
            bx, by, bw, bh = darkest
            overlap = max(0, min(ax+aw, bx+bw)-max(ax,bx)) * max(0, min(ay+ah, by+bh)-max(ay,by))
            union = aw*ah + bw*bh - overlap
            if union and overlap/union >= .65:
                best = darker
    confirmed = best is not None
    box = best or (badge["x"], badge["y"], badge["w"], badge["h"])
    return (box, confirmed) if with_confirmation else box


def _fan_angles(plates) -> list:
    """
    每张牌的**倾角**(度)。手机端手牌是扇形,每张牌都歪着,水平窗口必然错位。

    ★ 倾角不用另找检测器:**相邻两张牌的徽章中心连线方向 = 这张牌自身的 x 轴方向**
      —— 徽章长在每张牌的同一个相对位置,所以这条连线就是牌的朝向。
      实测 9 张手牌:最左 -12.0° / 中间 -0.7° / 最右 +5.4°,正好是一条弧。
    ★ 只有一张牌时没法连线 -> 返回 0(不转),此时判据会退化成老行为,如实记着。
    """
    if len(plates) < 2:
        return [0.0] * len(plates)
    cx = [p[0] + p[2] / 2.0 for p in plates]
    cy = [p[1] + p[3] / 2.0 for p in plates]
    out = []
    for i in range(len(plates)):
        if i == 0:
            dx, dy = cx[1] - cx[0], cy[1] - cy[0]
        elif i == len(plates) - 1:
            dx, dy = cx[-1] - cx[-2], cy[-1] - cy[-2]
        else:
            dx, dy = cx[i + 1] - cx[i - 1], cy[i + 1] - cy[i - 1]
        out.append(float(np.degrees(np.arctan2(dy, dx))))
    return out


def _rot(img, deg):
    """绕中心旋转(尺寸不变)。边缘用**复制**填充,免得凭空造出一条亮/暗边。"""
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), deg, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def _ad_numeral(frame, badge, angle: float = 0.0) -> tuple:
    """
    徽章底板右下角**有没有那个攻/防小数字**。返回 `(has_ad, info)`。

    做法(每一步都是踩出来的,别省):
      ① 先框出**底板**(`_badge_plate`)—— 以底板为坐标基准,而不是以橙色碎片;
      ② 按这张牌的倾角**转正**(`_fan_angles`);
      ③ **往里收 `PLATE_INSET` 像素**再分析 —— 底板描边和牌边都是亮线,
         不收进来就会被当成"笔画"(实测:不收时连指令都测出 0.3+,两边分不开);
      ④ 底色 = 这块的 **25 分位亮度**(底板是暗的、数字是亮的,分位不会被数字带跑);
         亮到 `底色 + AD_INK_LIFT` 以上的算笔画 —— ★ 不认颜色,
         因为那个小数字**可下时是橙的、不可下时是灰的**;
      ⑤ 连通域里找**右下角那个小块**(位置 + 尺寸都对)才算有。
    """
    (px, py, pw, ph), confirmed = _badge_plate(frame, badge, with_confirmation=True)
    if not confirmed:
        return False, {"plate": [px, py, pw, ph], "plate_confirmed": False,
                       "ad": [], "base": 0.0, "reason": "没有确认的费用底板"}
    h_img, w_img = frame.shape[:2]
    px = max(0, min(px, w_img - 2))
    py = max(0, min(py, h_img - 2))
    pw = max(2, min(pw, w_img - px))
    ph = max(2, min(ph, h_img - py))
    crop = frame[py:py + ph, px:px + pw].copy()
    if angle:
        crop = _rot(crop, angle)
    h, w = crop.shape[:2]
    inner = crop[PLATE_INSET:h - PLATE_INSET, PLATE_INSET:w - PLATE_INSET]
    if inner.size == 0:
        return False, {"plate": [px, py, pw, ph], "plate_confirmed": True,
                       "ad": [], "base": 0.0}
    V = cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)[:, :, 2].astype(int)
    base = float(np.percentile(V, 25))
    m = (V >= base + AD_INK_LIFT).astype(np.uint8)
    n, _lab, st, _c = cv2.connectedComponentsWithStats(m, 8)
    ih, iw = inner.shape[:2]
    ad, edge_rejected = [], []
    for i in range(1, n):
        bx, by, bw, bh, a = (int(st[i, 0]), int(st[i, 1]), int(st[i, 2]),
                             int(st[i, 3]), int(st[i, 4]))
        if a < AD_MIN_AREA or a > AD_MAX_AREA:
            continue
        if bw < AD_MIN_W or bw > AD_MAX_W or bh > AD_MAX_H:
            continue
        # ★ 细长条一律不收:底板框一旦大了一点,卡片的亮边就会以 1px 宽的细条
        #   出现在分析区边缘 —— 那是**边框**,不是笔画。
        #   (实测那处假阳性就是 `1x5`;真数字的块是 2x3 / 3x7 / 5x7。)
        if bh > AD_MAX_SLENDER * bw:
            continue
        if AD_NEEDS_TALLER and bh < bw:
            continue
        rx, ry = (bx + bw / 2.0) / iw, (by + bh / 2.0) / ih
        if AD_ROI[0] <= rx <= AD_ROI[1] and AD_ROI[2] <= ry <= AD_ROI[3]:
            # A numeral must be a complete interior component. Rotation can
            # leave a 2x6 fragment of the plate outline at the lower-right
            # analysis edge; its size/center alone mimics an operation digit.
            # A clipped component cannot establish that a unit numeral exists.
            if bx <= 0 or by <= 0 or bx + bw >= iw or by + bh >= ih:
                edge_rejected.append([bx, by, bw, bh, a])
                continue
            ad.append([a, round(rx, 2), round(ry, 2), bw, bh])
    return bool(ad), {"plate": [px, py, pw, ph], "plate_confirmed": True,
                      "ad": ad, "base": round(base), "edge_rejected": edge_rejected}


def card_kind(frame, badge, angle: float = 0.0) -> tuple:
    """
    这张手牌是**单位**还是**指令**?返回 `(kind, bar_dark, lines, ad, ad_info)`。

    kind ∈ {'unit'(能拖出去部署), 'order'(指令/反制,**绝不能拖**), 'unknown'(拿不准,当成不碰)}。

    ★★★ 判据的演化(三次都是被"拖出指令"逼出来的,别再把中间那版当成现状):
      ① 最早只用 `bar_dark`(徽章右边那一条暗不暗)—— 它只是"名条"的**代理**,
         会被暗色美术骗过(非洲军团的黄昏天空);
      ② 2026-09-18 换成 `lines`(名条带上"有字的行"占比)—— 也是代理,
         一样会被美术骗;而且它在**真单位**上也会量出 0.045(伊尔-2M);
         `k_below` 那一版(徽章里的小数字)因为**框放不稳**被降级成弱信号佐证;
      ③ **现在(2026-09-19)的主判据 = 徽章底板右下角那个攻/防小数字**(`_ad_numeral`)。
         它是**结构化**的:在徽章内部,不靠卡面美术,也不靠名字 ——
         名字那条路已被证实走不通(手牌一多,名条只剩 2 个字,见文件头)。

    判定顺序:
        ad 有            -> unit      (主判据;实测 20/20 + 29/29 + 真机 9 张 9/9)
        没有 ad:
          lines >= UNIT_LINES_STRONG -> unknown  (有名条却没小数字:两个信号打架,**不碰**)
          bar_dark < ORDER_BAR_DARK  -> order
          其余                        -> unknown
    """
    V = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2].astype(int)

    # ---- ① 名条那一带(现在是**辅助**信号,不再独自决定任何一张牌) ----
    x0 = badge["x"] + badge["w"] + 3
    x1 = min(frame.shape[1], x0 + BAR_STRIP_W)
    y0 = max(0, badge["y"] + 2)
    y1 = min(frame.shape[0], badge["y"] + badge["h"] - 2)
    if x1 - x0 < 6 or y1 - y0 < 6:
        bar_dark, lines = 0.0, 0.0
    else:
        v = V[y0:y1, x0:x1]
        bar_dark = float(np.median((v < BAR_DARK_V).mean(axis=1)))
        lines = _bar_lines(v)

    # ---- ② 徽章底板右下角那个攻/防小数字(主判据) ----
    ad, ad_info = _ad_numeral(frame, badge, angle)

    # ---- ③ 判定 ----
    if not ad_info.get("plate_confirmed"):
        return "unknown", round(bar_dark, 3), round(lines, 3), False, ad_info
    if ad:
        return "unit", round(bar_dark, 3), round(lines, 3), True, ad_info
    if lines >= UNIT_LINES_STRONG:
        # 名条像是有字、可徽章里没有攻/防数字 —— 两个信号打架。
        # 实测这一档里**指令占多数**(铁锤、非洲军团那种人物美术都会被 lines 喂高),
        # 所以**不碰**;真单位掉进这里只是少打一张牌,方向是安全的。
        return "unknown", round(bar_dark, 3), round(lines, 3), False, ad_info
    if bar_dark < ORDER_BAR_DARK:
        return "order", round(bar_dark, 3), round(lines, 3), False, ad_info
    return "unknown", round(bar_dark, 3), round(lines, 3), False, ad_info



def find_hand(frame, zone: tuple = None, want: str = "orange",
              units_only: bool = False, debug: bool = False,
              max_units: int = 0) -> list:
    """
    手牌里**费用数字是 `want` 颜色**的牌,按从左到右排。

    返回 [{'x','y','w','h','cx','cy','digit_s','digit_v','digit_n','state',
           'dark_frac','anchor','kind','bar_dark','lines','ad','plate','angle'}]。
    `x/y/w/h` 是**那个徽章窗口**的框;要按牌就按 `grab_point()` 给的坐标。

    ★ `kind` 的主判据是**徽章底板右下角那个攻/防小数字**(见 `_ad_numeral`);
      `bar_dark` / `lines` 只当辅助信号(它们会被卡面美术骗,历史见 `card_kind`)。

    want: 'orange' = 这回合下得起的(默认) / 'grey' = 下不起的 / 'any'。
    ★ `want='grey'` **现在不可靠**:灰数字和牌名白字一样是"暗底上的亮低饱和块",
      实测会捞到一堆名字字。留着这个开关是为了做 A/B,不是让你拿它数牌。

    units_only: True 时**只留判成 `unit` 的**(指令和 unknown 都丢掉)——
      **引擎要拖牌时必须用 True**,理由见文件头"单位 / 指令 的判别"。
    max_units: 大于 0 时，仍然先召回**全部费用徽章**并计算整手牌倾角，
      但从左到右判定卡牌类型，找到这么多单位后就停止。这样惰性出牌不会
      漏掉费用候选，也不会为了判断后面的牌继续做昂贵的攻防数字分析。
    """
    if frame is None or not hasattr(frame, "shape"):
        return []
    zone = hand_zone() if zone is None else zone
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    V = hsv[:, :, 2].astype(np.float32)
    S = hsv[:, :, 1]
    DI_dark = cv2.integral((V < us.BADGE_DARK_V).astype(np.float32))

    found, rejected = [], []
    for (x, y, w, h, _a) in _orange_anchors(frame, zone):
        b = _verify(frame, V, S, DI_dark, x, y, w, h)
        (found if b is not None else rejected).append(b or {"anchor": [x, y, w, h]})
    found = [b for b in found if want == "any" or b["state"] == want]
    found = _nms(found)
    # ★ 倾角要从**整手牌的徽章位置**估计(相邻两点连线 = 这张牌的朝向),
    #   所以先都框出底板、一起算,再逐个判 kind。
    # Artwork can satisfy the orange-digit probe without having a cost plate.
    # Such a rejected point must not tilt its valid neighbours: a low aircraft
    # art patch once rotated a real order by -37 degrees, moving its K into the
    # operation-numeral region. Estimate the fan only from confirmed plates.
    confirmed = [(i, plate) for i, b in enumerate(found)
                 for plate, valid in [_badge_plate(frame, b, V, with_confirmation=True)]
                 if valid]
    angles = [0.0] * len(found)
    for (i, _plate), angle in zip(confirmed, _fan_angles([p for _i, p in confirmed])):
        angles[i] = angle
    unit_seen = 0
    for i, b in enumerate(found):
        (b["kind"], b["bar_dark"], b["lines"],
         b["ad"], b["ad_info"]) = card_kind(frame, b, angle=angles[i])
        b["angle"] = round(angles[i], 1)
        if b["kind"] == "unit":
            unit_seen += 1
            if units_only and max_units > 0 and unit_seen >= max_units:
                break
    if units_only:
        found = [b for b in found if b.get("kind") == "unit"]
    if debug:
        print(f"  锚点 {len(found) + len(rejected)} 个 -> 要 "
              f"{'全部' if want == 'any' else want} 的 {len(found)} 个"
              f"{'(已滤成单位)' if units_only else ''}")
        for b in found:
            print(f"    x{b['x']:4d} y{b['y']:4d} {b['w']}x{b['h']}  "
                  f"S={b['digit_s']:6.1f} V={b['digit_v']:6.1f} "
                  f"n={b['digit_n']:3d} 暗={b['dark_frac']:.2f} -> {b['state']}"
                  f"  | {b['kind']:7s} 攻防数字={'有' if b['ad'] else '无'}"
                  f" 倾角={b.get('angle', 0):+5.1f}°"
                  f" bar_dark={b['bar_dark']:.2f} lines={b.get('lines', -1):.2f}"
                  f"  底板={b['ad_info'].get('plate')}")
        for r in rejected:
            print(f"    [丢] 锚点 x{r['anchor'][0]} y{r['anchor'][1]} "
                  f"{r['anchor'][2]}x{r['anchor'][3]}")
    return found


def grab_point(badge, dy: int = 22) -> tuple:
    """
    **按哪个点能把这张牌抓起来**(客户区坐标)。

    ★ 为什么不按徽章正中:徽章在牌的**左上角**、太靠边;稍微往下一点才是牌身。
    ★ 为什么不往右挪(电脑端 `unit_state.drag_from_point` 是 +60/+70):
      **手机端手牌是扇形叠着的** —— 牌距实测 6 张时 118px、9 张时只有 60px。
      往右挪 60px 在 9 张手牌上会**落到下一张牌身上**,拖错牌。
      ⇒ 只往下挪:横坐标**咬死在徽章中心**,那一列一定属于这张牌。
      竖着挪 22px 还在牌的浅色顶边/名字条上,离徽章也不远(不会碰到场上单位)。

    ★★ 2026-09-18 加**夹住**:实测有一张牌(扇形里位置偏低的那张)算出来是
      `(519, 725)`,而客户区只有 **720** 高 —— **y 已经掉出屏幕了**,
      真按那儿按下去等于没按(而且不会报错)。现在夹到画面内。
      ★ 夹住只是"别把点击丢到屏幕外";**不保证那一点真的在牌上** ——
        所以 `deploy_one_unit` 那边**还要靠"拖完手牌变了没有"来验**。
    """
    x = int(min(max(badge["cx"], 2), CLIENT_W - 3))
    y = int(min(max(badge["cy"] + dy, 2), CLIENT_H - 4))
    return (x, y)


# ---------------------------------------------------------------------------
# 画出来看(强制步骤)
# ---------------------------------------------------------------------------

def debug_overlay(frame, badges, path, zone=None, band=None, note=""):
    """
    把"它看到了什么"画出来存盘。**必须打开看一眼**再拿结果下结论。
    绿框 = 认下来的徽章;红框 = 被丢掉的锚点(画在 `find_hand(debug=True)` 里看不到,
    所以这里只画认下来的);品红 = 量出来的手牌带;黄 = 搜索区。
    """
    vis = frame.copy()
    z = hand_zone() if zone is None else zone
    cv2.rectangle(vis, (z[0], z[1]), (z[2], z[3]), (0, 255, 255), 1)
    cv2.putText(vis, "search zone", (z[0] + 2, z[1] + 13),
                cv2.FONT_HERSHEY_SIMPLEX, 0.36, (0, 255, 255), 1)
    if band is not None:
        cv2.rectangle(vis, (band[0], band[1]), (band[2], band[3]), (255, 0, 255), 1)
        cv2.putText(vis, "hand box", (band[0] + 2, band[3] - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, (255, 0, 255), 1)
    for k, b in enumerate(badges, 1):
        # ★ 绿 = 判成"单位"(能拖);红 = 指令/拿不准(**不能拖**)。
        col = (0, 255, 0) if b.get("kind") == "unit" else (0, 0, 255)
        cv2.rectangle(vis, (b["x"], b["y"]), (b["x"] + b["w"], b["y"] + b["h"]),
                      col, 1)
        # ★ 底板(判据的坐标基准)也画出来 —— 判错时第一眼要看的就是"框住底板没有"。
        pl = (b.get("ad_info") or {}).get("plate")
        if pl:
            cv2.rectangle(vis, (pl[0], pl[1]), (pl[0] + pl[2], pl[1] + pl[3]),
                          (255, 128, 0), 1)
        gx, gy = grab_point(b)
        cv2.drawMarker(vis, (gx, gy), col, cv2.MARKER_CROSS, 9, 1)
        tag = {"unit": "U", "order": "O"}.get(b.get("kind"), "?")
        cv2.putText(vis, f"{k}{tag}ad{'Y' if b.get('ad') else 'N'}"
                         f"/{b.get('angle', 0):+.0f}",
                    (b["x"] - 3, b["y"] - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.32, col, 1)
    nu = sum(1 for b in badges if b.get("kind") == "unit")
    cv2.putText(vis, f"{len(badges)} orange / {nu} unit {note}", (z[0] + 2, z[3] - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    if not imwrite_u(path, vis):
        print(f"  [存帧] **写不进去**:{path}(路径有中文? 用 imwrite_u 才对)")
        return ""
    return path


# ---------------------------------------------------------------------------
# ★★★ 出牌(2026-09-17 实机验通的第一条完整链)
#
# ★★★ **坐标系陷阱(我在这上面白扔了一整轮)**:`actions.click / move_drag`
#   收的是**屏幕坐标**(设备像素 1920x1080),**不是**引擎的客户区坐标(1280x720)。
#   `main_loop` 在调用它们之前已经做过 `client_to_screen`。
#   ⇒ 这里也必须先 `p.client_to_screen(None, cx, cy)` 再交给 `actions`。
#   症状非常像"输入通道坏了":命令 rc=0、日志正常、**画面上什么都不动**
#   (点全落在战场中间的空地上)。**这类错只能靠"点完去对画面"发现。**
# ---------------------------------------------------------------------------

def click_client(cx: int, cy: int, jitter: int = 4) -> None:
    """
    **按客户区坐标点一下**。★ 存在的唯一理由:把那个坐标系陷阱挡在一处。

    `actions.click` 要的是**屏幕坐标**(设备像素),而引擎里所有坐标表都是**客户区**
    (1280x720)。`main_loop` 自己在调用前做了换算,别的地方很容易忘 ——
    忘掉的表现是"点了没反应,而且不报错"。⇒ 统一从这里走。
    """
    import actions
    import platformapi
    p = platformapi.get()
    sx, sy = p.client_to_screen(None, int(cx), int(cy))
    actions.click(sx + random.randint(-jitter, jitter),
                  sy + random.randint(-jitter, jitter))


DEPLOY_DROP = (830, 430)   # 我方战线上的落点(**客户区**;实测这一拖真的把单位放下去了)
DEPLOY_VERIFY = (560, 720, 200, 1100)   # 验证用:手牌带 (y0,y1,x0,x1)

# ---------------------------------------------------------------------------
# ★★★ 出牌前**必须存帧**(2026-09-18 用户提的,补上一个真缺口)
#
# 为什么:上一轮引擎把一条指令当单位拖了出去,用户问"有没有出牌前的截图" ——
# **没有**。引擎抓的帧验完就丢,我手动存的那几张又全是出牌**之后**的。
# 结果就是:知道判错了、**量不出错在哪一块像素上**。
# 这个项目自己写过一句话:"只留下日志是量不出'到底读错了哪块像素'的"。
# ⇒ 从现在起,**每一次真的要去拖之前**,把三样东西落盘:
#      before.png   —— 做决定用的那一帧(**原图**,不许裁)
#      overlay.png  —— 把"它看到了什么"画上去(候选框、判成单位还是指令、bar_dark)
#      decision.txt —— 每个候选的原始数字 + 挑了哪一个 + 落点 + 拖完的验证结论
#      after.png    —— 拖完之后那一帧(用来对"到底动了什么")
# ★ 落盘失败**绝不许影响出牌** —— 整块包在 try 里,出问题只写一行日志。
# ---------------------------------------------------------------------------
DUMP_ROOT_DEFAULT = os.path.join(os.path.expanduser("~"), "Desktop",
                                 "手机版截图", "test")


def imwrite_u(path: str, img) -> bool:
    """
    **能写中文路径**的 `cv2.imwrite`。返回 True/False,**绝不静默**。

    ★★★ 为什么非要有它:`cv2.imwrite` 在 Windows 上遇到**非 ASCII 路径**
      会**直接返回 False、不抛异常** —— 而这个项目的存帧目录就叫
      `C:\\Users\\...\\Desktop\\手机版截图\\test`,正好踩上。
      实测后果:`dump_deploy` 建好了目录、写好了 `decision.txt`,
      **`before.png` / `overlay.png` 一个都没落盘,而且一声不响**。
      (同一个坑这一轮开头就踩过一次:`cv2.imread` 读不了中文文件名,
       当时的"修法"是把文件改名成 ASCII —— 这次路径是用户指定的,改不了,
       所以必须走 `imencode` + `ndarray.tofile`。)
    """
    try:
        ext = os.path.splitext(path)[1] or ".png"
        ok, buf = cv2.imencode(ext, img)
        if not ok:
            return False
        buf.tofile(path)
        return True
    except Exception:                            # noqa: BLE001
        return False


def imread_u(path: str):
    """**能读中文路径**的 `cv2.imread`(同样的理由,见 `imwrite_u`)。"""
    try:
        return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:                            # noqa: BLE001
        return None


def _w(path: str, img, what: str) -> None:
    """写一张图;失败**要吵**,不许静默(见 `imwrite_u` 的说明)。"""
    if not imwrite_u(path, img):
        raise OSError(f"写不进去:{what} -> {path}")


def dump_root() -> str:
    """存帧的根目录。`KARDS_DUMP_DIR` 能覆盖(设备上跑的时候用得上)。"""
    return os.environ.get("KARDS_DUMP_DIR") or DUMP_ROOT_DEFAULT


def dump_deploy(tag: str, before, after=None, note: str = "") -> str:
    """
    把"这一次拖"的全套证据落盘,返回目录(失败返回空串,**不抛异常**)。

    ★ `overlay.png` 是这里最关键的一样:**只留原图,下一次还得重新推一遍判据**;
      把当时看到的框和分数画上去,才可能一眼看出"它为什么把这张判成单位"。
    """
    try:
        import time
        d = os.path.join(dump_root(),
                         time.strftime("%Y%m%d_%H%M%S") + "_" + (tag or "deploy"))
        os.makedirs(d, exist_ok=True)
        _w(os.path.join(d, "before.png"), before, "before.png")
        zone = _zone_for(before, None)
        cards = find_hand(before, zone=zone, debug=False)
        debug_overlay(before, cards, os.path.join(d, "overlay.png"), zone=zone,
                      band=hand_box() if before.shape[1] == 1280 else None,
                      note="(存帧自查用)")
        lines = [f"tag={tag}", f"note={note}",
                 f"frame={before.shape[1]}x{before.shape[0]}",
                 f"zone={zone}",
                 f"主判据 攻/防小数字:底板右下角有一个小笔画块(V >= 底板25分位"
                 f"+{AD_INK_LIFT}, 面积 {AD_MIN_AREA}~{AD_MAX_AREA}, 相对位置 x>="
                 f"{AD_ROI[0]} y>={AD_ROI[2]})  先按牌倾角转正、且往里收 "
                 f"{PLATE_INSET}px 再量(躲开底板描边/牌边那些亮线)",
                 f"辅助 UNIT_BAR_DARK={UNIT_BAR_DARK} ORDER_BAR_DARK={ORDER_BAR_DARK}"
                 f"(暗线 V<{BAR_DARK_V})  名条带 = 徽章右 {BAR_STRIP_W}px",
                 f"两者打架(lines>={UNIT_LINES_STRONG} 但没有攻防数字)-> unknown,不碰",
                 "", f"候选 {len(cards)} 个(按 x 排):"]
        # ★ 2026-09-18:把 `lines` / `k_below` 也写进来。
        #   起因:用户报"把铁锤打出去了、10 回合拖了一次反制",而翻遍 34 个 dump
        #   都**查不出当时那张牌的特征** —— 老格式只记了 kind/bar_dark。
        #   证据要能自证,不然每次都得重跑一局去撞同一张牌。
        # ★ 2026-09-19:判据换成"攻/防小数字"之后,这里记 `ad`(有没有)与 `angle`
        #   (这张牌的倾角)—— 就是这一版判据的全部输入,出问题能直接复盘。
        for i, b in enumerate(cards, 1):
            lines.append(
                f"  {i:2d}) x={b['cx']:4d} y={b['cy']:4d}  state={b['state']:6s}"
                f"  kind={b['kind']:7s}  ad={'Y' if b.get('ad') else 'N'}"
                f"({b.get('ad_info', {}).get('ad')})  angle={b.get('angle', 0):+.1f}"
                f"  lines={b.get('lines', -1):.3f}"
                f"  bar_dark={b['bar_dark']:.3f}"
                f"  digit_S={b['digit_s']:.1f} V={b['digit_v']:.1f} n={b['digit_n']}"
                f"  抓取点={grab_point(b)}")
        units = [b for b in cards if b["kind"] == "unit"]
        lines.append("")
        lines.append(f"判成**单位**的 {len(units)} 个:"
                     f"{[grab_point(b) for b in units]}")
        lines.append(f"→ 实际会拖:"
                     f"{grab_point(units[0]) if units else '**没有,不拖**'}")
        if after is not None:
            _w(os.path.join(d, "after.png"), after, "after.png")
            lines.append("")
            lines.append("after.png = 拖完之后那一帧")
        with open(os.path.join(d, "decision.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return d
    except Exception as e:                       # noqa: BLE001
        try:
            print(f"  [存帧] 失败(不影响出牌):{type(e).__name__}: {e}")
        except Exception:                        # noqa: BLE001
            pass
        return ""


#: 拖完**晚看**多久再判"这是不是普通部署"(秒)。
# ★★★ 2026-09-19 加的,起因是实机上**第二次**"把非洲军团打出去":
#   拖完 1.2s 那一帧画面还是对局(于是判"部署成功"),而"三选一"选择框**晚一点**才弹 ——
#   那一局在框上**卡了 13 分钟**,直到人工点掉。
#   ⇒ 指令的特效/选择框会晚 1~2 秒出现,所以要多看一眼。
LATE_STATE_WAIT = 2.5


_LAST_DEPLOY_ATTEMPT = None
_LAST_DEPLOY_PENDING = None


def take_last_deploy_attempt():
    """Consume evidence even when the input did not produce a confirmed deployment."""
    global _LAST_DEPLOY_ATTEMPT
    value, _LAST_DEPLOY_ATTEMPT = _LAST_DEPLOY_ATTEMPT, None
    return value


def take_last_deploy_pending():
    global _LAST_DEPLOY_PENDING
    value, _LAST_DEPLOY_PENDING = _LAST_DEPLOY_PENDING, None
    return value


def _deployment_support_count(frame):
    """Count observed friendly support units, or return unknown for unclear layout."""
    import mobile_board as mb
    if frame is None or mb.board_transition_reason(frame):
        return None
    # The unique large HQ shield anchors the row. Its HP text is irrelevant to
    # a deployment count; low-confidence red HP must not erase clear geometry.
    # This grants no attack target or HP reading, whose stricter gate is intact.
    hq_shapes = []
    for card in mb._support_row_bright_cards(frame, "our"):
        shield, box = mb.hq_hp.find_shield(frame, card)
        if shield is not None and mb._hq_shield_geometry(card, box):
            hq_shapes.append(card)
    if len(hq_shapes) != 1:
        return None
    cards = mb.cards_from_stats(frame, field=(200, 425, 1120, 590))
    row = [c for c in cards if 425 <= c["y"] <= 470]
    if any(c["n_stats"] < 2 or mb.unit_combat_type(frame, {"card": c, "row": "support"}) == "unknown"
           for c in row):
        return None
    return len(row)


def _deployment_unit_gain(before_count, previous, current):
    """An ordinary deployment needs a persistent new unit on a stable support row."""
    import mobile_board as mb
    old = _deployment_support_count(previous)
    new = _deployment_support_count(current)
    stable = (mb.board_motion(previous, current) <= mb.BOARD_MOTION_MAX)
    confirmed = (before_count is not None and old is not None and new == old
                 and new > before_count and stable)
    return confirmed, {"before_support": before_count, "previous_support": old,
                       "after_support": new, "stable": stable}


def deploy_one_unit(frame=None, drop=DEPLOY_DROP, dry_run=False,
                    verify_px=25, settle=1.2, debug=True,
                    authorize=None, allow_attempt=None):
    """
    从手牌里挑一张**判成单位**的牌,拖到我方战线。返回 `(ok, detail)`。

    ★ **必须验证**:拖完再抓一帧,比对**手牌带**变了没有 ——
      这条链最危险的失败模式是"报告成功、其实什么都没干"(实测过:坐标用错空间,
      `move_drag` 返回 True、画面一动不动)。
    """
    global _LAST_DEPLOY_ATTEMPT, _LAST_DEPLOY_PENDING
    _LAST_DEPLOY_ATTEMPT = _LAST_DEPLOY_PENDING = None
    import time

    import numpy as np

    import actions
    import mobile_board as mb
    import platformapi

    p = platformapi.get()
    # A caller's frame is useful for a dry diagnostic, never authority for touch.
    before = frame if dry_run and frame is not None else p.capture_client(None)
    if before is None:
        _LAST_DEPLOY_PENDING = "部署前抓不到新帧"
        return False, "抓不到帧"
    permitted = authorize or (lambda f: mb.end_turn_state(f) in ("white", "orange"))
    reason = mb.board_transition_reason(before)
    if reason or (not dry_run and not permitted(before)):
        _LAST_DEPLOY_PENDING = reason or "新帧未确认我方回合"
        return False, _LAST_DEPLOY_PENDING
    zone = _zone_for(before, None)
    units = find_hand(before, zone=zone, units_only=True, debug=debug)
    if not units:
        orange = find_hand(before, zone=zone, debug=False)
        # ★ 这一支也要存帧:用户马上要开一局"手上带着那张指令"的对局,
        #   而**判对了(不拖)的那一次同样需要留下那一帧** —— 否则手上只有
        #   "判错时"的帧,没法对照。只在**有橙色候选但一张单位都没有**时存,
        #   免得每个空回合都写一堆。
        if orange:
            dump_deploy("nounit", before,
                        note=f"橙色可下 {len(orange)} 张,单位 0 张 -> 拒绝拖")
        return False, (f"没有可拖的单位(橙色可下 {len(orange)} 张,其中单位 0 张)"
                       f" -> **不拖**;宁可过牌也不冒险拖指令")
    if not dry_run:
        time.sleep(mb.BOARD_SAMPLE_GAP)
        current = p.capture_client(None)
        if current is None:
            _LAST_DEPLOY_PENDING = "部署前抓不到第二张新帧"
            return False, _LAST_DEPLOY_PENDING
        reason = mb.board_transition_reason(current)
        a = cv2.GaussianBlur(before[560:720, 200:1100], (3, 3), 0)
        b = cv2.GaussianBlur(current[560:720, 200:1100], (3, 3), 0)
        hand_motion = float((cv2.absdiff(a, b).max(axis=2) > 18).mean())
        if (reason or not permitted(current) or hand_motion > 0.025 or
                mb.board_motion(before, current) > mb.BOARD_MOTION_MAX):
            _LAST_DEPLOY_PENDING = reason or "部署前回合或手牌/战场尚未稳定"
            return False, _LAST_DEPLOY_PENDING
        before = current
        units = find_hand(before, zone=zone, units_only=True, debug=debug)
        if not units:
            _LAST_DEPLOY_PENDING = "第二张新帧没有可确认单位"
            return False, _LAST_DEPLOY_PENDING
    if allow_attempt is not None:
        units = [b for b in units if allow_attempt(before, b, drop)]
        if not units:
            _LAST_DEPLOY_PENDING = "部署失败预算已用尽，等待人工处理"
            return False, _LAST_DEPLOY_PENDING
    tgt = units[0]
    gx, gy = grab_point(tgt)
    sx0, sy0 = p.client_to_screen(None, gx, gy)
    sx1, sy1 = p.client_to_screen(None, *drop)
    if debug:
        print(f"  拖第 1 张:客户区 ({gx},{gy}) -> 屏幕 ({sx0},{sy0});"
              f"落点 客户区 {drop} -> 屏幕 ({sx1},{sy1})")
    if dry_run:
        return False, "dry-run:只算了坐标,没真的拖"
    # ★ 拖之前先把证据落盘(见 `dump_deploy` 那段说明)——
    #   顺序很重要:**先存 before,再拖**;拖完再补 after。
    d = dump_deploy("deploy", before, note=f"chosen={grab_point(tgt)} drop={drop}")
    if d and debug:
        print(f"  存帧 -> {d}")
    _LAST_DEPLOY_ATTEMPT = {"before": before, "after": None, "badge": dict(tgt),
                            "target": tuple(drop), "input_sent": True}
    before_support = _deployment_support_count(before)
    _LAST_DEPLOY_ATTEMPT["before_support"] = before_support
    actions.move_drag(sx0, sy0, sx1, sy1)
    time.sleep(settle)
    after = p.capture_client(None)
    _LAST_DEPLOY_ATTEMPT["after"] = after
    if after is None:
        _LAST_DEPLOY_PENDING = "部署已输入但无法验证结果"
        return False, "拖完抓不到帧 —— 无法验证"
    y0, y1, x0, x1 = DEPLOY_VERIFY
    diff = float((np.abs(after[y0:y1, x0:x1].astype(int)
                         - before[y0:y1, x0:x1].astype(int)).max(axis=2)
                  > verify_px).mean())
    hand_changed = diff > 0.02

    # ★★★ 2026-09-18(实机抓到的一次真漏判,用户当场看出来的):
    #   引擎把**一条指令**当成单位拖了出去 —— 那条指令的效果是"从三张单位里选一个",
    #   于是画面**停在了一个选择框上**,`classify` 认不出(None),引擎**卡住了**。
    #   而当时**"手牌变了"这条验证是通过的**(手牌确实少了一张) ——
    #   ⇒ 光看手牌**分不出**"部署了一个单位"和"打出了一条指令"。
    #
    #   补的第二道验证:**打完这一下之后,画面必须还是 `in_game`**。
    #     正常的单位部署 -> 画面还是对局(in_game);
    #     打出指令弹选择框 -> `classify` 变成别的/None -> **当场判定"不是普通部署"**。
    #   ★ 这道验证**救不回已经打出去的牌**,但能让引擎**当场发现自己判断错了**
    #     (而不是接着往下拖第二张、第三张)。
    state_after = ""
    try:
        import ui_state
        meta, _note = ui_state.load_platform_meta(
            getattr(p, "name", "") or "")
        st, _m = ui_state.classify(after, ui_state.load_templates(meta),
                                   ui_state.load_states(os.path.join(
                                       PROJECT_ROOT, "config", "states.json")))
        state_after = st or "None"
    except Exception as e:                      # noqa: BLE001
        state_after = f"分类失败({type(e).__name__})"

    # ★★★ 2026-09-19(实机**第二次**踩到,用户当场报的"又把非洲军团打出去了"):
    #   那一次拖完 **1.2s** 抓的这一帧画面**还是对局**,于是老代码判成"部署成功";
    #   而"三选一"选择框是**再晚一点**才弹出来的(存帧 `shots/android/hand/live_stuck.png`,
    #   那一局在那张选择框上**卡了 13 分钟**,直到人工点掉)。
    #   ⇒ 光看"拖完那一帧"**不够** —— 指令的特效/选择框会晚一两秒才出现。
    #   加一道**晚看**:再等 `LATE_STATE_WAIT` 秒抓一帧,那时已经不是对局 ->
    #   把这一发改判成"不是普通部署"(这道验证**救不回已经打出去的牌**,
    #   但能让引擎**当场知道自己判错了**,而不是接着拖第二张)。
    late_state = ""
    if hand_changed and state_after == "in_game":
        try:
            time.sleep(LATE_STATE_WAIT)
            late = p.capture_client(None)
            if late is not None:
                import ui_state as _us
                meta2, _n2 = _us.load_platform_meta(getattr(p, "name", "") or "")
                lst, _m2 = _us.classify(late, _us.load_templates(meta2),
                                        _us.load_states(os.path.join(
                                            PROJECT_ROOT, "config", "states.json")))
                late_state = lst or "None"
                after = late
            else:
                late_state = "晚看抓不到帧"
        except Exception as e:                  # noqa: BLE001
            late_state = f"晚看失败({type(e).__name__})"

    if hand_changed and state_after == "in_game" and late_state == "in_game":
        # A consumed order can change the hand and remain in_game. Observe a
        # real additional support unit on two stable frames before calling this
        # a unit deployment. The late frame starts this bounded confirmation.
        confirmed, evidence = False, {"before_support": before_support}
        previous = after
        for _ in range(3):
            time.sleep(max(mb.BOARD_SAMPLE_GAP, 0.5))
            current = p.capture_client(None)
            if current is None:
                break
            after = current
            if not permitted(current):
                break
            confirmed, evidence = _deployment_unit_gain(before_support, previous, current)
            if confirmed:
                break
            previous = current
        _LAST_DEPLOY_ATTEMPT["unit_gain"] = evidence
        if confirmed:
            verdict = True, (f"手牌带变化 {diff * 100:.1f}%,连续稳定帧我方支援单位 "
                             f"{before_support}->{evidence['after_support']} -> **部署成功**")
        else:
            verdict = False, (f"手牌带变化 {diff * 100:.1f}%,但未确认稳定新增我方支援单位"
                              f"({evidence}) -> 部署未确认")
    elif hand_changed and late_state not in ("", "in_game"):
        verdict = False, (f"手牌带变化 {diff * 100:.1f}%,但**{LATE_STATE_WAIT:.0f}s 后画面"
                          f"变成了 {late_state}** -> 这不是普通部署(很可能打出的是一条"
                          f"**指令**,例如『从三张单位里选一个』那种);引擎应当停下,"
                          f"别接着拖")
    elif hand_changed:
        verdict = False, (f"手牌带变化 {diff * 100:.1f}%,但**画面变成了 {state_after}**"
                          f" -> 这不是普通部署(很可能打出的是一条**指令**);"
                          f"引擎应当停下,别接着拖")
    else:
        verdict = False, (f"手牌带变化 {diff * 100:.1f}% -> "
                          f"**没拖成**(卡还在手上,别当成功)")
    # ★ 把 after 和结论**补进同一个目录**(和 before 配套,别另开一个文件夹)
    _LAST_DEPLOY_ATTEMPT["after"] = after
    if not verdict[0]:
        _LAST_DEPLOY_PENDING = verdict[1]
    dump_after(d, after, verdict[1], state_after, diff)
    # ★ 录像:把"动作刚做完那一刻"的帧交上去(没开录像时是空操作)。
    #   为什么在这里:只有**做动作的人**知道"我刚做完、现在这一帧就是结果"——
    #   等 `think()` 返回之后再抓,画面早就不是这一步的了(见 mobile_trace 文件头)。
    try:
        import mobile_trace
        mobile_trace.report_after(after)
    except Exception:                            # noqa: BLE001
        pass
    return verdict


def dump_after(d: str, after, verdict: str, state_after: str = "",
               diff: float = 0.0) -> None:
    """把拖完那一帧和结论补进 `dump_deploy` 建的那个目录(失败不影响出牌)。"""
    if not d:
        return
    try:
        _w(os.path.join(d, "after.png"), after, "after.png")
        with open(os.path.join(d, "decision.txt"), "a", encoding="utf-8") as f:
            f.write(f"\nafter.png = 拖完之后那一帧\n")
            f.write(f"画面状态 classify -> {state_after}\n")
            f.write(f"手牌带变化率 = {diff * 100:.1f}%\n")
            f.write(f"结论 = {verdict}\n")
    except Exception as e:                       # noqa: BLE001
        try:
            print(f"  [存帧] 补 after 失败(不影响出牌):{type(e).__name__}: {e}")
        except Exception:                        # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load(path, to_client=True):
    """
    读一帧。★ **只把设备分辨率的帧缩到 1280x720** —— 已经是手牌小图的那种
    (用户的截图、裁出来的 ROI)一律**原样读**。
    ★ 踩过:上一版写成"宽 != 1280 就 resize 到 1280x720",于是用户那 4 张手牌截图
      (752x118 之类)被**横向拉成 1280x720** —— 数字被揉烂,检测当然一个都找不到。
      而当时的日志只写"能打 0 张",**不报错**。⇒ 这类"输入被悄悄改掉"的错,
      只能靠**每次都把 overlay 画出来看**发现。
    """
    img = imread_u(path)
    if img is None:
        return None
    if to_client and img.shape[1] > 1280:
        img = cv2.resize(img, (1280, 720), interpolation=cv2.INTER_AREA)
    return img


def _zone_for(img, zone):
    """小图(非 1280 宽的裁图)没有"客户区"可言 -> 整张就是搜索区。"""
    if zone is not None:
        return zone
    if img.shape[1] != 1280:
        return (0, 0, img.shape[1], img.shape[0])
    return hand_zone()


def _capture_live():
    import platformapi
    p = platformapi.get()
    print(f"平台 {p.name} 抓一帧 ...")
    img = p.capture_client(None)
    if img is None:
        print("抓不到帧:", getattr(p, "error", "?"))
        raise SystemExit(1)
    return img


if __name__ == "__main__":
    import argparse

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(
        description="手机端手牌:**这一回合哪几张牌能打**(判据 = 费用数字橙色/灰色)")
    ap.add_argument("--frame", default="", help="对某一张存帧跑,并画出 overlay")
    ap.add_argument("--live", action="store_true", help="从设备现抓一帧再跑")
    ap.add_argument("--out", default="", help="overlay 存到哪")
    ap.add_argument("--want", default="orange", choices=["orange", "grey", "any"])
    ap.add_argument("--units-only", action="store_true",
                    help="只留判成『单位』的(引擎要拖牌时必须开)")
    ap.add_argument("--selftest", action="store_true",
                    help="在存帧上跑一遍(每张都画 overlay,要自己打开看)")
    ap.add_argument("--try-deploy", action="store_true",
                    help="★ 真机:挑一张判成『单位』的手牌拖到我方战线,并**验证手牌变了没有**")
    ap.add_argument("--dry-run", action="store_true", help="只算坐标,不真的拖")
    args = ap.parse_args()

    if args.try_deploy:
        ok, detail = deploy_one_unit(dry_run=args.dry_run)
        print(("★ 成功:" if ok else "★ 没成:") + detail)
        raise SystemExit(0 if ok else 1)

    if args.frame or args.live:
        out = args.out or os.path.join(
            PROJECT_ROOT, "shots", "android", "probe",
            "handplay_" + (os.path.basename(args.frame) if args.frame else "live.png"))
        if args.live:
            img = _capture_live()
        else:
            img = _load(args.frame)
            if img is None:
                print("读不到", args.frame)
                raise SystemExit(1)
        zone = _zone_for(img, None)
        cards = find_hand(img, zone=zone, want=args.want, debug=True)
        units = [b for b in cards if b["kind"] == "unit"]
        print(f"橙色可下 {len(cards)} 张;其中判成**单位** {len(units)} 张"
              f"(指令 {sum(1 for b in cards if b['kind'] == 'order')} / "
              f"拿不准 {sum(1 for b in cards if b['kind'] == 'unknown')})")
        print(f"能拖的抓取点 {[grab_point(b) for b in units]}")
        debug_overlay(img, cards, out, zone=zone,
                      band=hand_box() if img.shape[1] == 1280 else None)
        print("★ 打开图看一眼:", out, "(绿=单位 红=指令/拿不准)")
        raise SystemExit(0)

    if args.selftest:
        #: (帧, 我方费用, 期望"橙色的"张数, 期望"单位"的张数)
        #: ★ 期望值是**我一张张打开 overlay 数出来的**,不是检测自己报的。
        #: ★ 期望写 None 的 = **取证用**(用户的截图 / 早期帧):数过但没有可核对的
        #:   第二来源,所以**不当结论**,只打印数量。
        #: ★★ 2026-09-19 更正一条**写错过的期望**:`hand_n9` 原来写"单位 4",
        #:   而把那张图放大一张张看过(`shots/android/probe/_n9_mid.png`)之后是
        #:   **6 个单位 + 1 个指令**(第 4 张徽章只有 `2 K`、没有名字条 = 指令)。
        #:   ⇒ 老期望是错的,当时的"✗单位"是**用例在冤枉代码**。这一条要记住:
        #:     期望值也要有第二来源(放大图),不能凭印象写。
        CASES = [
            ("shots/android/hand/live_k3_6cards.png", 3, 5, 3),
            ("shots/android/hand/hand_n6.png", None, 5, 3),
            ("shots/android/hand/hand_n7.png", None, 0, 0),
            ("shots/android/hand/hand_n8.png", None, None, None),
            ("shots/android/hand/hand_n9.png", None, 7, 6),
            ("shots/android/hand/live_hand_now.png", None, 2, 0),
            ("shots/android/ingame/f0.png", 1, None, None),
            ("shots/android/ingame/f1.png", None, None, None),
            ("shots/android/ingame/f2.png", None, None, None),
            ("shots/android/ingame/f3.png", 2, None, None),
            ("shots/android/ingame/f4.png", None, None, None),
            ("shots/android/ingame/f5.png", None, None, None),
        ]
        print(f"搜索区 = {hand_zone()}  手牌带 = {hand_box()}  "
              f"窗口 = {DIGIT_WIN}  色域 = {ANCHOR_HUE}+S{ANCHOR_S_MIN}+V{ANCHOR_V_MIN}")
        print(f"主判据 = 徽章底板右下角的**攻/防小数字**"
              f"(亮 >= 底色25分位+{AD_INK_LIFT}, 面积 {AD_MIN_AREA}~{AD_MAX_AREA});"
              f" 辅助 名条 lines / bar_dark\n")
        bad = 0
        for rel, kred, want_o, want_u in CASES:
            p = os.path.join(PROJECT_ROOT, rel)
            img = _load(p)
            if img is None:
                print(f"  {os.path.basename(rel):22s} 读不到")
                continue
            zone = _zone_for(img, None)
            cards = find_hand(img, zone=zone)
            units = [b for b in cards if b["kind"] == "unit"]
            out = os.path.join(PROJECT_ROOT, "shots", "android", "probe",
                               "handplay_" + os.path.basename(rel))
            debug_overlay(img, cards, out, zone=zone,
                          band=hand_box() if img.shape[1] == 1280 else None,
                          note=f"(kredits={kred})")
            marks = []
            for got, want, what in ((len(cards), want_o, "橙"), (len(units), want_u, "单位")):
                marks.append("" if want is None else ("OK " if got == want else f"✗{what}"))
                if want is not None and got != want:
                    bad += 1
            kinds = "".join({"unit": "U", "order": "O"}.get(b["kind"], "?") for b in cards)
            ads = "".join("Y" if b["ad"] else "n" for b in cards)
            print(f"  {os.path.basename(rel):22s} {''.join(marks):8s}"
                  f"费用={str(kred):>4s} -> 橙 {len(cards):2d} / 单位 {len(units):2d}"
                  f"  [{kinds}] ad[{ads}]  x={[b['cx'] for b in units]}")
        print()
        print("★ overlay 都写在 shots/android/probe/handplay_*.png —— **必须打开看**。")
        print("★ 没标期望值的那几张:期望值没有第二来源可核对,只打印数量,不当结论。")
        print("★ `live_hand_now.png` 是真机 9 张那局现抓的:**只有 2 张能下、两张都是指令**")
        print("   (用户当场确认)—— 所以期望是 橙 2 / 单位 0。")
        print("★★ `ingame/f0..f5` 上「橙=能下」有个**没查清的反例**,见文件头那一节 ——")
        print("   所以 `find_hand()` 的返回只能当**候选**,引擎拖完必须**验证手牌变了没有**。")
        print("★ 全部对上" if not bad else f"★ {bad} 条对不上")
        raise SystemExit(1 if bad else 0)

    ap.print_help()
