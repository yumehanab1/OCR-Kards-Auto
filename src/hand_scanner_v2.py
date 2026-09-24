"""
hand_scanner_v2.py - hover-diff hand scanner (M3, working version).

Per hand-card probe:
  1. mouse -> SAFE point, capture baseline
  2. mouse -> probe x on hand fan, hold, capture hover
  3. diff baseline vs hover -> hover panel bbox only
  4. inside bbox: type-icon template match + cost OCR

On-field units are present in BOTH captures so they cancel out of the diff.
"""

from __future__ import annotations

import json
import os
import re
import time

import cv2
import numpy as np

from actions import cursor_moved_from, set_cursor, set_cursor_checked
from card_match import (DATA_JSON, CardHashDB, card_by_name,
                        crop_card_name_band, dhash, hash_to_hex,
                        load_db as load_card_db, match_name, read_cost_badge)
from hover_card_reader import _ocr
import orders                     # 指令卡"能不能打"的唯一来源(见 orders.playable)
from ui_state import match_one
from win import capture_client_bgr, client_to_screen

# ---- calibrate ----
SAFE_POINT = (1270, 360)   # screen middle far right - no hover panel
PROBE_Y = 700              # hand fan hover y
X0, X1 = 340, 920
STEP = 12
HOLD = 0.30                # 悬停后等面板出现(原 0.4,实测 0.3 够)
SAFE_SETTLE = 0.20         # 回安全点后等上个面板消失(原 0.35)
DIFF_THRESH = 25
MIN_DIFF_PX = 3000

# 相邻探针判定"还是同一张卡"的阈值:面板 bbox 重叠度足够高就复用上次的
# 识别结果,省掉一次 ~1.5s 的 OCR。一张牌的热区通常覆盖 4-6 个探针,
# 这是扫描耗时的大头(实测 5 张牌 121s,其中约 37s 花在重复 OCR 上)。
PANEL_IOU_SAME = 0.55

# 单张手牌在扇形里的间距(px)。用于把"同名牌挨在一起、热区连成一片"的段
# 展开成正确的张数。实测相邻牌中心间距约 60px。
CARD_PITCH = 60

# 单张牌悬停热区的跨度上限:同一个热区里相邻探针最多差这么多,
# 超过就说明换了一张牌,不能再复用上一次的识别结果。
#
# ★ 实测标定:同一张卡的热区约 72px 宽、探针步长 12 -> 相邻探针只差 12-24px;
#   而布局表里**相邻两张牌**的探针间距是 35-70px(6 张牌那档最小 35px)。
#   所以这个上限必须**小于 35**,否则会把相邻的牌并成一张 ——
#   原来写 90 太宽,实测把探针 493 和 559(差 66)判成了同一张。
MAX_SAME_SPAN = 30

# scan_fast 用:测到的左边缘与校准表里的值最多允许差这么多像素。
# 实测左边缘本身有 ±10px 波动(同一副 5 张牌,采集时 421、后来 430),
# 所以容差必须够大;而相邻张数的最小间距是 11px(7↔8 张)与 1px(8↔9 张),
# 单靠边缘区分不了,所以容差内允许有多个候选,由命中率来定谁对。
LAYOUT_EDGE_TOL = 22
# ★★★ 2026-09-13(第十个会话):**右边缘也要用上**(A/B 开关)。
#
# 为什么:`config/hand_layout.json` 里每条布局都记了**两个**边缘
# (`left_edge` / `right_edge`),而选条目时**只用左边缘**(容差内取最近)。
# 实测(`src/edge_probe.py --frame shots/hand_live/base.png`):
#   · 扇形是**居中**的(9 条的 center 全在 636.5~654.0,极差 17.5px)
#     ⇒ 两个边缘是**同一个张数的两次独立测量**;
#   · 于是"两边都解释得通"是一条硬得多的判据:只解释一边的条目多半是错的
#     (实测 6 张那一帧:6 张条目 残差 L0/R18;5 张条目 L31/R8 但左边缘过不了闸;
#      7 张条目 L22/R47 —— 只有 6 张那条**两边都对得上**)。
#   · 宽度还能分开"左边缘几乎一样"的 8 张 / 9 张(357/925 vs 358/915)。
# ★ 安全约定(和别处一样 fail-open):
#   ① 右边缘**只在宽度看起来合理**时才参与;测量明显坏掉(实测背景参考区被
#      污染时会给出 R=1099)就退回"只看左边缘"的老规则;
#   ② **左边缘的闸不放宽** —— 两边都过闸的条目优先,没有这样的条目时,
#      仍然在老候选里按左边缘残差选(行为与改之前一致,不会更差)。
LAYOUT_RIGHT_TOL = 22
LAYOUT_MATCH_BOTH_EDGES = True
# 合理的扇形宽度(R-L)。实测 1~9 张是 165~568;给足余量,只用来挡"测量坏掉"。
LAYOUT_WIDTH_SANE = (110, 700)

# ★★★ 2026-09-13 深夜(实机 + 逐像素核对,用户当场观察到的现象):
#   **左边缘可能"量短了" —— 把最左边那张牌整个漏掉。**
#
# 实机那一帧(`shots/scan_frames/0913_205627_scan.png`)逐像素核对过:
#   · 手牌**真是 8 张**:最左那张(铁锤/指令)左边缘 357、扇形右边缘 ~925,
#     正好是布局表「8 张」那条(357/925);
#   · `detect_left_edge` 量到 **416** —— 最左那张牌与桌面的色差被它自己的
#     卡面花纹切成 **6 / 13 / 14px 三段**(有一列只到 41.0,阈值是 45),
#     三段都不到 `MIN_FAN_RUN_W=40` 于是被跳过,第一个"够宽"的段(416 =
#     **第 2 张**牌的左边缘)被当成了扇形左边缘;
#   · 右边缘 926 与表里 8 张的 925 **只差 1px**,但它以前只能"排序"不能"救人"。
# 后果(用户 2026-09-13 当场观察到的):探针按「5 张」的间距铺 -> 只落在
#   第 2/4/6/8 张上,**最左那张铁锤整局一次都没被识别**,KV-1 整局只被认到一次,
#   第 11 回合"跳着识别、认到的全是指令",38t/Bf 109 都因此没出。
#
# 判据(**窄而明确**,用的是检测器**自己**报出来的跳过段):
#   被跳过的窄段里,有就贴在选中边缘左边 `SUSPECT_GAP`(一个卡距)以内的吗?
#   有 -> 那个边缘多半是"第 2 张"的左边缘 -> **改用右边缘挑条目**。
# ★ 只在"宽度合理"时启用(背景被污染时右边缘会给出 R=1099 这种坏值);
# ★ 这一条**不动那些左边缘量得好好的帧**(实测 60 帧里只有 15 帧命中这个签名)。
LAYOUT_TRUST_RIGHT_IF_LEFT_SUSPECT = True
SUSPECT_GAP = 60          # 跳过段离选中边缘多近才算"量短了"(≈一个卡距)
# ★★ 固定装饰的禁区:左下角"手枪装饰 + 玩家名"在 **x277..313** 制造两段 16/18px
#    的亮区(§7 第 2/3 条那个老坑)。它就在扇形左边不远处,所以判"左边缘量短了"
#    的时候必须把它排除掉,否则**左边缘本来就对**的帧也会被误判成可疑
#    (2026-09-13 深夜实机就误判过一次:左边缘 358 是对的,却因为 277/294 两段
#     装饰在 60px 内,改去信了右边缘 —— 而那一帧的右边缘恰好也量短了)。
FAN_X_MIN = 340           # 扇形左边缘不可能小于这个值(实测 1~9 张是 357~570)

# ★★★ 2026-09-21(用户实机日志之后):**"张数分不清"就别分 —— 探针取并集 + 两端各补一格**。
#
# 为什么上面那条 `LAYOUT_TRUST_RIGHT_IF_LEFT_SUSPECT` 只救了一半:
#   表里 7/8/9 三条条目的边缘**彼此几乎一样**(左 368/357/358,右 915/925/915),
#   而容差是 22 —— 三条**都能过闸**;连"命中率"也分不出来(每根探针都落在某张牌的
#   热区里,选错的条目照样接近 100% 命中,见第 62~63 行"单靠边缘区分不了")。
#   ⇒ "挑哪条"这一步**本质上还是在猜**;一旦猜小一档,就重演第 96~99 行那个后果
#     (探针按「5 张」的间距铺 -> 只落在第 2/4/6/8 张上,最左那张整局没被识别过)。
#
# 实机证据(2026-09-20 另一台机器那一局,复核见 本机副本 `docs/reports/` 下的实机报告):
#   23:41:34 `布局「7 张」(表内左 368,量到 L433/R919;选中那条残差 L65/R4;
#             7 探针;容差内还有 [9, 8])` —— 量到的左边缘 433 比 7/8 两条都偏右
#             65~76px(最左那张牌被卡纹切碎),选中 7 张、探针铺在 405..821;
#   23:42:06 同一副牌又变成 `布局「5 张」(量到 L414/R812;容差内还有 [])`。
#   ⇒ **同一局里引擎对"几张"给过 5 / 7 / 8 三个答案。**
#
# 判据(窄而明确):**容差内不止一条候选**时按"并集"铺探针 —— 不管真实张数是 7 还是 8,
#   每张牌至少有一根探针落在它身上;再按选中那条的间距往两端各补一格,
#   兜住"边缘量短、最边那张整张没被覆盖"。
# ★ A/B:`LAYOUT_PROBE_UNION = False` 一键退回"只用选中那条的探针"(老行为)。
# ★ 代价:多几根探针(每根 ~0.6s 固定等待),**只在有歧义时才付**(唯一候选时不加)。
LAYOUT_PROBE_UNION = True
#: 两根探针近于这个距离就合成一根。
#:
#: ★★★ 2026-09-21 深夜(用户:*"这一局跑下来光扫卡扫了好久"*)—— **从 15 提到 35**。
#:   为什么必须提(判据可离线复算,见 `dev\_probe_dedup_eval.py`):
#:   15 这个数**比噪声下限还小**,等于没去重。7/8/9 三条布局在同一张牌上的针距差是
#:   **逐张递增**的(实测):
#:       `7 张 vs 8 张`: 17  23  27  34  40  46  77
#:       `7 张 vs 9 张`: 16  29  47  57  71  91 131
#:   而 15 只能吃掉 8/9 两条里最靠左那两根 -> 那次实机 24 根并集只去了 8 根,
#:   **实走 14 根读 7 张牌,每张读两遍,第一次扫描花了 27.2 秒**(日志原文)。
#:   ⇒ 提到 35:同样这三条并集 **24 根 -> 10 根**,次数直接砍掉一半多。
#:
#: ★★★ 但**这不是干净的修法,必须如实记下来**(别再以为它"修好了"):
#:   上界是量出来的 —— 所有布局里**最小的相邻针距 = 46px**(count=9 那条),
#:   所以门槛必须 < 46,否则会把**同一条布局里的两张真牌并成一张**
#:   (我上一次就是栽在这:当时把门槛按"卡距"算,结果把 7 张并成 4 张)。
#:   而"同一张牌的偏移"最大到 **131px**,**比 46 还大** —— 两个区间**重叠**,
#:   所以**不存在任何固定门槛**能同时做对"合并同一张"和"不并相邻两张"。
#:   35 只是"在不并错的前提下尽量多去"的那个折中,它**消不掉全部浪费**。
#:   ⇒ 真正的修法是**按牌的身份对齐**(用每条布局的 `left_edge` 把探针归一到
#:     同一套牌位),不是按裸坐标去重。那件事要拿真实手牌帧逐张标定卡片中心
#:     才能定判据(§7:合成用例全绿 ≠ 能用),所以**留在下一轮**,这里只先止血。
#:   ★ A/B 回退:把这个数改回 15 就退回老行为。
LAYOUT_PROBE_UNION_DEDUP_PX = 35
LAYOUT_PROBE_EXTRA_ENDS = True     # 两端各往外补一格(按选中那条的间距)
LAYOUT_PROBE_X_MAX = 1000          # 再往右就是右侧那块鹰徽面板/按钮,不探

# ★★★ 2026-09-21(同一天,继续上一段):**张数本身也要读准,不能继续拿 `cands[0]["count"]` 猜**。
#
# 上一段只解决了"别把牌漏掉"(并集 + 两端补探),`self.last_hand_count` 仍然是
# "选中那条布局表条目说的张数" —— 也就是**那个已经被证明会猜错的量**。它的下游是
# `turn_engine._memory_note_scan` -> `hand_memory.note_scan(probed, count)`:
# 张数一错,记忆当场失效,而且**每一次扫描都再错一次**(实机日志里成串的
# `[记忆] 失效:张数对不上(记忆 7 张,现在读到 5 张)`)。
#
# 判据(**窄而明确**,不引入任何新的不确定量):既然 `probes` 里**下标 >= 0 的一定是
# 选中那条自己的探针**(`_probes_for` 只给并集/两端补出来的发 -1),那么:
#   实读张数 = 选中那条的 count + "**落在它『够得着』的范围之外、且真读到牌**的位置的个数"
#              (上限 `LAYOUT_COUNT_MAX_BUMP`)
#   其中"够得着" = `[base[0] - MAX_SAME_SPAN, base[-1] + MAX_SAME_SPAN]` ——
#   选中那条自己的探针铺在 base[0]..base[-1],再往两边各让一个热区半宽。
#
# 为什么门槛要**同时**满足"出界"和"出界超过一个 `MAX_SAME_SPAN`"(两条都是踩出来的):
#   · 只看"落在两端之外":实测同一根探针本来就能读到**相邻卡**的一块
#     (`MAX_SAME_SPAN` 就是为这条标定的),所以"刚出界一点点"完全可能是选中那条
#     **本来就该探到**的那张牌 —— 23:41:34 那帧(7 张,选对了)左端 x405 只出界 7px,
#     照"出界即多"会数成 8 > 真值 7,**比不改更坏**。
#   · 只看"离最近那根探针远不远":并集铺的是两套间距,某根 -1 针本来就会落在两条带的
#     交界处 —— 23:43:17 那帧(9 张)x777 离最近那根 base 针 744 有 36px,照"离得远就算多"
#     会数成 10 > 真值 9。落在带子里面的命中,不管离某根针多远,都在它覆盖到的那几张牌上。
#
# ★ 实机四帧都核算过(几何全部来自 `config/hand_layout.json` + 日志里量到的 L/R,
#   离线可复现:见 `dev/hand_count_test.py` 第 ⑥ 段):
#   23:41:34 选中 7、真值 7 -> 一格不动 ✓(对照组)
#   23:41:58 选中 5、真值 8 -> 6(只补回一格,**仍少 2**,见下面那条"够不着")
#   23:43:17 选中 8、真值 9 -> 9 ✓(右端补出来的 x890 真的落在第 9 张上)
#   23:43:10 选中 8、真值 9 -> 9 ✓
#   ★ 四帧里没有一帧被改成"大于真值" —— 这是最硬的一条:猜多比不改更坏(会把记忆带偏)。
#
# ★ 判据只用**两处**已有的量,没有新标定值:`MAX_SAME_SPAN`(热区半宽,见第 51~58 行)
#   和布局表自己的 `probes`。
#
# ★ 已知够不着、也**不假装够得着**:补出来的探针只往外伸**一格**,所以当 `cands[0]`
#   比真值小 2 张以上时,外面那一格只能证明"至少还多一张",补不回全部 ——
#   23:41:58 那帧就是实例(表里当 5 张用、真值 8 张,而且它的第一根探针 x455 已经
#   落在第 2 张牌上,第 1 张整张没被覆盖)。再往外属于**没探过**的地方,
#   按项目纪律不许猜(宁可按最小值报,不许猜多)。
# ★ 另一头(**只准加、不准减**)的理由:不加时误差最多就是"真值 - base",不会更坏;
#   而"减"要拿"某一根探针没弹面板"当"那里没牌" —— 面板不弹的已知原因一大把
#   (牌缝、卡纹切碎、悬停没稳定、`diff_bbox` 阈值),没有一条能证明"没牌"。fail-closed。
LAYOUT_COUNT_FROM_PROBES = True
#: 最多往上提几档。取 2 = "并集探针最多能看到 base 覆盖之外的**两个**位置":
#: 两端补探各一个;再加上 `LAYOUT_PROBE_UNION` 里更大的那条候选自己的探针。
#: 一次只提一档是**有意的保守**:同一个位置可能被两根 -1 探针先后探到,不许当成两张牌。
LAYOUT_COUNT_MAX_BUMP = 2

# ★★★ 2026-09-13(第十个会话):**手牌记忆**(用户提的第三个优化)。
#   把上一轮/上一回合"探到过的牌"按【从左到右的次序】记住,下一轮**跳过**那些
#   已知"出不起 / 不是单位"的探针 —— 省下的是悬停(0.5s)+ 识别(1.4s)/个。
#   规则、风险与两条纪律都写在 `hand_memory.py` 的文档里;这里只有开关。
#   ★ A/B:`USE_HAND_MEMORY = False`(或 `main_loop --no-hand-memory`)一键退回
#     "每个探针都老实悬停"的老行为。
USE_HAND_MEMORY = True
# 最多试几个候选(每个约 3-10 秒),避免表不对时耗太久
MAX_CANDIDATES = 3
# 命中率到这个数就认定是它,不必再试其它候选
CANDIDATE_GOOD_RATE = 0.85
# 卡名只在【中线附近】找:悬停放大的卡在中部,卡名是大字;
# 底部手牌区(y 更大)全是小字残句,读它必然出错。实测手牌区从 y≈620 开始,
# 中线在 360,所以 550 这条线能把两者干净分开。
NAME_ZONE_MAX_Y = 550

# ★★ 2026-09-11 下午实机实测(新卡组,`shots/hoverdump/x0492_full.png`):
#   **指令(order)/ 反制(counter) 的卡名印在放大卡的【下方】**,不是中线那条带。
#   实测那张反制卡:名字 `复仇` 的 OCR 行是 **y=551 h=25 conf=0.58** ——
#   而 `NAME_ZONE_MAX_Y=550` 把它切在门外,**差 1 个像素**。
#   于是这类牌永远 `name=None -> cost=None`,引擎一辈子不出它(§7 第 35 条
#   那个"整局压着三张 order 打不出去"就是这么来的)。
#   修法:这两类牌把名字带放宽到 600 —— 手牌扇形的小字卡名实测在 y≈629
#   (「0%步兵第554团」),600 这条线仍然把它们挡在外面。
NAME_ZONE_MAX_Y_SPECIAL = 600
# 放宽的那一段(y≥540)同时把置信度门槛从 0.6 放到 0.5:实测 `复仇` 只有 0.58。
# ★ 只对"下方名字带 + 指令/反制"放开,不动中线那条带的老门槛。
NAME_BOTTOM_BAND_Y = 540
NAME_CONF_MIN = 0.6
NAME_CONF_MIN_BOTTOM = 0.5

# 指令(order)/ 反制(counter) 的卡名印在类型图标【下边】(用户 2026-09-11 指出),
# 所以第一遍没读出名时,再裁这么高的一条带补一次 OCR。
TYPE_NAME_BAND_H = 70

# ★★★ 2026-09-13(第九个会话):OCR / 模板匹配的【输入形状】才是真正的大头。
#
# 实测(`src/hand_timing.py`,真实悬停帧):
#   `_classify` 每张卡 ~2.0s = **OCR ~1.4s + 类型图标模板匹配 ~0.6s**
#   (旧档案说"图标匹配 0.001s/张"——那是**盘面上**那个 23x23 小牌子;
#    这里是在**整块悬停面板**上跑 7 个模板的 `cv2.matchTemplate`,完全是另一回事。)
#
# 再往下挖,OCR 的成本**只由长宽比决定**,不是由面积决定:
#   RapidOCR 的 detector 用 `limit_side_len=736 / limit_type=min`
#   —— 它把**短边放大到 736**,所以送进模型的像素数
#       = 736² × (长边 / 短边)。
#   实测(单测 detector 的纯耗时,已经排掉识别阶段的噪声):
#      550x1138 (1 : 2.07) -> 1.12M px -> 0.31s
#      550x550  (1 : 1.00) -> 0.54M px -> 0.135s   <- **方形就是下界**(再小也一样)
#      192x1138 (1 : 5.93) -> 3.21M px -> 0.97s    <- **"窄横带"是最坏的形状**
#   ★★ 这条是**反直觉的**,而且我一开始就猜错了:
#      "把卡名带裁窄"看着像优化,实测**反而慢 3 倍**(横带的长宽比更差)。
#      → 正解是把输入裁成**接近正方形**的窗口。
#
# 窗口的位置/大小来自实测语料(63 帧:diffdiag 悬停帧 + probe 悬停帧):
#   胜出的卡名行永远落在 screen x 392~863 / y 210~359;
#   类型图标最靠右到 x 812;指令/反制的"图标下方"名字带最下到 y≈575。
#   取 x∈[300,980] / y∈[0,600] —— 近正方形(680x600),而且把三条都包住。
# 两条安全约定:
#   ① 候选集**一个字都不改** —— 里面那套"按行高取最大的卡名"和
#      `NAME_ZONE_MAX_Y` / `special` 的裁剪规则原样保留,只是喂给它的图小了;
#   ② 窗口里**没认出【卡名】**时,自动退回**整块**再跑一遍那套老代码
#      (fail-open:宁可多花一次时间,绝不因为裁窗口而少认一张牌)。
#      ★ 判据是"只有卡名才算收获",**类型不算** —— 理由见 `_classify` 里那段注释
#        (第一版按"名字或类型"提前返回,用打偏的窗口一测:20 帧错 6 帧)。
NAME_OCR_X0, NAME_OCR_X1 = 300, 980
NAME_OCR_Y1 = NAME_ZONE_MAX_Y_SPECIAL          # 600,见上面两条名字带
# A/B 开关(§7 第 59/67 条的纪律):False = 退回"整块 diff bbox"的老行为
NAME_OCR_WINDOW = True

# 可部署的类型(单位)。和 turn_engine.DEPLOYABLE 一致;
# 放在这里是为了让 `_probe_layout_until` 能独立判断"这张能不能出"。
DEPLOYABLE_TYPES = {"infantry", "tank", "fighter", "bomber", "artillery"}


def is_playable(ctype, name: str = "") -> bool:
    """
    "这张牌允许被拖出去吗" —— **统一问 `orders.playable`**,不在这里自己拼名单。

    ★ 2026-09-20:以前这里只有"类型在 DEPLOYABLE_TYPES 里"一条,于是**指令卡
      在扫描阶段就被判成不可用** —— 惰性扫描会跳过它、继续往后扫,而引擎那边
      再怎么支持都没用(候选根本回不来)。这正是"判据分散在两处"的典型后果。
    """
    return orders.playable(ctype, name)

# 卡库路径统一由 card_match 解析(2026-09-19 起目录名是 card_db\,旧名字兜底)——
# 这里不再自己拼一份:两处各写一个路径,改目录名时必漏一处。
# 放大卡指纹库:卡名 OCR 读不出时用它认卡(见 card_match.CardHashDB)。
# 扫描时顺手学习"卡名读出来了"的那些指纹,越跑越准。
HASH_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "config", "card_hashes.json")


def _load_db():
    load_card_db(DATA_JSON)


def _same_identity(mem, info):
    """
    记忆里那张牌,和这一帧读到的是不是同一张。

    判据(从严到宽):
      ① 两边都读出了**卡名** -> 必须完全相同(卡名来自 OCR + 查库,最硬);
      ② **只有一边有名字** -> 名字那一侧的信息在另一边**根本不存在**,
         不是"它变了";这时退回比**类型**(+ 两边都有费用时的费用);
      ③ 都没有名字 -> 类型 + 费用**都**要相同。

    ★★★ 2026-09-13 深夜(**用户实测**)修的就是第 ② 条:
      以前"一边有名字一边没有"一律算不同,而**记忆里常常只读到类型**
      (探针只认出了类型图标、卡名 OCR 没出来),于是**每次校验点抽到这种条目
      都判失效 -> 整手重扫**。用户原话:"明明有手牌记忆的时候,隔一两回合就又
      把手牌从头扫到尾一次"。实机账(连跑三局):**命中 22 / 失效 16**,
      失效原因里满是 `校验点第 N 张读到 某某卡,记忆说 infantry(None)`。
      为什么放宽这一条是安全的:
        · 记忆那边**本来就没有名字可比** —— 拿"没读到"当"变了"是判据错位;
        · **真要出的那张永远会当帧确认**(见本模块文档的两条纪律),
          所以即使真漂移,也绝不会照着旧记忆去拖一个位置;
        · **两边都有名字**时第 ① 条一个字节都没放宽 —— 真正的漂移照样抓得到。
    ★ 宁可判"不同"(fail-closed:退回老实扫一遍,只是慢一点)那条原则仍然成立,
      只是不再把"没读到"当成"不同"。
    """
    if not mem or not info:
        return False
    mn, mt, mc = mem.get("name"), mem.get("type"), mem.get("cost")
    n, t, c = info.get("name"), info.get("type"), info.get("cost")
    if mn and n:
        return mn == n
    if mn or n:
        # ★ 只有一边有名字 -> 用**类型**(两边都读出来时)当判据;费用只在两边都有时比。
        if mt and t and mt == t:
            return mc is None or c is None or mc == c
        return False
    if mt is None or t is None:
        return False
    if mt != t:
        return False
    # ★★★ 2026-09-19(实机)**"两边费用都没读出来"不等于"它变了"**。
    #   旧写法是 `if mc is None or c is None ...: return False`,于是
    #   记忆里记着 tank(None)、这一帧又读到 tank(None) —— 身份明明**逐字相同**,
    #   却判"不同" -> 记忆当场作废 -> 整手从头重扫一遍。
    #   实机日志(`0919` 那一局)里那三行就是这么来的:
    #     `[记忆] 失效:校验点第 1 张读到 tank(None),记忆说 tank(None)`
    #     `[记忆] 失效:校验点第 3 张读到 infantry(None),记忆说 infantry(None)`
    #     `[记忆] 失效:校验点第 5 张读到 order(None),记忆说 order(None)`
    #   —— **读到什么和记忆说什么一字不差**,却报了失效,一眼就是判据错位。
    #   这和本函数文档第 ② 条要修的是同一类错:拿"没读到"当"变了"。
    #   放宽的边界:类型必须相同(唯一还剩的硬判据),两边**都有**费用时照样要比。
    if mc is None or c is None:
        return True
    return mc == c


def _match_name(t):
    """
    卡名匹配 —— 真正的规则在 card_match.match_name(可离线单测)。
    这里保留一个薄包装,老脚本(ocr_lines_debug.py 等)还在用这个名字。
    """
    return match_name(t)


def _card_by_name(name):
    return card_by_name(name)


def diff_bbox(a, b):
    if a is None or b is None or a.shape != b.shape:
        return None
    d = cv2.absdiff(a, b)
    gray = cv2.cvtColor(d, cv2.COLOR_BGR2GRAY)
    mask = (gray > DIFF_THRESH).astype(np.uint8)
    if mask.sum() < MIN_DIFF_PX:
        return None
    ys, xs = np.where(mask > 0)
    return (int(xs.min()), int(ys.min()), int(xs.max()) - int(xs.min()) + 1,
            int(ys.max()) - int(ys.min()) + 1)


class HandScannerV2:
    def __init__(self, hwnd, templates, safe=SAFE_POINT, y=PROBE_Y,
                 x0=X0, x1=X1, step=STEP, hold=HOLD):
        self.hwnd = hwnd
        self.templates = templates
        self.safe = safe
        self.y = y
        self.x0, self.x1, self.step = x0, x1, step
        self.hold = hold
        self.icon_names = [n for n in templates if n.endswith("_icon")]
        self.last_segments = []      # scan() 填:原始"连续同卡段",便于离线重算
        self._last_cursor = None     # 脚本上次设置的屏幕坐标(用于让行判断)
        # ★ 上一次扫描"为什么是这个结果"。
        #   实测踩过的坑:日志里只有 `hand scan #10: 0 cards in 0.8s ->` ——
        #   0.8 秒说明根本没真扫,但**完全看不出倒在哪一条回退分支上**
        #   (没布局表 / 测不到左边缘 / 边缘超容差 / 命中率太低 / 用户中止)。
        #   所以每条早退路径都往这里写一句人话,由调用方打进日志。
        self.last_reason = None
        # ★ 2026-09-13:最近一次扫描匹配到的**手牌张数**(布局表里那个 `count`)。
        #   唯一用途是让引擎知道"手牌多不多"(用户要求:手牌多时不必把费用用完,
        #   见 `turn_engine.BIG_HAND_*`)。★ **不用额外扫一次手牌** ——
        #   惰性扫描本来就要测左边缘查布局表,顺手记下来而已。
        #   拿不到就是 None,调用方按"不知道"处理。
        self.last_hand_count = None
        # ★★ 2026-09-13(第十个会话):诊断用 —— "这次用了哪条布局"(见 find_playable)
        #   和"每个探针到底读到了什么"。日志里以前只有结论,判错和判对长得一样。
        self.last_layout = None
        self.last_probe_seen = []
        # ★★★ 2026-09-21:最近一次"张数按实读修正"那行日志(没有修正就是 None)。
        #   为什么要单独存一份:修正行写进 `last_reason` 之后**立刻会被**后面那句
        #   `惰性扫描:布局「N 张」…全扫完` 覆盖,不留一份就等于没写(见
        #   `_count_correction_from_walk` 里的说明)。同一时刻也已经打到控制台、
        #   由 main_loop 落进日志文件。
        self.last_count_fix = None
        # ★★★ 2026-09-13 深夜:这一次量到的左边缘是不是**量短了**(漏掉最左那张牌)。
        #   由 `measure_edges` 每次刷新(判据见 LAYOUT_TRUST_RIGHT_IF_LEFT_SUSPECT)。
        self.last_left_suspect = False
        # ★ 右边缘**也**可能量短 —— 两条同时量短时不许"用坏的换坏的"(实机见过)。
        self.last_right_suspect = False
        # ★★★ 手牌记忆(可选注入;`find_playable` 会问它"哪些探针可以跳过")
        self.memory = None
        # 这一轮记忆给出的计划(日志/诊断用):None = 没用记忆
        self.last_memory = None
        # 记忆校验发现"整体错位" -> 这一轮退回老实扫(由 find_playable 消费)
        self._memory_broken = False
        self.cursor_clamped = 0      # 光标没能落到目标点的次数(见 _move)
        # 放大卡指纹库(自动学习,见 card_match.CardHashDB)
        self.hash_db = CardHashDB(HASH_DB_PATH)
        self._hash_dirty = False
        self._hash_saved_at = 0.0

    def _learn_hash(self, bits, name, type_=None):
        """
        记住"卡名读出来了"的那张卡的指纹,以后卡名读不出时靠它认卡。
        落盘做了去抖(默认 10s):一张卡的指纹在整个库里只需要一条,
        所以学习只会在遇到新卡时发生,不会每帧都写文件。
        """
        if bits is None or not name:
            return
        if self.hash_db.learn(bits, name, type_):
            self._hash_dirty = True
            now = time.time()
            if now - self._hash_saved_at > 10.0:
                self.hash_db.save()
                self._hash_dirty = False
                self._hash_saved_at = now

    def _move(self, x, y):
        """
        把光标移到客户区 (x,y)。

        ★ 按【实际落点】记账,不按请求点。
        Windows 会把光标裁剪进桌面范围:窗口位置/DPI 一旦让目标点落到屏幕外,
        SetCursorPos 会静默地把它拉回来,光标根本没到我们想去的地方。如果这时
        还按请求点记账,下一步 `user_took_over()` 就会把这点误差当成"用户在操作
        鼠标",扫描在第一个探针就中止 —— 实测表现是 `0 cards in 0.8s`,
        而日志里完全看不出原因。
        记账改成实际落点后,让行判据只对**别人的**鼠标动作敏感;
        光标被裁剪这件事单独计数,由 last_reason 报出来(否则扫描会安静地
        扫空:悬停探针全落在错误的位置,一张牌都弹不出来)。
        """
        sx, sy = client_to_screen(self.hwnd, x, y)
        actual = set_cursor_checked(sx, sy)
        if actual is None:                       # 读不到就退回请求点
            set_cursor(sx, sy)
            self._last_cursor = (sx, sy)
            return
        if abs(actual[0] - sx) > 8 or abs(actual[1] - sy) > 8:
            self.cursor_clamped += 1
        self._last_cursor = (int(actual[0]), int(actual[1]))

    def _why(self, msg: str, debug: bool = False) -> str:
        """记下"这次扫描为什么是这个结果"(每条早退路径都要写)。"""
        self.last_reason = msg
        if debug:
            print(f"    {msg}")
        return msg

    def user_took_over(self) -> bool:
        """
        鼠标是不是**被别人**动了(用户自己操作,或者别的程序)。

        判据:脚本上次把光标放在 _last_cursor;如果现在光标离那儿很远,那不是
        脚本干的 —— 只能是别人。扫描每一步都查一次,一旦发现就立即中止,把鼠标
        还给用户:宁可这次扫描白做,也不要一直抢。

        ★ 实测这个判据会**指向真正的问题**(2026-09-11 的 0.8s 之谜):
          当时有两个 main_loop 实例在跑,一方把光标放到手牌上、另一方又把它
          移走,于是双方的让行判据都一路为真,扫描全在第一个探针就中止。
          表现就是 `hand scan: 0 cards in 0.8s` —— 看起来像扫描器坏了。
          现在:①启动时用单实例锁(win.acquire_single_instance_lock)挡掉第二个
          实例;②中止时把原因写进 last_reason,日志里直接能看见。
        """
        if self._last_cursor is None:
            return False
        return cursor_moved_from(*self._last_cursor)

    def _baseline(self):
        self._move(*self.safe)
        time.sleep(SAFE_SETTLE)
        return capture_client_bgr(self.hwnd)

    def _hover_frame(self, x):
        self._move(x, self.y)
        time.sleep(self.hold)
        return capture_client_bgr(self.hwnd)

    @staticmethod
    def _panel_same(a, b):
        """
        两个探针看到的是不是同一张卡的面板。

        用 bbox 的交并比 + 面积比双重判断。同一张卡的相邻探针里,悬停面板
        位置几乎不动(只有光标小图标在面板内移动),所以重叠度很高;
        换到相邻的卡时面板会整体平移,重叠度立刻掉下来。
        """
        if a is None or b is None:
            return False
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        ix1, iy1 = max(ax, bx), max(ay, by)
        ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
        if ix2 <= ix1 or iy2 <= iy1:
            return False
        inter = (ix2 - ix1) * (iy2 - iy1)
        union = aw * ah + bw * bh - inter
        if union <= 0:
            return False
        iou = inter / union
        # 面积也要接近:一个超大的假面板可能把真面板整个包住,此时 IoU 不低,
        # 但面积比会露馅。
        area_a, area_b = aw * ah, bw * bh
        size_ratio = min(area_a, area_b) / max(area_a, area_b)
        return iou >= PANEL_IOU_SAME and size_ratio >= 0.6

    def _classify(self, region, y0=0, box=None, frame=None, debug=False):
        """
        ★ 2026-09-13:把识别**限制在一个近正方形的窗口里**(见 NAME_OCR_* 的实测说明)。

        为什么:OCR 的成本 = 736² × (长边/短边),模板匹配的成本 = 输入面积。
        旧代码把**整块 diff bbox**(可能 1280x720)喂进去,形状很差 ——
        实测裁成 680x600 之后,**认得出卡名的那 51 帧从 1.87s 降到 1.0s(1.87x)**,
        而**认出来的牌一个字都没变**(见 `src/hand_timing.py` 的 A/B)。

        ★ 候选集逻辑完全没动(`_classify_core` 原样):这里只负责"喂哪块图"。
        ★ fail-open:窗口里**没认出卡名** -> 拿**整块**再跑一遍老代码。
        """
        if not NAME_OCR_WINDOW:
            return self._classify_core(region, y0=y0, box=box, frame=frame,
                                       debug=debug)
        narrow = self._name_window(region, y0, box)
        if narrow is None:
            return self._classify_core(region, y0=y0, box=box, frame=frame,
                                       debug=debug)
        info = self._classify_core(narrow, y0=y0, box=box, frame=frame,
                                   debug=debug)
        # ★★ 只有"**认出了卡名**"才提前返回 —— 类型单独认出来**不算**。
        #
        # 为什么(这是验证时真踩到的,不是想出来的):一开始写的是
        # `if info.get("name") or info.get("type")`,看着很合理(类型也算收获)。
        # 于是我用一个**故意打偏的窗口**(x 0~130)去测 fail-open,结果 20 帧里有
        # **6 帧返回了错的答案而根本没走兜底** —— 窗口只剩一条缝,图标匹配在那条缝上
        # 误报了一个 `type`(实测 icon_score 0.745 那种假匹配,§7 第 79 条 ③),
        # 于是"有收获"就把兜底挡掉了。
        # ⇒ 判据改成:**只有卡名**才算收获(卡名来自查库,是硬的);
        #   没认出卡名就老老实实拿整块再跑一遍 —— 那一路是**原封不动的老代码**,
        #   跑出来的结果**必然**和改之前一模一样,所以"裁窗口"这件事
        #   **不可能**让任何一张牌从"认得出"变成"认不出"。
        if info.get("name"):
            info["ocr_window"] = "narrow"
            return info
        if debug:
            print("      [窗口] 窄窗口里没认出卡名 -> 退回整块重跑")
        full = self._classify_core(region, y0=y0, box=box, frame=frame,
                                   debug=debug)
        full["ocr_window"] = "full"
        return full

    def _name_window(self, region, y0, box):
        """
        把 region 裁成 NAME_OCR_* 那个近正方形窗口;不值得裁就返回 None。

        ★ box 传进来的是**整块**在帧里的 bbox:窗口是按**屏幕坐标**定义的
          (卡名/图标永远画在屏幕中部那一带),所以要先换算成 region 的行列。

        ★★ "面积变小了"**不等于**"更快":裁出来的形状如果比原来更扁,
           detector 那一步反而更贵(它只认长宽比)。所以这里**不是**按面积判,
           而是按实测出来的成本模型判:
             det  ≈ 2.5e-7 s/px × (736² × 长宽比)     ← 只和长宽比有关
             模板 ≈ 7e-7   s/px × 面积                 ← 7 个模板扫全图,和面积成正比
           两者相除 ⇒ 只要比较 `0.36 × 736² × 长宽比 + 面积` 就够了。
           (实测依据:`--shapes`/`--parts`,见 src/hand_timing.py。)
        """
        rx0 = box[0] if box else 0
        h, w = region.shape[:2]
        c0 = max(0, NAME_OCR_X0 - rx0)
        c1 = min(w, NAME_OCR_X1 - rx0)
        r1 = min(h, max(0, NAME_OCR_Y1 - y0))
        cw, ch = c1 - c0, r1
        if cw < 60 or ch < 60:
            return None
        if self._ocr_cost(cw, ch) >= self._ocr_cost(w, h):
            return None                     # 裁了不会更快 -> 别折腾
        return region[:ch, c0:c1]

    @staticmethod
    def _ocr_cost(w, h):
        """识别一块 w×h 的图的相对成本(只用来比大小,单位无所谓)。"""
        if w <= 0 or h <= 0:
            return float("inf")
        long_side, short_side = max(w, h), min(w, h)
        return 0.36 * 736 * 736 * (long_side / short_side) + w * h

    def _classify_core(self, region, y0=0, box=None, frame=None, debug=False):
        """
        region: 裁剪出来的悬停面板区域(局部坐标)
        y0:     region 在整帧里的起始 y(用来排除手牌区)
        box:    面板在整帧里的 bbox(可选,给指纹库裁剪卡面用)
        frame:  整帧(可选,给指纹库裁剪卡面用)

        ★ 卡名只认【中线附近的大字】。
        悬停时 KARDS 会在屏幕中部弹出放大卡,卡名是大字;而底部手牌区
        还有一堆小字(卡名残句、费用),那儿的 OCR 结果全是"…的单位攻击。"
        这类残句,读它必然出错(实测把一张坦克认成了指令卡"攻击")。
        所以:丢掉手牌区(y > NAME_ZONE_MAX_Y)的行,再在剩下的里取【行高最大】的
        那个 —— 放大的卡名永远是那一带字号最大的文字。

        识别顺序(每一级失败都往下走):
          1. 类型图标模板匹配(便宜,不依赖 OCR)
          2. 卡名 OCR + 查库 —— 顺带用图像指纹"学习"这张卡
          3. 卡名读不出:
             a. 指纹库查表(以前学过这张卡的卡面)
             b. 费用徽章 OCR 兜底 —— 至少让引擎知道要花多少费
                (PROJECT_STATE 第 35 条:纯英文+数字卡名 OCR 读不出,
                 引擎因 cost=None 永远不出这张牌)
        """
        info = {"type": None, "cost": None, "name": None}
        # 1. 类型图标匹配(便宜,不依赖 OCR)
        best, best_s, best_reg = None, 0.0, None
        for name in self.icon_names:
            s, reg = match_one(region, self.templates[name])
            if reg and s > best_s:
                best_s, best, best_reg = s, name.replace("_icon", ""), reg
        if best and best_s > 0.65:
            info["type"] = best
            info["icon_score"] = round(best_s, 3)
            info["icon_reg"] = best_reg

        # ★ 卡名只把【中线附近】那块交给 OCR(手牌区的小字只会污染结果)。
        # 再叠上用户 2026-09-11 指出的规律:
        #   **指令(order)/ 反制(counter) 这两类牌的卡名印在它们那个
        #     感叹号 / 问号图标【下边】** —— 所以先认类型,再决定 OCR 往哪看。
        # 其它类型保持原样(卡名在中线附近那条带上)。
        # ★ 指令/反制例外:它们的卡名印在放大卡下方(实测 y≈551),所以名字带
        #   要放宽到 600(手牌扇形小字在 y≈629,仍然被挡住)。
        special_name_zone = best in ("order", "counter")
        zone_max_y = NAME_ZONE_MAX_Y_SPECIAL if special_name_zone else NAME_ZONE_MAX_Y
        z0 = zone_max_y - y0
        zone = region[:z0, :] if z0 > 0 else region[:0, :]
        info["ocr_zone_h"] = int(zone.shape[0])

        lines = []
        if zone.size:
            lines = _ocr(zone)
            # 指令/反制:卡名在图标下方 -> 若第一遍没读出名,再专门裁一条
            # "图标正下方"的窄带补一次 OCR
            if best in ("order", "counter") and best_reg is not None \
                    and not any(match_name(ln["text"]) for ln in lines):
                ix, iy, iw, ih = best_reg
                by0 = iy + ih + 2
                by1 = min(zone.shape[0], by0 + TYPE_NAME_BAND_H)
                if by1 > by0:
                    strip = zone[by0:by1, :]
                    extra = _ocr(strip)
                    if debug or extra:
                        info["ocr_below_icon"] = [ln["text"] for ln in extra]
                    # 补读的行 y 要加回偏移,后面的日志/诊断才对得上
                    for ln in extra:
                        ln["y"] = ln.get("y", 0) + by0
                        ln["cy"] = ln.get("cy", 0) + by0
                    lines = lines + extra

        if debug:
            info["ocr_lines"] = [ln["text"] for ln in lines]

        hits = []
        cost_lines = []
        for ln in lines:
            # 下方名字带(只有指令/反制够得到)把门槛放到 0.5,见常量处的实测说明
            conf_min = NAME_CONF_MIN
            if special_name_zone and (y0 + float(ln.get("y", 0))) >= NAME_BOTTOM_BAND_Y:
                conf_min = NAME_CONF_MIN_BOTTOM
            if ln["conf"] < conf_min:
                continue
            nm, tier = match_name(ln["text"], debug=True)
            if nm:
                hits.append((int(ln.get("h", 0)), len(nm), nm, ln["text"], tier))
            cost_lines.append(ln)

        if hits:
            # 取字号最大的那行 = 放大的卡名(描述文字明显更小)
            hits.sort(key=lambda t: (-t[0], -t[1]))
            line_h, _n, nm, raw, tier = hits[0]
            info["name_h"] = line_h          # 诊断用:卡名那行的字号
            info["ocr"] = raw                # 诊断用:读到的原文
            info["name_tier"] = tier         # 诊断用:哪一级命中的
            info["name"] = nm
            entry = _card_by_name(nm)
            if entry:
                if info["cost"] is None:
                    info["cost"] = entry.get("kredits")
                info["db_type"] = entry.get("type")
                # 卡名查库的类型比 24px 图标匹配权威,冲突时以库为准
                if info["db_type"]:
                    info["type"] = info["db_type"]

        # 2. 学习指纹:卡名读出来了就记住这张卡的卡面
        bits = None
        if frame is not None and box is not None:
            crop = crop_card_name_band(frame, box)
            bits = dhash(crop)
            info["hash"] = hash_to_hex(bits) if bits is not None else None
            if info.get("name"):
                self._learn_hash(bits, info["name"], info.get("type"))

        if info.get("name"):
            return info

        # 3a. 卡名读不出 -> 指纹库查表
        if bits is not None and len(self.hash_db):
            hname, htype, hdist = self.hash_db.lookup(bits)
            if hname:
                info["name"] = hname
                info["hash_hit_distance"] = hdist
                entry = _card_by_name(hname)
                if entry:
                    info["cost"] = entry.get("kredits")
                    if entry.get("type"):
                        info["type"] = entry["type"]
                return info

        # 3b. 还认不出 -> 费用徽章兜底(至少让引擎知道费用)
        cost, ev = read_cost_badge(cost_lines)
        if cost is not None:
            info["cost"] = cost
            info["cost_source"] = ev
        # ★★★ 2026-09-19(实机第二局):**卡名没读出来时,把 OCR 行留下来当证据。**
        #   起因:用户报"那个喷火从头到尾就没打出过",而日志里只有
        #   `x466=fighter(fighter/None,✗)` —— 看得出"没读到",**看不出卡在哪一级**。
        #   (原来只有 `debug=True` 才收 `ocr_lines`,生产路径上永远是空的。)
        #   代价只有"失败时多存几个字符串",换来的是下次实机能当场判因。
        if not info.get("name"):
            info["ocr_lines"] = [ln["text"] for ln in lines][:6]
        return info

    def find_playable(self, budgets, edge=None, right=None, exclude=None,
                      max_cards=10, debug=False, allow_draw=False):
        """
        ★ 惰性扫描(用户 2026-09-11 的想法):**找到第一张能出的牌就停手**。

        budgets: [上限1, 上限2, ...] —— 依次放宽;每一轮只识别到
                 "第一张出得起、且有明确费用的可部署单位"为止。
        edge:    已经测好的扇形左边缘。**传了就不重测**(重测约 1 秒),
                 所以"边扫边出"的循环里该测一次、反复传进来。
        exclude: 本回合已经试过的探针位置(出过牌 / 被拒绝的),
                 **必须传进来** —— 否则引擎会一遍遍找到同一张牌。

        为什么要这样:实测瓶颈是**探针数量**,不是 OCR ——
        每个探针要付 0.5s 固定等待(回安全点 + 悬停稳定),
        5 张牌约 15 个探针 = 7.5 秒白等。而"找到一张能出的"通常只要前几个探针。

        返回 (cards, cost);没找到返回 ([], None)。
        """
        layouts = self._load_layouts()
        if not layouts:
            self._why("惰性扫描:没有 config/hand_layout.json(先跑 hand_zone_capture.py)",
                      debug)
            return [], None
        if edge is None:
            edge = self.measure_left_edge()
        if edge is None:
            self._why("惰性扫描:测不到扇形左边缘(手牌是空的,或者画面不是对局)",
                      debug)
            return [], None
        cands = sorted(
            (v for v in layouts.values()
             if abs(v.get("left_edge", -999) - edge) <= LAYOUT_EDGE_TOL),
            key=lambda v: abs(v["left_edge"] - edge))
        # ★★★ 2026-09-13:右边缘也参与排序(见 LAYOUT_MATCH_BOTH_EDGES 的说明)
        if LAYOUT_MATCH_BOTH_EDGES and right is not None and cands:
            width = right - edge
            sane = LAYOUT_WIDTH_SANE[0] <= width <= LAYOUT_WIDTH_SANE[1]
            if sane:
                def _rank(v):
                    dl = abs(v["left_edge"] - edge)
                    d_r = (abs(v["right_edge"] - right)
                           if v.get("right_edge") else 999)
                    both_ok = d_r <= LAYOUT_RIGHT_TOL
                    # ① 两边都对得上的优先 ② 残差和小的优先 ③ 左边缘近的优先
                    return (0 if both_ok else 1, dl + min(d_r, 120), dl)
                cands = sorted(cands, key=_rank)
            else:
                if debug:
                    print(f"    [边缘] 量到宽度 {width} 不合理"
                          f"{LAYOUT_WIDTH_SANE} -> 退回只看左边缘")
        # ★★★ 2026-09-13 深夜:**左边缘"量短了" -> 改用右边缘挑条目**(判据见常量区)。
        #   为什么必须放在"筛候选"这一步之后、而不是只参与排序:
        #   老逻辑是"先用左边缘过闸(容差 22)、再用右边缘排序",而量短的左边缘
        #   会把正确答案**在过闸那一步就丢掉**(实机:8 张条目左边缘差 59px ->
        #   直接出局,右边缘只差 1px 也救不回来)。
        via_right = False
        if (LAYOUT_TRUST_RIGHT_IF_LEFT_SUSPECT
                and getattr(self, "last_left_suspect", False)
                and not getattr(self, "last_right_suspect", False)
                and right is not None
                and LAYOUT_WIDTH_SANE[0] <= (right - edge) <= LAYOUT_WIDTH_SANE[1]):
            by_right = sorted(
                (v for v in layouts.values()
                 if v.get("right_edge")
                 and abs(v["right_edge"] - right) <= LAYOUT_RIGHT_TOL),
                key=lambda v: abs(v["right_edge"] - right))
            if by_right:
                via_right = True
                # ★★★ 2026-09-21:**两边各闸放行的候选取并集,不是替换**。
                #   实机证据(2026-09-20 那一局 23:42:06 那帧):左边缘基本准
                #   (量到 L414,表里 5 张是 421,差 7),而**右边缘短了 113px**
                #   (量到 R812,真值约 925)。老代码一进这条分支就 `cands = by_right`,
                #   右闸把 8 张那条(R 925,差 113)在**过闸那一步**就扔了 ——
                #   于是"左边缘差 59px"的错误条目靠"右边缘差得少"胜出。
                #   这和第 711~715 行注释里记的那次事故**是同一个形状**:
                #   "量短的边缘会把正确答案在过闸那一步就丢掉,另一条边缘只差 1px 也救不回来"。
                #   ⇒ 谁都不许在"过闸"这一步被另一个坏测量杀掉;要淘汰也是后面排序的事。
                #   ★ 这一改还顺带解释了实机日志里一处对不上的地方:23:42:06 那行写着
                #     `容差内还有 [9, 8]`,而现行代码在 L414 下**只放得进 5 张**
                #     (复核者按逐字重放复现不出那格) —— 取并集之后,9/8 张本来就会在候选里。
                #   排序仍以**右边缘残差**为主(这条分支的本意就是"信右边缘"),
                #   并列时**张数多的优先**(与 `dev/hand_layout_pick_ab.py` 里那条更强的规则对齐)。
                seen_ids = {id(v) for v in cands}
                merged = list(cands) + [v for v in by_right if id(v) not in seen_ids]
                cands = sorted(
                    merged,
                    key=lambda v: (abs((v.get("right_edge") or 0) - right)
                                   if v.get("right_edge") else 999,
                                   -(v.get("count") or 0)))
        if cands:
            # 顺手记下"这次匹配到的手牌是几张"给引擎用(见 last_hand_count)
            # ★★★ 2026-09-21:这里**不再是最终值** —— 它只是"选中那条布局表说的张数"。
            #   真正的实读张数由 `_count_correction_from_walk` 在**整条探针走完**之后
            #   按"有没有 -1 探针读到牌"改上去(判据与实机复核见常量区
            #   `LAYOUT_COUNT_FROM_PROBES`)。为什么不能在这里就定死:此刻**一根探针都还没走**,
            #   没有任何"实读"证据,只能先按表里的值占位。
            self.last_hand_count = cands[0].get("count")
        # ★★ 2026-09-13(第十个会话):把"这次到底用了哪条布局、有几个候选"
        #   记下来给引擎写日志。为什么必须写出来:
        #   §7 第 32 条早就量过"容差内允许多个候选,靠命中率定谁对",而
        #   **惰性扫描这条路只取 `cands[0]`(离左边缘最近的那个),从不验证** ——
        #   实测证据:2026-09-13 那一局第 6/7 回合,日志写着
        #   `deploying Fw 190 A 百舌鸟 (fighter, cost 6) 手牌x=455`,而费用只掉 3,
        #   说明**拖出去的是邻居那张牌**;而 `x=455` 正好是「5 张」那条布局的
        #   第一个探针 —— 在一副**6 张**的手牌上,它落在第 1、2 张的**分界线上**。
        #   日志里以前完全看不到"用的是 5 张那条"这件事。
        # ★★★ 2026-09-20(用户实机日志,12h44m):**这一行原先少了 `if cands` 守卫。**
        #   上面的 count / left_edge 都有,只有 n_probes 写了 `(cands[0] or {})`
        #   —— 那个 `or {}` 只挡得住"元素是假值",挡不住**列表本身是空的**,
        #   于是 `cands == []` 时直接 IndexError。
        #   为什么这条是致命的:下面 `if not cands:` 那一整段(盲扫兜底)本来就是
        #   为"布局表一条都对不上"写的,而 bug 在它**前面一行**就把线程掀了 ——
        #   兜底永远走不到。异常从 think() 冒到 main_loop.handle_in_game 的 except,
        #   那一 tick **根本没执行到"该不该结束回合"**,下一 tick 从同一步重来。
        #   实机指纹:手牌出完那一刻最容易踩(布局表里没有"0 张"这条),
        #   日志里 34 段卡死、每段 10~61 秒,玩家看到的就是"操作完了不结束回合"。
        self.last_layout = {
            "count": (cands[0].get("count") if cands else None),
            "left_edge": (cands[0].get("left_edge") if cands else None),
            "n_probes": (len(cands[0].get("probes") or []) if cands else 0),
            # ★ 2026-09-21:并集探针启用后,**实走**的根数(见 `_probes_for`)——
            #   上面那个 `n_probes` 是"选中那条条目自己的"根数,两者不一样时必须都写出来。
            "n_probes_actual": None,
            "n_cands": len(cands),
            "cand_counts": [v.get("count") for v in cands],
            "measured_edge": int(edge) if edge is not None else None,
            # ★★ 两个边缘 + 选中那条的残差都写进日志:以后"选错条目"能当场看见,
            #    不必再去翻存帧(判据的证据要跟结论写在一起)。
            "measured_right": int(right) if right is not None else None,
            # ★★★ 2026-09-13 深夜:把"为什么用右边缘挑"写进日志 ——
            #   判据(左边缘量短了)和结论(改用右边缘)必须写在一起,
            #   否则下一个人只会看到"选了 8 张"而不知道它凭什么。
            "via": ("right" if via_right else "left"),
            "left_suspect": bool(getattr(self, "last_left_suspect", False)),
            "res_l": (abs(cands[0]["left_edge"] - edge) if cands else None),
            "res_r": (abs(cands[0]["right_edge"] - right)
                      if (cands and right is not None
                          and cands[0].get("right_edge")) else None),
            "runner": ([{"count": v.get("count"),
                         "res_l": abs(v["left_edge"] - edge),
                         "res_r": (abs(v["right_edge"] - right)
                                   if (right is not None and v.get("right_edge"))
                                   else None)}
                        for v in cands[1:3]] if cands else []),
        }
        if not cands:
            # 布局表对不上 -> 张数也就不可信了,清掉(引擎按"不知道"处理)
            self.last_hand_count = None
            self.last_layout = {
                "count": None, "left_edge": None, "n_probes": 0,
                "n_cands": 0, "cand_counts": [],
                "measured_edge": int(edge) if edge is not None else None,
            }
            nearest = min(layouts.values(),
                          key=lambda v: abs(v["left_edge"] - edge))
            self._why(f"惰性扫描:左边缘 {edge} 与最近布局({nearest['count']} 张,"
                      f"{nearest['left_edge']})差 "
                      f"{abs(nearest['left_edge'] - edge)}px > 容差 {LAYOUT_EDGE_TOL}",
                      debug)
            # ★★ 2026-09-11 傍晚实机补的兜底:布局表对不上 -> **整回合一张牌不出**。
            #   实测连着三个回合都是同一行日志:
            #     `惰性扫描 #N: 0.3s 内没找到出得起的牌 | 原因: 左边缘 277 与最近布局
            #      (8 张,357)差 80px > 容差 22`
            #   —— 0.3s 说明它**根本没扫**,只是查表失败就放弃了,而回合照样被结束掉。
            #   盲扫(scan)不看布局表,所以布局表坏掉/换了棋盘/手牌数和表对不上时
            #   它能兜住;代价是十几秒,但**总比整回合不出牌好**(这正是"静默失败"
            #   那一类问题:日志有原因,但玩家看到的是"这局它什么都不干")。
            return self._blind_scan_fallback(budgets, exclude, debug)

        found = []
        for budget in budgets:
            # ★★★ 手牌记忆:先问它"这一轮哪些探针不用悬停"
            plan = self._memory_plan(cands[0], budget, allow_draw=allow_draw,
                                     debug=debug)
            if plan is not None:
                res, cost = self._memory_path(cands[0], budget, plan,
                                              exclude=exclude, debug=debug)
                if res:
                    found.extend(res)
                    return found, cost
                if not self._memory_broken:
                    # ★★ 记忆这一轮**可信**而且已经走完了 -> **就按它的结论收手**。
                    #   这正是省时间的地方:跳过那些探针,本来就是为了不看它们;
                    #   要是这里再退回老实扫一遍,记忆一个探针都省不下来
                    #   (实机第一版就是这么白做的:`_probe_layout_until` 照样跑)。
                    self._why(f"手牌记忆可信:跳过 "
                              f"{len(plan.get('skip') or [])} 个已知探针后,"
                              f"预算 {budget} 内没有可部署的牌", debug)
                    return found, None
                self._memory_broken = False
            # ★★★ 2026-09-21:走**并集探针**(见 `LAYOUT_PROBE_UNION`)。
            #   这条路以前只取 `cands[0]`、**且从不验证**(第 736 行自己的注释就写着
            #   "从不验证"),正是"探针只落在第 2/4/6/8 张上"那类事故的来源。
            #   ★ 顺手把"实走几根"记进 `last_layout` —— 日志里那句"7 探针"是**选中那条
            #     条目自己的**根数,走了并集之后它就不再是全貌了,不写清就是让日志说谎。
            probes_use = self._probes_for(cands, debug=debug)
            if self.last_layout:
                self.last_layout["n_probes_actual"] = len(probes_use)
            res, cost = self._probe_layout_until(
                cands[0], budget, exclude=(exclude or set()) | {c["x"] for c in found},
                max_cards=max_cards, debug=debug, probes=probes_use)
            if res:
                found.extend(res)
                return found, cost
        # ★★ 2026-09-21:这一行是引擎那行日志里**最后**关于张数的话(`| 原因: …`),
        #   而修正在它**之前**就跑完了 —— 不改它,日志里报的就还是**表里那个错的**张数,
        #   而真正交给 `hand_memory` 的实读值在日志里一个字都看不到。
        #   所以张数按实读值报,并把"表里说几张"一起写出来(判据和结论写在一起)。
        table_n = cands[0]["count"]
        read_n = self.last_hand_count
        n_text = (f"布局「{read_n} 张」" if read_n in (None, table_n)
                  else f"布局「实读 {read_n} 张」(表里写 {table_n} 张)")
        self._why(f"惰性扫描:{n_text}"
                  f"{len(cands[0].get('probes', []))} 个探针全扫完,"
                  f"预算 {budgets} 内没有可部署的牌", debug)
        return found, None

    # ------------------------------------------------------------ 手牌记忆这一路
    def _memory_plan(self, entry, budget, allow_draw=False, debug=False):
        """
        问记忆要一份"这一轮的计划";拿不到(没记忆/不可用/没省头)就返回 None。

        ★ 只有**真的能省下至少一个探针**时才用记忆 —— 否则(比如全部都得探)
          用记忆只会多花一次校验,纯亏。
        """
        self.last_memory = None
        if not USE_HAND_MEMORY or self.memory is None:
            return None
        count = entry.get("count")
        # ★ 下标要对得上:记忆的第 i 张 <-> 布局条目的第 i 个探针。
        #   实测表里每个张数就是"每张一个探针"(4 张 4 个),但**不许假设** ——
        #   对不上就别用记忆(fail-open)。
        if count is None or len(entry.get("probes") or []) != count:
            return None
        if not self.memory.ok_for(count, allow_draw=allow_draw):
            return None
        # ★ 2026-09-20:`{"order"}` 也交给记忆 —— 否则"记着这张是指令 -> 以后每回合都跳过",
        #   于是指令永远回不到候选里。真正能不能打仍由 `is_playable()` 决定
        #   (记忆只用来决定"哪些不用悬停")。
        plan = self.memory.plan(budget, DEPLOYABLE_TYPES | {"order"})
        if not plan or plan.get("saved", 0) <= 0:
            return None
        self.last_memory = plan
        if debug:
            print(f"    [记忆] {self.memory.short()} -> 跳过 {plan['skip']}、"
                  f"必探 {plan['probe']}、候选 {plan['targets']}、"
                  f"校验 {plan['verify']}")
        return plan

    def _memory_path(self, entry, budget, plan, exclude=None, debug=False):
        """
        按记忆的计划走:**先做一次校验(抓整体错位),再只探"必须探的"和"要出的"。**

        返回和 `_probe_layout_until` 一样:([card], cost) 或 ([], None)。
        ★ 校验不过 / 真要出的那张与记忆不符 -> 当场把记忆判失效,并置
          `self._memory_broken = True` 让调用方**退回老实扫**(fail-open)。
        """
        probes = entry.get("probes") or []
        exclude = exclude or set()
        seen = []
        self.last_probe_seen = seen
        saved = plan.get("saved", 0)
        verify_ok = False

        def probe_index(i, why):
            """悬停第 i 个探针并识别;返回 (info, card_dict) 或 (None, None)。"""
            if not (0 <= i < len(probes)):
                return None, None
            px = probes[i]
            rec = {"i": i, "x": px, "panel": False}
            seen.append(rec)
            if px in exclude:
                rec["why"] = "这一轮已经试过"
                return None, None
            self._move(*self.safe)
            time.sleep(SAFE_SETTLE)
            base = capture_client_bgr(self.hwnd)
            self._move(px, self.y)
            time.sleep(self.hold)
            hover = capture_client_bgr(self.hwnd)
            if base is None or hover is None:
                return None, None
            box = diff_bbox(base, hover)
            if box is None:
                if debug:
                    print(f"      [记忆] x={px} 没有面板(这张牌可能不在了)")
                return None, None
            bx, by, bw, bh = box
            info = self._classify(hover[by:by + bh, bx:bx + bw], y0=by,
                                  box=box, frame=hover, debug=debug)
            cost = info.get("cost")
            ctype = info.get("type")
            rec.update({"panel": True, "name": info.get("name"), "type": ctype,
                        "cost": cost,
                        "playable": bool(is_playable(ctype, info.get("name"))
                                         and cost is not None and cost <= budget),
                        "why": why,
                        # ★ 2026-09-19:同上,拒绝的原因要能当场看见
                        "cost_source": info.get("cost_source"),
                        "ocr": info.get("ocr"),
                        "name_tier": info.get("name_tier"),
                        "icon_score": info.get("icon_score")})
            card = {"x": px, "i": i, "name": info.get("name"), "type": ctype,
                    "cost": cost, "info": info,
                    "panel": hover[by:by + bh, bx:bx + bw].copy()}
            return info, card

        # ---- ① 一次校验:抓"整体错位"(错位会让**每一个**下标的身份都不对) ----
        #   ★ 如果校验点本来就在"要探的清单"里(候选/未知),就**顺手在那次悬停上校验**,
        #     不额外多悬停一次(否则等于白花 1.9s)。
        v = plan.get("verify")
        to_probe = list(plan.get("probe") or []) + \
            [i for i, _ in (plan.get("targets") or [])]
        verify_inline = v is not None and v in to_probe
        if v is not None and not verify_inline:
            info, card = probe_index(v, "记忆校验")
            if info is None:
                # 面板都没弹出来 -> 那一张可能已经不在了;不当成"错位",但也不信记忆
                self.memory.invalidate(f"校验点 x={probes[v] if 0 <= v < len(probes) else '?'} "
                                       f"没有弹出面板(那张牌可能不在了)")
                self._memory_broken = True
                return [], None
            mem = self.memory.cards[v] if 0 <= v < len(self.memory.cards) else None
            if mem is not None and not _same_identity(mem, info):
                self.memory.note_verify_bad()
                self.memory.invalidate(
                    f"校验点第 {v + 1} 张读到 {info.get('name') or info.get('type')}"
                    f"({info.get('cost')}),记忆说 "
                    f"{mem.get('name') or mem.get('type')}({mem.get('cost')})")
                self._memory_broken = True
                return [], None
            verify_ok = mem is not None
            if debug:
                print(f"      [记忆] 校验 x={probes[v]} = "
                      f"{info.get('name') or info.get('type')} "
                      f"{'✓' if verify_ok else '(身份未知,没基准)'}")

        # ---- ② 只探"身份未知的"和"记忆里能出的(便宜的先)" ----
        for i in to_probe:
            info, card = probe_index(i, "记忆校验" if i == v else "记忆计划")
            if card is None:
                continue
            # ★ 校验点落在这一张上(顺手校验):一致才算记忆可信
            if i == v and verify_inline:
                mem = (self.memory.cards[i]
                       if 0 <= i < len(self.memory.cards) else None)
                if mem is not None and not _same_identity(mem, info):
                    self.memory.note_verify_bad()
                    self.memory.invalidate(
                        f"校验点第 {i + 1} 张读到 "
                        f"{info.get('name') or info.get('type')}({info.get('cost')}),"
                        f"记忆说 {mem.get('name') or mem.get('type')}"
                        f"({mem.get('cost')})")
                    self._memory_broken = True
                    return [], None
                verify_ok = mem is not None
            if is_playable(card["type"], card.get("name")) \
                    and card["cost"] is not None and card["cost"] <= budget:
                self.memory.note_plan_used(saved, verify_ok)
                if self.memory.log:
                    self.memory.log(
                        f"[记忆] 命中:跳过 {saved} 个探针(约 {saved * self.memory.PROBE_COST_S:.0f}s)"
                        f" -> 直接出第 {i + 1} 张 "
                        f"{card.get('name') or card.get('type')}({card.get('cost')})")
                return [card], card["cost"]
        self.memory.note_plan_used(saved, verify_ok)
        return [], None

    def _blind_scan_fallback(self, budgets, exclude=None, debug=False):
        """
        布局表不可用时的兜底:**整手盲扫一遍**,再按预算挑出最便宜的可部署单位。

        `scan()` 不查布局表(它从 x=340 起按 STEP 走),所以布局表坏掉、
        换了棋盘、或者手牌数和表里的条目对不上时,它是唯一还能干活的路。
        代价是十几秒,但**比"整回合一张牌不出"好得多** ——
        2026-09-11 傍晚实机就是这么连着三个回合一张没出,而日志只有一行查表失败。

        返回和 `find_playable` 一样的 (cards, cost)。
        """
        self.last_reason = "布局表对不上 -> 盲扫兜底"
        ceiling = max(budgets) if budgets else 0
        try:
            cards = self.scan(debug=debug)
        except Exception as e:            # 兜底失败也不许把回合弄崩
            self._why(f"盲扫兜底失败:{type(e).__name__}: {e}", debug)
            return [], None
        if not cards:
            self._why("盲扫兜底:一张牌也没识别出来", debug)
            return [], None
        skip = set(exclude or set())
        best = None
        for c in cards:
            if c.get("x") in skip:
                continue
            cost, ctype = c.get("cost"), c.get("type")
            if is_playable(ctype, c.get("name")) and cost is not None and cost <= ceiling:
                if best is None or cost < best[1]:
                    best = (c, cost)
        if best is None:
            self._why(f"盲扫兜底:认出 {len(cards)} 张,但预算 {ceiling} 内"
                      f"没有能出的牌", debug)
            return [], None
        self.last_reason = (f"布局表对不上 -> 盲扫兜底命中 "
                            f"{best[0].get('name')}({best[1]})")
        if debug:
            print(f"    [兜底] 盲扫认出 {len(cards)} 张 -> 出 {best[0].get('name')}"
                  f"({best[1]})")
        return [best[0]], best[1]

    def measure_left_edge(self):
        """把鼠标放回安全点,测一次扇形左边缘(约 1 秒)。"""
        le, _re = self.measure_edges()
        return le

    def measure_edges(self):
        """
        把鼠标放回安全点(扇形回到**未展开**态),一次测出**两个**边缘。

        ★ 为什么两个都要:布局条目里两个边缘都是实测的,而"两边都解释得通"
          比"只有左边缘对得上"硬得多(见 `LAYOUT_MATCH_BOTH_EDGES`)。
        ★ 只在**光标停 SAFE_POINT** 时测 —— 悬停会展开扇形,边缘会变
          (`hand_calibrate.detect_left_edge` 的文档里那条实测:367 / 394 / 369)。
        """
        self._move(*self.safe)
        time.sleep(SAFE_SETTLE)
        frame = capture_client_bgr(self.hwnd)
        if frame is None:
            return None, None
        from hand_calibrate import detect_edges
        le, re_ = detect_edges(frame)
        # ★ 顺手判定两条边缘**各自**有没有"量短"(判据见常量区的实测说明)。
        #   为什么在这里判:`detect_edges` 刚跑完,`detect_left_edge.skipped` /
        #   `detect_right_edge.skipped` 里就是**这一帧**被跳过的窄段;换一帧就没了。
        self.last_left_suspect = self._edge_looks_short(le, "left")
        self.last_right_suspect = self._edge_looks_short(re_, "right")
        return le, re_

    def _edge_looks_short(self, edge, side):
        """
        选中的这条边缘**,它旁边有没有被检测器跳过的窄段**?

        有 -> 那些窄段多半是"最边那张牌被自己的卡纹切碎"的残片,
        而这条"边缘"其实是**相邻那张**牌的边缘(整张牌被漏掉)。

        ★ 两个方向都要判(2026-09-13 深夜实机证明**两条边缘可能同时量短**:
          21:11:02 那一帧左 383(真值 358)、右 850(真值 ~924)—— 那一帧**只能**
          退回左边缘规则;只判左边就变成了"拿坏右边缘去换坏左边缘",反而更差)。
        ★ 左侧还要排除固定装饰区(x < FAN_X_MIN),见那个常量的说明。
        """
        if edge is None:
            return False
        try:
            import hand_calibrate as hc
            fn = (hc.detect_left_edge if side == "left" else hc.detect_right_edge)
            skipped = getattr(fn, "skipped", None) or []
        except Exception:
            return False
        for s, w in skipped:
            if side == "left":
                if s < FAN_X_MIN:
                    continue                     # 左下角的固定装饰,不是手牌
                if 0 < edge - (s + w) <= SUSPECT_GAP:
                    return True
            else:
                if 0 < s - edge <= SUSPECT_GAP:
                    return True
        return False

    def _probes_for(self, cands, base_entry=None, debug=False):
        """
        这一轮**实际要走的探针序列** —— 见常量区 `LAYOUT_PROBE_UNION` 那段的实机证据。

        返回 `[(次序下标, x)]`:
          · 选中那条(`base_entry`,默认 `cands[0]`)的探针 **保留下标** ——
            手牌记忆是按"从左到右第几张"对齐的(`hand_memory.py`:扇形一平移 x 就变,
            只有次序稳),下标一乱记忆就废;
          · 并集进来的、以及两端补出来的,一律给下标 **-1** ——
            `hand_memory.plan()` 只认下标 >= 0,所以这些探针**永远不会被跳过**。
            这正是我们要的:补它们就是为了亲眼看一眼。
        """
        if not cands and base_entry is None:
            return []
        base = list((base_entry if base_entry is not None else cands[0]).get("probes") or [])
        seq = [(i, int(x)) for i, x in enumerate(base)]
        if LAYOUT_PROBE_UNION:
            for v in cands:
                if v is base_entry or (base_entry is None and v is cands[0]):
                    continue
                seq += [(-1, int(x)) for x in (v.get("probes") or [])]
        if LAYOUT_PROBE_EXTRA_ENDS and len(base) >= 2:
            pitch = (base[-1] - base[0]) / (len(base) - 1)
            # ★ 两端补针**按需**补,不无条件补:每根探针要付 ~0.6s 固定等待,
            #   而无条件在两端各补一根 = 每回合白花 1.2s。
            #   触发条件(两条都是"有据可依"的信号):
            #     · 候选不止一条(张数本身就有歧义)-> 两端都补;
            #     · 或检测器自己说这条边缘**旁边有被跳过的窄段**
            #       (`_edge_looks_short`:那个边缘多半是"第 2 张"的,整张牌被漏掉)
            #       -> 只补那一边。
            ambiguous = len(cands) > 1
            if ambiguous or getattr(self, "last_left_suspect", False):
                seq.append((-1, int(round(base[0] - pitch))))
            if ambiguous or getattr(self, "last_right_suspect", False):
                seq.append((-1, int(round(base[-1] + pitch))))
        # 去重:同一位置附近只留一根(优先留下标 >= 0 的,记忆才能照老样子跳它)
        seq.sort(key=lambda t: (t[1], t[0] < 0))
        out = []
        for i, x in seq:
            if x < FAN_X_MIN or x > LAYOUT_PROBE_X_MAX:
                continue                  # 扇形之外(固定装饰 / 右侧面板),别去探
            if out and abs(x - out[-1][1]) <= LAYOUT_PROBE_UNION_DEDUP_PX:
                continue
            out.append((i, x))
        if debug and len(out) != len(base):
            print(f"    探针并集:选中「{len(base)} 根」-> 实走 {len(out)} 根 "
                  f"{[x for _i, x in out]}")
        return out

    def _probe_layout_until(self, entry, budget, exclude=None, max_cards=10,
                            debug=False, probes=None):
        """
        按布局表从左到右悬停,**一旦找到一张"费用 <= budget 的可部署单位"就停**。

        返回 ([card], cost);没找到返回 ([], None)。
        exclude: 已经找过的探针位置(上一轮找到的那张,不要重复)。
        """
        exclude = exclude or set()
        # ★★★ 2026-09-21:调用方可以传 `probes`(并集探针,见 `_probes_for`);
        #   不传就还是"只用选中这条布局自己的探针"(老行为,A/B 用)。
        all_probes = (probes if probes is not None
                      else [(i, p) for i, p in enumerate(entry.get("probes", []))])
        # ★ 2026-09-13:连**下标**一起带着走 —— 手牌记忆要按"从左到右第几张"对齐
        #   (扇形一平移 x 就变了,只有次序是稳的,见 hand_memory.py)。
        probes = [(i, p) for i, p in all_probes if p not in exclude]
        last_box = None
        last_px = None
        # ★★ 诊断(2026-09-13 第十个会话):逐个探针记下"读到了什么"。
        #   为什么要记:用户报的两个症状——"扫到了却跳过部署"和"有费用却没下"——
        #   在日志里只表现为一句 `预算 N 内没有可部署的牌`,**看不出是哪张牌、
        #   差在哪一条**(类型没认出?费用没读出?费用超预算?)。
        #   这一行把每条判据都摊开,下一次实机就能当场分清。
        seen = []
        self.last_probe_seen = seen
        for i, px in probes:
            if self.user_took_over():
                self._why(f"惰性扫描:第 {len(probes)} 个探针前发现鼠标被别人"
                          f"移走 -> 中止让路", debug)
                return [], None
            self._move(*self.safe)
            time.sleep(SAFE_SETTLE)
            base = capture_client_bgr(self.hwnd)
            self._move(px, self.y)
            time.sleep(self.hold)
            hover = capture_client_bgr(self.hwnd)
            if base is None or hover is None:
                continue
            box = diff_bbox(base, hover)
            if box is None:
                seen.append({"i": i, "x": px, "panel": False})
                last_box = None
                continue
            # 同一张卡的相邻探针:已经在这张卡上做过判断了,跳过不重复识别
            if (last_box is not None
                    and self._same_card(box, last_box, last_px, px)):
                last_box = box
                continue
            last_box, last_px = box, px
            bx, by, bw, bh = box
            info = self._classify(hover[by:by + bh, bx:bx + bw], y0=by,
                                  box=box, frame=hover, debug=debug)
            cost = info.get("cost")
            ctype = info.get("type")
            playable = (is_playable(ctype, info.get("name")) and cost is not None
                        and cost <= budget)
            seen.append({"i": i, "x": px, "panel": True, "name": info.get("name"),
                         "type": ctype, "cost": cost, "playable": bool(playable),
                         # ★ 2026-09-19:拒绝的原因要能当场看见(见 turn_engine._probes_text)
                         "cost_source": info.get("cost_source"),
                         "ocr": info.get("ocr"),
                         "ocr_lines": (info.get("ocr_lines") or [])[:4],
                         "name_tier": info.get("name_tier"),
                         "icon_score": info.get("icon_score")})
            if debug:
                print(f"      x={px:<5} {info} "
                      f"-> {'可用,停止扫描' if playable else '继续'}")
            card = {"x": px, "i": i, "name": info.get("name"), "type": ctype,
                    "cost": cost, "info": info,
                    # ★★ 2026-09-13(第十个会话):**把这张牌的悬停面板一起带回去**。
                    #   为什么:部署成/没成的**最后一条退路**是"同一个手牌位置的面板
                    #   前后对比"(`turn_engine._panel_looks_same`),它需要一个
                    #   "拖之前的面板"当基准。全量扫描那一路有 `_scan` 预先拍,
                    #   而**惰性扫描这一路从来没拍过**(`card["_before"] = None`)
                    #   —— 于是 `_panel_looks_same(None, X)` 恒为 False,
                    #   `ok = not False = True`:**面板判据在惰性模式下是一枚橡皮图章**,
                    #   任何"费用读数不符 + 卡数读不准"的部署都会被判成成功。
                    #   实机证据:2026-09-13 那局第 6/7 回合两次
                    #   `部署成功 (费用读数 3 与账本 0 不符(读数可疑);⚠️卡数异常 6->8
                    #    -> 退回面板判据)` —— 正是这条退路给的"成功"。
                    #   这里把扫描时那一帧的面板裁出来当基准,**不额外花时间**。
                    "panel": hover[by:by + bh, bx:bx + bw].copy()}
            if playable:
                return [card], cost
        # ★★★ 2026-09-21:**只有走到这里**("整条探针从头到尾一根不落")才动张数。
        #   上面那个 `return [card], cost` 是"找到第一张能出的牌就收手" —— 那时手里
        #   还有没探过的位置,`seen` 里没有它们的记录,**拿它去推张数就是拿没探过的地方猜**
        #   (项目纪律:拿不准就 fail-closed)。所以修正动作挂在这个出口上,提前收手那条路
        #   一律保持 `find_playable` 给的占位值不变。
        # ★ 每次重设原因之前先把上一轮的修正行清掉 —— 否则"这一次没修"时,
        #   上一次修正的日志还挂在那儿,读日志的人会以为张数又被改过。
        self.last_count_fix = None
        self._count_correction_from_walk(entry, debug=debug, seen=seen)
        return [], None

    def _count_correction_from_walk(self, entry, debug=False, seen=None):
        """
        **整条探针走完之后**,按"实读到了什么"修正手牌张数(判据与实机复核见常量区
        `LAYOUT_COUNT_FROM_PROBES`) —— 调用点只有一处,就是 `_probe_layout_until` 的收尾出口。

        为什么只能在这里做:那之前所有"张数"都只是**布局表条目**说的数(一个已经被
        实机证明会猜错的量),而**唯一**能证伪它的证据是"补出来的探针真的读到了牌"。

        `seen`:本次探针逐个读到的记录(和 `_probe_layout_until` 的 `probes=` 一个套路 ——
                调用方可以传进来,不传就用 `self.last_probe_seen`)。

        返回 `(是否改了, 原值, 新值)`;没改就返回 `(False, None, None)`。
        """
        if not LAYOUT_COUNT_FROM_PROBES:
            return False, None, None
        was = self.last_hand_count
        # 拿不到表里的张数(布局对不上 -> None)就无从修起:没有基准,加多少都是猜。
        if not isinstance(was, int) or was <= 0:
            return False, None, None
        base_probes = list(entry.get("probes") or [])
        if len(base_probes) < 2:
            # 一根探针算不出间距(也就没有"覆盖范围"可言)——1 张/2 张这种手牌本来也不会错,
            # 不必为它引入一条没有几何依据的规则。
            return False, None, None
        if seen is None:
            seen = self.last_probe_seen
        hits = [s for s in (seen or [])
                if s.get("panel") and isinstance(s.get("x"), int)]
        if not hits:
            return False, None, None
        # ★ 什么算"在选中那条的覆盖范围之外":**落在这条布局的探针带以外**,
        #   而且超出的距离**超过一个 `MAX_SAME_SPAN`**(即"它的探针再偏也够不到那儿")。
        #   带子 = `[base[0] - span, base[-1] + span]`。
        #
        #   为什么两条都要:
        #   · 光看"离最近那根探针远不远"会**误判**:表里相邻候选取并集之后,实走探针是
        #     两套间距叠在一起的,某根 -1 针本来就会落在**两条带交界**处(实测 23:43:17
        #     那帧的 x777 离最近那根 base 针 744 有 36px,按"离得远就算多"会数出 10 > 真值 9)。
        #     落在带子**里面**的命中,不管离某根针多远,都在这条布局本来就覆盖到的那几张牌上。
        #   · 光看"落在两端之外"也会**误判**:实测同一根探针能读到相邻卡的一块
        #     (`MAX_SAME_SPAN` 就是为这条标定的),所以"刚出界一点点"完全可能是它本来就该
        #     探到的那张牌(23:41:34 那帧左端 x405 出界只有 7px,照"出界即多"会数成 8 > 真值 7)。
        #   ⇒ 两条一起用:出界 **且** 出界超过一个热区半宽,才谈得上"它覆盖不到"。
        span = MAX_SAME_SPAN
        left_reach = base_probes[0] - span
        right_reach = base_probes[-1] + span
        outside = sorted(s["x"] for s in hits
                         if s["x"] < left_reach or s["x"] > right_reach)
        if not outside:
            return False, None, None
        # ★ 先把挨在一起的合成**一个位置**:同一个位置被两根 -1 探针先后探到是常事
        #   (`_probes_for` 的去重只合成 15px 以内的,而并集补出来的针间距可能更大),
        #   不合成就会把**同一张牌**数成两张 —— 那是"猜多",比不改更坏。
        #   合并门槛也用 `MAX_SAME_SPAN`:同一个热区里的两根针本来就该算一处。
        spots = []
        for x in outside:
            if spots and x - spots[-1][-1] <= span:
                spots[-1].append(x)
            else:
                spots.append([x])
        # 上限 = "补出来的探针**最多**能看到几个 base 覆盖之外的位置"(见常量区说明)。
        bump = min(len(spots), LAYOUT_COUNT_MAX_BUMP)
        now = was + bump
        self.last_hand_count = now
        pitch = (base_probes[-1] - base_probes[0]) / float(len(base_probes) - 1)
        # ★ 修正必须留痕(而且要能一眼看出"凭什么"):原以为几张 -> 实读几张、依据是
        #   哪几根并集探针读到了牌、出了选中那条"够得着"的范围多远。
        #   ★★ 为什么还要**单独存一份** `last_count_fix` 并**直接打到控制台**:
        #     `_why()` 写的是 `last_reason`,而它**马上就会被后面那句
        #     `惰性扫描:布局「N 张」…全扫完` 覆盖掉**(实测:不单独留一份的话,
        #     日志里只剩结论、看不到"张数为什么变了" —— 这正是这条要求要防的事)。
        #     控制台那份由 main_loop 落到日志文件里,和 `[记忆] …` 那些行同一个去处。
        self.last_count_fix = self._why(
            f"张数按实读修正:原以为 {was} 张 -> 实读到 {now} 张"
            f"(依据:选中那条的探针铺在 x{base_probes[0]}..x{base_probes[-1]}"
            f"(卡距 {pitch:.0f}px),够得着的范围只到 x{left_reach}..x{right_reach};"
            f"而并集/两端补出来的探针在 x{[s[0] if len(s) == 1 else s for s in spots]} "
            f"处读到了牌 —— 那已经出了它的范围 -> 至少还多 {bump} 张)", debug)
        print(f"    [张数] {self.last_count_fix}")
        return True, was, now

    def _load_layouts(self):
        """载入校准好的手牌布局表(config/hand_layout.json)。"""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "config", "hand_layout.json")
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("layouts", {})
        except Exception as e:
            print(f"hand_layout.json 读取失败: {e}")
            return {}

    @staticmethod
    def _same_card(box, last_box, last_x, x):
        """
        这个探针看到的面板,和上一个探针是不是**同一张卡**。

        判据(实测标定,见 PROJECT_STATE 第 24 条):
          同一张卡的相邻探针:bbox 的 x 完全相同、y 和高度只差几像素
            (251,317,440,403) vs (251,314,440,406)
          换到相邻的卡:    (312,102,444,618) —— 差异巨大
        所以要求 (x, y, height) 三者都接近;再叠一道跨度上限兜底
        (单张牌的热区不可能宽过 MAX_SAME_SPAN)。
        """
        if box is None or last_box is None:
            return False
        near = (abs(box[0] - last_box[0]) <= 10
                and abs(box[1] - last_box[1]) <= 10
                and abs(box[3] - last_box[3]) <= 10)
        return bool(near and abs(x - last_x) <= MAX_SAME_SPAN)

    def _probe_layout(self, entry, max_cards=10, debug=False, probes=None):
        """
        按给定布局表悬停,返回 (results, hits, aborted)。
        aborted=True 表示用户中途操作鼠标,我们让路了。

        ★★ 性能:一张卡的热区会覆盖 4-6 个探针,而每个探针的识别成本是
        OCR ~1.1s + 图标匹配 ~0.6s —— 直接做就是"一张卡六七秒"。
        所以**面板没换就复用上一次的识别结果**(判据 `_same_card`)。
        这是把"每张卡 6 秒"降到 ~2 秒的关键。
        """
        probes = entry.get("probes", []) if probes is None else probes
        results = []
        hits = 0
        t_start = time.time()

        def record(px, info):
            """记一张牌。★ 认不出的牌也要记(否则它等于从手牌里消失)。"""
            results.append({"x": px, "name": info.get("name"),
                            "type": info.get("type"), "cost": info.get("cost"),
                            "unknown": not (info.get("name") or info.get("type")),
                            "info": info})

        # ============ 第一段:只悬停、只测 diff,找出每张卡的面板 ============
        # 这一段**不做任何 OCR/图标匹配** —— 那些是 1.8s/张 的大头,
        # 而一张卡的热区会覆盖 4-6 个探针,直接做就是把同一张卡识别 4-6 次
        # (实测"一张卡平均六秒多"就是这么来的)。
        # 这里只花 ~0.6s/探针的固定等待 + 55ms 截图。
        panels = []          # [{'px', 'box', 'frame'}]
        last_box = None
        last_px = None
        for px in probes:
            if self.user_took_over():
                self._why(f"直扫:第 {len(panels) + 1} 张牌前发现鼠标被别人移走"
                          f" -> 中止让路", debug)
                return [], hits, True
            self._move(*self.safe)
            time.sleep(SAFE_SETTLE)
            base = capture_client_bgr(self.hwnd)
            self._move(px, self.y)
            time.sleep(self.hold)
            hover = capture_client_bgr(self.hwnd)
            if base is None or hover is None:
                continue
            box = diff_bbox(base, hover)
            if box is None:
                last_box = None
                continue
            hits += 1
            # 面板和上一个探针几乎一样 -> 还是同一张卡,第一段就不用重复记
            if (last_box is not None and panels
                    and self._same_card(box, last_box, last_px, px)):
                last_box = box
                continue
            panels.append({"px": px, "box": box, "frame": hover})
            last_box, last_px = box, px
            if len(panels) >= max_cards:
                break

        t_locate = time.time() - t_start

        # ============ 第二段:每张卡只识别一次 ============
        t_ocr = 0.0
        for p in panels:
            bx, by, bw, bh = p["box"]
            t0 = time.time()
            info = self._classify(p["frame"][by:by + bh, bx:bx + bw], y0=by,
                                  box=p["box"], frame=p["frame"], debug=debug)
            t_ocr += time.time() - t0
            record(p["px"], info)
            if debug:
                print(f"      x={p['px']:<5} {info}")

        if debug:
            print(f"      布局「{entry.get('count')} 张」:定位 {t_locate:.1f}s"
                  f"({len(probes)} 个探针 -> {len(panels)} 张卡),"
                  f"识别 {len(panels)} 次共 {t_ocr:.1f}s,"
                  f"总 {time.time() - t_start:.1f}s")
        return results, hits, False

    def scan_fast(self, max_cards=10, debug=False):
        """
        用校准好的坐标表直接悬停,跳过盲扫。

        手牌扇形是居中布局,张数决定每张牌的位置。所以先用左边缘 x 反查张数,
        再按表里的悬停点逐个识别 —— 实测 1 张牌 4.2 秒,而盲扫要 121 秒。

        为什么可能要试两个布局:手牌多到一定程度后扇形不再变宽,
        实测 8 张左边缘 357、9 张 358,只差 1px,单靠边缘分不开。
        所以边缘接近时把候选都试一遍,选命中率高的那个。

        安全兜底(表不准时绝不乱来):
          - 左边缘匹配不到任何布局      -> 回退盲扫
          - 所有候选命中率都低于 60%    -> 回退盲扫
        """
        layouts = self._load_layouts()
        if not layouts:
            self._why("没有 config/hand_layout.json -> 回退盲扫", debug)
            return self.scan(debug=debug)

        self._move(*self.safe)
        time.sleep(SAFE_SETTLE)
        baseline = capture_client_bgr(self.hwnd)
        if baseline is None:
            self._why("基准帧截图失败(capture_client_bgr 返回 None:"
                      "窗口不见了/被最小化?) -> 返回空", debug)
            return []

        from hand_calibrate import detect_left_edge
        edge = detect_left_edge(baseline)
        if edge is None:
            self._why("测不到扇形左边缘(手牌空了,或画面不是对局) -> 回退盲扫",
                      debug)
            return self.scan(debug=debug)

        # 所有在容差内的候选,按接近程度排序
        cands = sorted(
            (v for v in layouts.values()
             if abs(v.get("left_edge", -999) - edge) <= LAYOUT_EDGE_TOL),
            key=lambda v: abs(v["left_edge"] - edge),
        )
        if not cands:
            nearest = min(layouts.values(),
                          key=lambda v: abs(v["left_edge"] - edge))
            self._why(f"左边缘 {edge} 与最近布局({nearest['count']} 张,"
                      f"{nearest['left_edge']})差 "
                      f"{abs(nearest['left_edge'] - edge)}px "
                      f"(>容差 {LAYOUT_EDGE_TOL}) -> 回退盲扫", debug)
            return self.scan(debug=debug)

        # 左边缘只能缩小范围,不能定张数(8/9 张只差 1px,7/8 张差 11px,
        # 而边缘自身波动就有 ±10px)。所以逐个试候选,用命中率定谁对:
        # 张数选对时每个悬停点都该弹面板;选错了就会落在牌缝里。
        if debug:
            print(f"    左边缘 {edge} -> 候选 "
                  f"{[(c['count'], c['left_edge'], abs(c['left_edge'] - edge)) for c in cands]}")

        best = None      # (rate, results, hits, entry)
        for entry in cands[:MAX_CANDIDATES]:
            if debug:
                print(f"    试布局「{entry['count']} 张」{entry['probes']}")
            results, hits, aborted = self._probe_layout(
                entry, max_cards=max_cards, debug=debug)
            if aborted:
                self._why("用户在操作鼠标 -> 中止直扫,让路(本次扫描作废)",
                          debug)
                return []
            n = len(entry.get("probes", []))
            rate = hits / n if n else 0.0
            if debug:
                print(f"      -> 命中 {hits}/{n} ({rate:.0%}),识别 {len(results)} 张")
            if best is None or rate > best[0]:
                best = (rate, results, hits, entry)
            if rate >= CANDIDATE_GOOD_RATE:     # 足够可信,不必再试
                break

        if best is None:
            self._why("没有可用候选 -> 回退盲扫", debug)
            return self.scan(debug=debug)
        rate, results, hits, entry = best
        if rate < 0.6:
            self._why(f"所有候选命中率都低于 60%(最好 {rate:.0%},"
                      f"布局「{entry['count']} 张」)-> 回退盲扫", debug)
            return self.scan(debug=debug)
        if debug:
            print(f"    采用「{entry['count']} 张」布局(命中率 {rate:.0%}),"
                  f"识别出 {len(results)} 张")
        self.last_hand_count = entry.get("count")
        # ★★★ 2026-09-21:命中率挑出来的"最好那条"**也不保证张数对** —— 7/8/9 三条
        #   边缘几乎一样(见 `LAYOUT_PROBE_UNION`),选错的条目照样能 100% 命中。
        #   所以候选不止一条时,把并集里**没走到的位置**补探一遍、结果并进来:
        #   代价是几根探针(~0.6s/根),换来"整手牌一张不漏"。
        if LAYOUT_PROBE_UNION and len(cands) > 1:
            base_probes = list(entry.get("probes", []))
            extra = [x for _i, x in self._probes_for(cands, base_entry=entry)
                     if not any(abs(x - p) <= LAYOUT_PROBE_UNION_DEDUP_PX
                                for p in base_probes)]
            if extra:
                if debug:
                    print(f"    并集补探 {len(extra)} 根: {extra}")
                more, _h2, aborted2 = self._probe_layout(
                    entry, max_cards=max_cards, debug=debug, probes=extra)
                if aborted2:
                    self._why("用户在操作鼠标 -> 中止直扫,让路(本次扫描作废)",
                              debug)
                    return []
                for r in more:
                    if any(abs(r["x"] - s["x"]) <= LAYOUT_PROBE_UNION_DEDUP_PX
                           for s in results):
                        continue
                    results.append(r)
                results.sort(key=lambda r: r["x"])
                if debug:
                    print(f"    补探后共识别 {len(results)} 张")
        if not results:
            self._why(f"布局「{entry['count']} 张」命中率 {rate:.0%} 但"
                      f"一张也没识别出来(面板都在,识别全失败)", debug)
        else:
            self.last_reason = (f"直扫成功:布局「{entry['count']} 张」"
                                f"命中率 {rate:.0%}")
        self.flush_hash_db()      # 把这次学到的指纹写盘(去抖可能还没触发)
        return results

    def scan(self, max_cards=10, debug=False):
        segments = []           # 连续"同一张卡"的段
        baseline = self._baseline()
        found_any = False       # became True once we saw the first card
        empty_run = 0           # consecutive empty probes AFTER finding cards
        last_box = None         # previous probe's panel bbox
        last_info = None        # its classification (OCR is the expensive part)
        cur = None              # the segment being extended
        ocr_calls = 0
        probes = 0              # 真正跑过的探针数(0 探针 = 根本没扫)
        t_start = time.time()
        for x in range(self.x0, self.x1 + 1, self.step):
            # 让路:用户一动鼠标就立刻收手,这次扫描作废(返回空)
            if self.user_took_over():
                self._why(f"盲扫:第 {probes + 1} 个探针就发现鼠标被别人移走 -> "
                          f"中止让路(只扫了 {time.time() - t_start:.1f}s)",
                          debug)
                return []
            probes += 1

            # 回安全点停一下:让上一个悬停面板消失,这样 diff 永远是
            # "干净画面 vs 当前悬停",不必每个探针重拍基准帧。
            self._move(*self.safe)
            time.sleep(SAFE_SETTLE)
            hover = self._hover_frame(x)
            box = diff_bbox(baseline, hover)

            # 固定基准帧的风险:如果对局里有全屏动画(换场景、结算),diff 会
            # 把整个画面当成"变化"。这种时候刷新基准再重试一次。
            if box is not None:
                fh, fw = hover.shape[:2]
                if box[2] * box[3] > 0.5 * fw * fh:
                    baseline = self._baseline()
                    hover = self._hover_frame(x)
                    box = diff_bbox(baseline, hover)

            if box is None:
                # No panel: before first card just keep going (hand may start
                # anywhere); after cards, allow a run of empties then stop.
                cur = None
                last_box = None
                if found_any:
                    empty_run += 1
                    if empty_run > 8:
                        break
                continue
            empty_run = 0

            # 同一个热区内的相邻探针会反复看到同一张卡的面板。OCR 一次要
            # ~1.5s,而一张牌的热区覆盖 4-6 个探针,重复识别是扫描耗时的
            # 大头(实测 5 张牌 121s)。面板没换就复用上次结果。
            #
            # 判据必须严格:实测同一张卡的 diff bbox 是
            # (251,317,440,403) / (251,314,440,406) / (251,312,440,408)
            # —— x 完全相同、y 和高度只差 5px;换卡时是 (312,102,444,618),
            # 差异巨大。之前用 bbox 交并比太宽松(bbox 主要反映"整个手牌区
            # 重排"),结果把 6 张牌全判成同一张 T-70。
            #
            # 另外加一道跨度上限:单张牌的热区不可能宽过 MAX_SAME_SPAN,
            # 超过就强制重新识别。即使判据失效也不会把整手牌合成一张。
            cached = False
            if last_info is not None and last_box is not None and cur is not None:
                near = (abs(box[0] - last_box[0]) <= 10
                        and abs(box[1] - last_box[1]) <= 10
                        and abs(box[3] - last_box[3]) <= 10)
                if near and (x - cur["x0"]) <= MAX_SAME_SPAN:
                    cached = True
            if cached:
                info = last_info
            else:
                bx, by, bw, bh = box
                region = hover[by:by + bh, bx:bx + bw]
                info = self._classify(region, y0=by, box=box, frame=hover,
                                      debug=debug)
                ocr_calls += 1
                last_info = info
            last_box = box
            if debug:
                print(f"    x={x:<4} box={box} -> {info}"
                      f"{' (cached)' if cached else ''}")

            if not (info.get("name") or info.get("type") or info.get("cost")):
                cur = None
                continue

            # ★ 只按"连续"去重,绝不全局去重。
            # 手牌里两张完全相同的牌(实测常见:左一左二是同一张 T-70)在
            # name/type 上不可区分,以前的 `key not in seen` 会把第二张整个
            # 吃掉,导致手牌数少算、少一张可部署的牌。
            # cost 也放进 key:两张都认不出来的牌(name/type 都是 None)靠
            # 费用区分,不然整段会被当成同一张。
            key = (info.get("name"), info.get("type"), info.get("cost"))
            if cur is None or cur["key"] != key:
                cur = {"key": key, "info": info, "x0": x, "x1": x}
                segments.append(cur)
            else:
                cur["x1"] = x
            found_any = True

        # 把每个连续段展开成若干张牌。
        #
        # 同名牌挨着时热区会连成一片(实测左一左二是同一张 T-70),这时用段的
        # 跨度除以单卡间距推断张数:
        #   - 向下取整,宁可少算也不虚高(单张热区跨度实测约 72px,而单卡间距
        #     约 60px,两者接近,用四舍五入很容易把一张牌算成两张)
        #   - 取每个子份的【中心】而不是段的边界:段边界是"探针第一次/最后
        #     一次命中"的位置,不是牌中心
        results = []
        for seg in segments:
            span = seg["x1"] - seg["x0"]
            n = 1 if span <= 0 else max(1, int(span / CARD_PITCH))
            for i in range(n):
                if n == 1:
                    px = (seg["x0"] + seg["x1"]) // 2
                else:
                    px = int(seg["x0"] + (i + 0.5) * span / n)
                results.append({"x": px, "name": seg["info"].get("name"),
                                "type": seg["info"].get("type"),
                                "cost": seg["info"].get("cost")})
                if len(results) >= max_cards:
                    break
            if len(results) >= max_cards:
                break

        if debug:
            print(f"    scan done: {len(results)} cards in {len(segments)} "
                  f"segments, {ocr_calls} OCR passes, {time.time() - t_start:.1f}s")
            for s in segments:
                print(f"      segment x {s['x0']}-{s['x1']} "
                      f"(span {s['x1'] - s['x0']}) {s['key']}")
        # 暴露原始段数据:以后调整 CARD_PITCH 等参数时可以离线重算,
        # 不必重新采集
        self.last_segments = segments
        if results:
            self.last_reason = (f"盲扫成功:{probes} 个探针 -> "
                                f"{len(results)} 张牌")
        else:
            self._why(f"盲扫:{probes} 个探针全扫完,一个悬停面板都没弹出来"
                      f"(鼠标可能没落到手牌上,或者画面根本不是对局)",
                      debug)
        return results

    def flush_hash_db(self):
        """把待落盘的指纹写下去(扫描结束后调一次,避免去抖丢掉最后几条)。"""
        if self._hash_dirty:
            self.hash_db.save()
            self._hash_dirty = False
            self._hash_saved_at = time.time()


if __name__ == "__main__":
    """
    单独测扫描:只悬停读牌,不部署、不点任何东西,所以不会干扰对局。
    用来量扫描耗时和检查识别结果。

      .venv\\Scripts\\python.exe src\\hand_scanner_v2.py            # 扫一次
      .venv\\Scripts\\python.exe src\\hand_scanner_v2.py --repeat 3 # 连扫三次
      .venv\\Scripts\\python.exe src\\hand_scanner_v2.py --debug    # 逐探针明细
    """
    import argparse
    import sys
    import time

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ui_state import load_meta, load_templates
    from win import find_by_process, set_dpi_aware, set_window_client_size

    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true", help="逐探针打印 bbox 和识别结果")
    ap.add_argument("--repeat", type=int, default=1, help="连续扫描次数")
    ap.add_argument("--fast", action="store_true",
                    help="用校准好的坐标表直接悬停(快),失败自动回退盲扫")
    args = ap.parse_args()

    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("no kards window")
        raise SystemExit(1)
    hwnd = wins[0]["hwnd"]
    set_window_client_size(hwnd, 1280, 720, 100, 100)
    time.sleep(1.0)
    _load_db()
    meta_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "config", "templates.json")
    tpls = load_templates(load_meta(meta_path)) if os.path.exists(meta_path) else {}
    sc = HandScannerV2(hwnd, tpls)
    mode = "坐标表直扫(scan_fast)" if args.fast else "盲扫(scan)"
    print(f"模式:{mode}。步长 {STEP},悬停 {HOLD}s,安全点停 {SAFE_SETTLE}s")
    times = []
    for i in range(args.repeat):
        t0 = time.time()
        cards = sc.scan_fast(debug=args.debug) if args.fast else sc.scan(debug=args.debug)
        dt = time.time() - t0
        times.append(dt)
        print(f"\n第 {i + 1} 次:{len(cards)} 张牌,耗时 {dt:.1f}s")
        for c in cards:
            print(f"    x={c['x']:<5}{c.get('name')}({c.get('cost')}) [{c.get('type')}]")
    if len(times) > 1:
        print(f"\n平均 {sum(times) / len(times):.1f}s  "
              f"(最快 {min(times):.1f}s, 最慢 {max(times):.1f}s)")
