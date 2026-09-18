"""
attack.py - M4:让我方单位攻击敌方目标(用户确认的操作方式:**拖拽到目标上松手**)。

★★★ 攻击规则(用户 2026-09-12 当场确认)—— 规则表被整块重写
------------------------------------------------------------------
旧版只有一个 `DIRECT_ATTACKER_TYPES = {fighter, bomber, artillery}`,
把**步兵和坦克一律跳过**,于是实机日志里那条"要上前线的 N 个已跳过"永远出现 ——
而真相是**步兵/坦克也能攻击**,只是打不到远的目标。档案里把游戏原文
"步兵只能攻击相邻战线的敌人。"(限制语气)读成了"步兵不能攻击"。

确认后的完整规则:
  ① 步兵/坦克 在【支援线】  : 只能打**敌方前线那一行**的单位
  ② 步兵/坦克 在【前线】    : 能打**敌方支援线的单位 + 敌方总部**
  ③ 战斗机/轰炸机/炮兵      : 从支援线就能打 敌方前线 / 敌方支援线 / 敌方总部
  ④ 反击:互相结算(我方也受伤),**炮兵和轰炸机除外**
另外两条(§10 第 7 条,实机弹过横幅):
  · **前线被敌方占着,我方就上不去**(「前线已被敌方占领。」);
  · 所以顺序是"先能打相邻战线 -> 才能清掉前线 -> 才能上前线"。

⚠️ ① 这条路**故意还没接**:要落地它必须先能可靠判出"前线那一行是谁的",
   否则就是**去打自己人**(§10 最危险那类错误的镜像)。
   归属判据的标定工具是 `frontline_line.py`,见 §8 P0。

"这个单位这回合还能不能打"
--------------------------
用户给的判据:**卡左上角费用数字 橙 = 还能行动 / 灰 = 本回合已行动**。
所以攻击者只从**橙色费用徽章**里选(见 `unit_state.actionable_units`)。
读不准一律当"不能行动" —— 宁可少打一次,也不要乱拖。

安全兜底(重要)
--------------
1. **自己的单位绝不会被当成攻击目标** —— 目标只从敌方那一侧选
2. **一回合最多 `MAX_ATTACKS` 次**(默认 6)
3. 每次拖拽前后都重读战场
4. 找不到橙色徽章就**不攻击**(`ALLOW_BOX_FALLBACK=False`)
"""

from __future__ import annotations

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np

import board
import deploy as deploy_mod
import unit_state
from actions import park_cursor
from deploy import move_drag
from win import capture_client_bgr, client_to_screen

# ★★ 读战场前是否先把光标停到安全点(2026-09-12 新增,理由见 `Attacker._park`)。
#   留成开关是为了能 A/B:关掉就是旧行为(光标留在上一次的落点上)。
PARK_CURSOR = True

# 一回合最多尝试几次攻击(含被拒绝的)
MAX_ATTACKS = 6
# 拖拽前后画面变化多少才算"这次拖拽被接受了"
BOARD_CHANGE_MIN = 900.0     # 平均绝对差 * 像素数 的量级判据(见 _changed)

# ★★ 找不到橙色费用徽章时,要不要退回"卡框 + 类型"来凑攻击者?**默认不要。**
#   2026-09-11 晚实机:回退这条路让我们拿**本回合刚部署、没有闪击**的轰炸机去打了一次
#   —— 用户给的规则是"费用数字**橙=还能行动**、灰=已行动",刚下场的单位本来就不能行动,
#   它的徽章不是橙的;于是这条回退等于**绕过了唯一可靠的"能不能打"判据**,
#   结果是白拖一次,而且"打没打中"还会退化到不可靠的判据上。
#   项目的原则是"宁可少打一次,也不要乱拖" —— 所以这里 fail-closed:
#   没有橙色徽章就**不攻击**,并把原因写进日志。
ALLOW_BOX_FALLBACK = False

# ★★★ 攻击规则表(用户 2026-09-12 当场确认,**替换掉旧的一行白名单**)
# ---------------------------------------------------------------------------
# 旧代码只有一个 `DIRECT_ATTACKER_TYPES = {fighter, bomber, artillery}`,
# 于是**步兵/坦克一律被跳过** —— 而实机日志里那条"要上前线的 N 个已跳过"
# 就是这么来的。真相是:步兵/坦克**能攻击**,只是打不到远的目标。
#
# 用户确认的四条(游戏里步兵卡面原文:"步兵只能攻击相邻战线的敌人。"):
#   ① 步兵/坦克 在【支援线】:只能打**敌方前线那一行**的单位
#      (打不到敌方支援线,也打不到总部)
#   ② 步兵/坦克 站到【前线】之后:能打**敌方支援线的单位 + 敌方总部**
#   ③ 战斗机/轰炸机/炮兵 在【支援线】:敌方前线 / 敌方支援线 / 敌方总部 **都能打**
#   ④ 反击(用户原话"1,炮兵和轰炸机除外"):攻击会**互相结算**(我方也受伤),
#      但**炮兵和轰炸机不吃反击**
#
# ⚠️ 落地 ① 需要先能**可靠判出「前线那一行是谁的」**(只有敌方占着前线时,
#    那一行的卡才是可打的敌方单位)—— 见 §8 P0 和 `frontline_line.py`。
#    在归属判据标定好之前,这条路**故意不接**:判错的后果是去打自己人,
#    而 §10 把"把敌方单位当成自己人拖"记成这个项目最危险的错误。
# ---------------------------------------------------------------------------
TARGET_ENEMY_FRONT = "enemy_front"        # 敌方前线那一行(= 中间那一行)
TARGET_ENEMY_SUPPORT = "enemy_support"    # 敌方支援线
TARGET_ENEMY_HQ = "enemy_hq"              # 敌方总部
ALL_ENEMY_TARGETS = frozenset({TARGET_ENEMY_FRONT, TARGET_ENEMY_SUPPORT,
                               TARGET_ENEMY_HQ})
# 不需要"前线归属"就能确定的目标(直接在画面上读得到)
OWNERLESS_TARGETS = frozenset({TARGET_ENEMY_SUPPORT, TARGET_ENEMY_HQ})

ROW_SUPPORT = "support"                   # 单位站在我方支援线
ROW_FRONT = "front"                       # 单位站在前线

FROM_SUPPORT_TARGETS = {
    "fighter": ALL_ENEMY_TARGETS,
    "bomber": ALL_ENEMY_TARGETS,
    "artillery": ALL_ENEMY_TARGETS,
    "infantry": frozenset({TARGET_ENEMY_FRONT}),
    "tank": frozenset({TARGET_ENEMY_FRONT}),
}
FROM_FRONT_TARGETS = {
    "infantry": frozenset({TARGET_ENEMY_SUPPORT, TARGET_ENEMY_HQ}),
    "tank": frozenset({TARGET_ENEMY_SUPPORT, TARGET_ENEMY_HQ}),
    "fighter": ALL_ENEMY_TARGETS,
    "bomber": ALL_ENEMY_TARGETS,
    "artillery": ALL_ENEMY_TARGETS,
}
# ★ 不吃反击的类型(用户原话:"1,炮兵和轰炸机除外")
NO_RETALIATION_TYPES = frozenset({"artillery", "bomber"})

# ★★★ 2026-09-12(第七个会话)"守护 / 拦截"的**保守版** —— 不需要任何新的图像判据
# ---------------------------------------------------------------------------
# 背景(用户补充的两条规则 + 实机证据,见 §10 和 §8 候选第 -3 条):
#   · **守护**:敌方守护单位放在总部旁边 -> 总部吃到守护特效,**必须先把那个单位打掉**
#     才能打总部;
#   · **拦截**:敌方支援线上有战斗机时,我方**轰炸机**的攻击会被拦截。
#   ＊ 这两条的**精确版**都要先能认出"哪张卡带守护"(需要卡面标记的模板,
#     见 `guard_probe.py` 的只读预检 + 用户提供的标记位置)。
#   ＊ 但两条的**表现是同一种**:"拖过去了,却一点伤害都没有" ——
#     所以先用**行为**把代价削掉:
#
#     **打总部一旦没有掉血 -> 本回合把"总部"这一档对非炮兵封掉。**
#
# 为什么这么定(每一条都有实机依据,不是拍的):
#   ① 第 7 局:fighter ×4 + infantry ×2 打敌方总部**全部"没打中"**,
#      而 artillery ×3 **全部打进去**(`13->11`/`11->9`/`16->14`),
#      也就是同一局里**只有炮兵打得动** -> 所以炮兵**不封**,继续试;
#   ② 封的是"**总部**"这一档,不是封那个单位 —— 别的目标没有守护特效这回事,
#      封掉之后 `_pick_target` 会自然往下走(敌方支援线单位 / 敌方前线),
#      而那正是"先打掉守护单位"的方向;
#   ③ 只在**读到硬判据**(出手前后血量都是有效读数、而且一动不动)时才封 ——
#      血量读不到时**不封**(那说明判据弱,不能据此下结论,§7 第 65 条)。
# 代价不对称且偏向安全侧:万一封错了,代价是**本回合少打一次总部**;
# 不封的代价是**每个单位每回合各白拖一次**(本项目头号要消除的行为)。
HQ_BLOCK_AFTER_MISS = True
# 封了之后还允许继续试总部的类型(实机证据:只有炮兵打得进去)
HQ_BLOCK_EXEMPT_TYPES = frozenset({"artillery"})

# ★★★ 2026-09-13 深夜(第十一个会话):**"总部卡从画面上消失了" = 打掉了。**
# ---------------------------------------------------------------------------
# 背景(实机,2026-09-12 第二局):敌方总部只剩 **1** 血,我方炮兵打过去,
# **11 秒后 `state -> victory`** —— 也就是说那一发**把总部打掉了**,
# 而日志把它写成了:
#     `[attack] #3 被拒绝(血量读不到,画面几乎没变 5)`
# 机理:总部被摧毁的那一帧上,血量数字/盾牌已经没了(`hp_after=None`),
# 于是退回**画面差异**那条弱判据(§7 第 46 条早就证明它会骗人),
# 而伤害动画恰好让 diff 很小 -> 记成"被拒绝"。
# ★ 其实**最硬的信号就在手里**:出手之前总部卡明明在那儿(是 `find_enemy_hq`
#   自己找到的),出手之后再找一遍,连盾牌/行内数字/卡名**三条判据全都找不到** ——
#   那张卡已经不是"读不出来",是**不在了**。
#
# 判据(两条一起,缺一不可 —— 防止把"遮挡/读不到"当成"没了"):
#   ① **敌方那一行还读得到**(`read_field` 有行结构、有卡)-> 排除"整帧读不到"这种假象;
#   ② 用**同一套** `board.find_enemy_hq`(盾牌 -> 行内 OCR -> 卡名)在**出手之后**那一帧
#      找不到任何总部卡。
#   ★ 用**晚读那一帧**(`LATE_HP_WAIT` 之后,伤害飘字/死亡动画已经放完)-> 比出手瞬间那帧可靠。
# 代价/风险(写清楚,不装作没有):判错只会错在**统计**(`landed` 少算/多算一次),
#   不会导致错的动作 —— 下一轮循环照样会**重新找一遍**总部,真活着就继续打它。
#   设 False 一键退回老行为。
HQ_GONE_IS_KILL = True

# ★★★ 2026-09-13 深夜(实机 J2 逐发对账抓到的**最贵的一条**):
#   **"没打中"里每一次其实都打中了 —— 血量数字更新得比我们的"晚读"还慢。**
#
# 实机原文(J2,把每一发的"出手前血量"按顺序排出来就一目了然):
#   21:16:03 出手前 20 -> 判"没打中(仍是 20)"   [顺手封掉总部这一档]
#   21:17:22 出手前 **15**  <- 20->15,**上一发打掉了 5 点**
#   21:18:13 出手前 10 -> 判"没打中(仍是 10)"   [又封]
#   21:18:24 出手前 **5**   <- 10->5,又打掉了 5 点
#   21:19:07 出手前 **2**   <- 5->2,又打掉了 3 点;这一发就是制胜一击
# 也就是说:伤害**确实生效**,只是**盾牌上的数字还没刷新**(现在只等
# `ATTACK_SETTLE + LATE_HP_WAIT ≈ 1.4s` 就下结论了)。
#
# 代价(为什么必须修):每误判一次就 `HQ_BLOCK_AFTER_MISS` **封掉总部这一档**,
#   本回合剩下的非炮兵**全都不再打总部** —— 等于把自己已经打中的伤害当成"打不动"。
#
# 判据:**别急着下"没打中"的结论** —— 先把血量盯住,看它会不会自己掉下来。
#   ★ 实机实测(2026-09-13 21:44,新探针第一次跑):
#       `血量跟踪:+1.2s=15 -> **掉血了**(数字是隔几秒才刷新的)`
#     —— 也就是说**刷新只比老的"晚读"(约 0.9s)晚一点点**,我们那一帧正好差过去。
#     所以窗口不用开很大:4 秒 = 实测 1.2s 的三倍余量,一看到掉血就提前收工。
MISS_HP_VERIFY_S = 4.0      # 判"没打中"之前最多再盯这么久(每秒读一次)
MISS_HP_TRACE = True        # 把盯的过程写进日志(先量再改:这一条是量出来的)

# ★★★ 2026-09-15(复验那轮实机抓到 3 次):**晚读读到"不可能的血量"时不许直接当结论。**
#   证据:`17 -> 20`、`11 -> 20`、`10 -> 87`(19:45:49 / 19:46:02 / 19:48:39)。
#   总部血量**不会变多**(上限就是 20,`87` 尤其离谱)-> 那是**读数错了**,
#   而旧代码把晚读当权威("以晚读的为准"),于是把**已经打中**的那一发写成
#   "结论不可信,按'没打中'处理"。第 3 发最可惜:出手后立刻读到 10(和出手前一样),
#   而**下一发**出手前读到 7 —— 说明那一发确实打进了 3 点。
#   开着:先**重新定位总部**读一次,再退回"出手后立刻"那次;都不行才维持原判。
#   关掉:旧行为(A/B 用)。
HP_BOGUS_RECOVER = True
#: 把"读到不可能的值"那一帧存到 `shots/hp_bogus/`(下一次再出现就有像素可量)。
DUMP_HP_BOGUS = True

# ★★★ 2026-09-13 深夜:**打单位也要有硬判据 —— 用"我方单位徽章由橙变灰"。**
#
# 问题(用户 2026-09-13 提出"先把打单位的问题解决一下"):
#   单位卡上**没有能读的血量数字**(那是总部卡才有的盾牌),所以"打中了没有"
#   一直只有"那一行还剩几张卡"这一条 —— **打伤但没打死就完全判不出来**,
#   日志只能写"结论不可信"(实机 J2 报了 **9 次**)。
#
# 判据(§7 第 74 条,用户确认过的规则):**橙 = 本回合还没行动过**。
#   拖之前是橙、拖之后**变灰** -> 游戏**接受了**这次行动;
#   拖之后**还是橙** -> 这次拖拽**被拒绝了**(守护/烟幕/规则不允许)。
#   ★ 这条信号是**现成的**:引擎每一轮本来就在读徽章(用它挑攻击者)。
#
# 实测依据(实机 J1~J4 全部 17 次打单位的拖拽,逐条把"拖前/拖后的橙色徽章集合"对出来):
#   **17/17 拖完之后我方都有一个橙色徽章变灰** ——
#   也就是说那 9 次"结论不可信"其实都是"打伤了、没打死",而且**一次都没白拖**。
#   (对照:同一批数据里没有一次"拖完还是橙"——那种才是真被拒绝。)
# 设 False 一键退回"只有那一行还剩几张卡"的老判据。
HIT_BY_BADGE = True

# ★★★ 2026-09-13 深夜:**打单位之前先看它是不是"被守护"。**
#   实机(存帧 `shots/attack_frames/0913_232500_after.png`):游戏弹出
#   **"此单位具有『被守护』。"** 并把拖拽拒绝了 —— 连跑三局里这样的白拖 **4 次**。
#   判据:**现成的**(`guard.glyph_at`)—— `which=="hq"`(半盾+框)= 被守护,去掉了;
#   `which=="unit"`(实心盾)= 守护单位,允许打而且优先打。
#   设 False 一键退回"不看守护标记,照打"(老行为)。
PROTECTED_SKIP = True

# ★★★ 2026-09-13 深夜(**用户实测**):**目标卡会动 —— 出手前必须重新定位。**
#   用户原话(第二局第 13 回合):"对面前线单位被我方打掉一个,仅剩的另一张前线单位
#   **移到中间**的时候触发的攻击,这时攻击指向**还在原位置**"。
#   -> 往旧坐标拖 = 拖到空地上,游戏直接拒绝(整发白拖)。
#   修法:出手前再看一帧,把落点更新到那张卡**现在**的位置;差得太多(> `RELOCATE_TOL`)
#   就跳过这一发、下一轮重选。设 False 退回"照旧坐标拖"。
RELOCATE_BEFORE_ATTACK = True
RELOCATE_TOL = 120        # 目标卡离原位置多远之内还算"同一张(挪了一下)"

# ★★★ 2026-09-12(第七个会话)**战斗机拦截轰炸机**(用户逐条确认,§10)
# ---------------------------------------------------------------------------
# 用户原话:"这一次实战**我方轰炸机没有打中对方总部**,原因是对方支援阵线存在
# **战斗机**,而**战斗机会拦截轰炸机的攻击**。"
# 追问之后用户把范围定死(2026-09-12):
#   · **拦哪几档**:"**总部 + 敌方支援线单位都拦**"(轰炸机只剩"打敌方前线"这条路);
#   · **被拦的机型**:"**只有轰炸机**";
#   · ★ 顺带确认:**守护对【战斗机】也生效** —— 所以 `HQ_BLOCK_EXEMPT_TYPES`
#     只放炮兵是对的(战斗机/步兵/坦克都会被守护挡住)。
#
# ★ 判据是**现成的**:`board.read_field(templates=…)` 已经在给敌方支援线每张卡认类型,
#   实测同一帧就能读出 `x443 fighter / x728 artillery / x586 infantry`
#   —— **不需要任何新的图像工作**(这也是用户当初说"这条成本不高"的原因)。
# ★ 这条**不做保守版**:它是纯规则,判据(类型)已经在手上,而且方向是"少拖"。
INTERCEPTOR_TYPES = frozenset({"fighter"})       # 谁会拦(目前只有战斗机)
INTERCEPTED_ATTACKERS = frozenset({"bomber"})    # 谁会被拦(目前只有轰炸机)

# ★★★ 2026-09-13(第八个会话)**提速**:每段"拖完之后的等待"收短一点。
#   动机(用户):"对局时间还是太长了,不够拟人" —— 实测我方**一个回合 30~101 秒**
#   (平均 62.6s),其中"拖拽本身 + 拖完的等待 + 验证读"占大头:
#   一个回合要拖 6~8 次(部署 3 + 攻击 2 + 上前线 1~2),每拖一次前后各有固定等待。
#   ★ 这些等待**不是随便砍的**:它们的作用是"等游戏把这次动作结算完,再去读战场验证",
#     所以宁可保守 —— 下面的值都留了余量,而且**改完要实机复测**
#     (看 `部署被拒` / `没打中` / `卡数异常` 有没有变多,那才是"等太短"的症状)。
ATTACK_SETTLE = 0.5      # 攻击松手后、读战场前(原 1.1)
MOVE_SETTLE = 0.6        # 移动/上前线松手后(原 1.2)
LATE_HP_WAIT = 0.9       # 打总部之后"晚读一次血量"的间隔(原 1.5,见 §7 第 81 条)

# ★★★ 2026-09-13(实机 + 用户逐回合观察):**对手打出的牌会在屏幕正中停几秒**, 
#   把【前线那一行】整条盖住 —— 行结构于是只剩 2 行 -> `front_row()` 返回 None
#   -> 语义判据判成 `empty` -> 攻击阶段"够不着目标"一个都不打;
#   而 2 秒后 `move_front` 再读(展示已消失)又判成 `enemy` -> 不许上前线。
#   ⇒ 单位整回合干站着(用户看到的第九/十一回合)。
#   重读一次要等多久:展示卡实测持续 2~4 秒,一次等太久没意义,
#   所以**只重读一次**、等这么久;真还在展示就在日志里留一行,不硬等。
DISPLAY_CARD_SETTLE = 1.2

# ★★★ 2026-09-13(用户要求):**轰炸机在敌方没有战斗机时,50% 概率先打前线单位。**
#   用户原话:"轰炸机在对方没有战斗机守护的情况下可以增加一条 50% 概率打前线单位。"
#   · 只在**不会被拦截**时掷骰(被拦截的轰炸机本来就只剩前线这一条路);
#   · 目的:总部打不动(守护 / **烟幕**)时别每回合都往同一个目标上撞,顺手清前线。
#   · 0.0 = 老行为(永远优先总部);1.0 = 总是先打前线。
BOMBER_FRONT_CHANCE = 0.5
BOMBER_FRONT_TYPES = frozenset({"bomber"})

# 我方前线的落点 y(实测前线卡在 y455-545 这一带)。
# 用户确认:**前线最多 5 个,满了上不去**。
FRONT_LINE_DROP_Y = 500
FRONT_LINE_MAX = 5


def attack_targets(ctype, from_row) -> frozenset:
    """
    这个类型的单位,**站在这一行**时能打哪些目标(目标用上面的 TARGET_* 表示)。

    ★ 类型未知 / 行未知 -> **返回空集**(fail-closed):不知道是什么、也不知道站在哪,
      就一个目标都不许打。调用方据此拒绝出拖。
    """
    if ctype is None or from_row not in (ROW_SUPPORT, ROW_FRONT):
        return frozenset()
    table = FROM_SUPPORT_TARGETS if from_row == ROW_SUPPORT else FROM_FRONT_TARGETS
    return table.get(ctype, frozenset())


def can_attack_target(ctype, from_row, target_kind) -> bool:
    """这一类单位从这一行出发,能不能打这个目标。"""
    return target_kind in attack_targets(ctype, from_row)


def takes_retaliation(ctype) -> bool:
    """
    这个单位攻击后会不会**被反击**(吃到对方的反击伤害)。

    用户确认:会互相结算,**炮兵和轰炸机除外**。
    ★ 类型未知时按"会吃反击"处理(保守:不主动拿它去换)。
    """
    return ctype not in NO_RETALIATION_TYPES


def can_attack_from_support(ctype) -> bool:
    """
    这类单位从支援线出发,能不能打到**"敌方支援线 / 敌方总部"**这一档目标。

    ★★ 语义已按用户 2026-09-12 的规则修正:**这不再是"能不能攻击"**。
      步兵/坦克**也能攻击**(打敌方前线那一行),只是打不到远处的这一档。
      要问"从支援线出发有没有任何合法目标",用
      `attack_targets(ctype, ROW_SUPPORT)` 是不是空集。
    """
    return can_attack_target(ctype, ROW_SUPPORT, TARGET_ENEMY_SUPPORT)


def needs_front_line(ctype) -> bool:
    """
    这类单位是不是"从支援线打不到远处的目标"(也就是说:想打支援线/总部必须先上前线)。

    ★ 类型未知 -> False:不知道是什么就**不下结论**(调用方那一路本来就 fail-closed)。
    """
    if ctype is None:
        return False
    return not can_attack_from_support(ctype)


def move_unit_to_front(hwnd, src, dst=None, log=print):
    """
    把一个单位从【支援线】拖到【前线】的空位(用户确认的操作方式)。

    用户 2026-09-11 说明:
      - 移动 = **把单位拖到前线的空位**
      - **前线最多 5 个,满了上不去**

    返回 (ok, detail)。dst=None 时用 `deploy.random_drop_point()` 那个落点带
    (实测 y 420-500 在支援线/前线上,两者相邻,所以这里默认拖到前线带的下半部)。

    ★ 这个动作**还没在实机上验证过** —— 第一次跑请盯日志和画面。
    """
    dx, dy = dst if dst else (src[0], FRONT_LINE_DROP_Y)
    sx, sy = client_to_screen(hwnd, src[0], src[1])
    ex, ey = client_to_screen(hwnd, dx, dy)
    log(f"[move] 把单位 x{src[0]}@y{src[1]} 拖到前线 ({dx},{dy})")
    move_drag(sx, sy, ex, ey)
    time.sleep(MOVE_SETTLE)
    return True, {"src": src, "dst": (dx, dy)}


# ★★ 诊断用:把攻击阶段那一帧存下来(便于事后逐帧核对"徽章到底有没有/判成什么")。
#   为什么要有上限:这个函数在**每个攻击阶段**都会跑,而**离线用例也会跑攻击阶段** ——
#   实测一次 `turn_logic_test` 就能写出几十张整帧(每张 ~300KB),24MB 就这么来的。
#   所以:① 目录只保留最新的 DUMP_MAX_FRAMES 张;② 离线用例把它关掉。
DUMP_ATTACK_FRAMES = True
DUMP_MAX_FRAMES = 40


def _changed(before, after, scale: float = 0.02):
    """
    两张整帧是否"有实质变化"。

    判据用"缩小后的平均绝对差":直接比全分辨率会被抗锯齿噪声干扰,
    缩小 1/4 再去噪之后再比,阈值也更好定。
    """
    if before is None or after is None or before.shape != after.shape:
        return None
    a = cv2.resize(before, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    b = cv2.resize(after, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return float(cv2.absdiff(a, b).mean())


# ---------------------------------------------------------------------------
# ★★★ "上前线"(2026-09-12 新增) —— 用户确认的顺序:
#   **先能打相邻战线 -> 才能清掉前线 -> 才能上前线。**
#
# 为什么必须做(实机证据,不是推测):
#   上一局 12 个攻击阶段全是"没有能攻击的单位",而 `徽章全表` 显示我方单位的
#   **橙色徽章读得好好的**(S=166~179,阈值只要 120)。被跳过的原因写在日志里:
#   `归属已读出但不是敌方的 N 个 已跳过` —— 步兵/坦克从支援线**只能打敌方前线
#   那一行**,而前线大多数时候是**空的**。于是它们够不着任何东西,
#   而引擎又没有"把单位挪上去"这一步 -> 一整局一次都打不出去。
#
# 规则(用户 2026-09-12 确认):
#   · 移动 = **把单位拖到前线的空槽位**;
#   · **前线最多 5 个**,满了上不去;
#   · **前线被敌方占着,我方就上不去**(实机弹过横幅「前线已被敌方占领。」)。
#
# ★ 安全约定(全部 fail-closed —— 判错的后果是白费一个单位的行动,甚至乱拖):
#   · **前线归属读不出来 -> 不动**(只在 `our` / `neutral` 时才敢上);
#   · 前线归属是 `enemy` -> 不动(游戏会拒绝,白拖一次还得回手);
#   · 前线已满(那一行 ≥ FRONT_LINE_MAX 张)-> 不动;
#   · 只有**橙色徽章**(这回合还能行动)的**步兵/坦克**才上 ——
#     飞机/炮兵站在支援线就能打,不需要上前线;
#   · 总部卡永远不动(它不能出战)。
# ---------------------------------------------------------------------------
MOVE_TO_FRONT_MAX = 3       # 一个回合最多挪几个单位上前线
# ★ 2026-09-12(第六个会话)**用户当场确认的规则**:"谁都能上,只要**付得起行动费**;
#   上限是**前线最多 5 个**"。所以这里不该是 1 —— 实测(第一局 15:28)前线刚被清空、
#   我方还有 2~3 个橙色步兵/坦克,引擎**只挪了 1 个**就进结束回合,白白放掉这些行动。
#
# ★ 为什么是 3 而不是 5:这个常数是**跑飞护栏**,不是规则上限。真正的限制有三条,
#   而且都在循环里逐次复查(fail-closed):
#     ① 每挪一个都要重新抓帧 + 重新挑人 —— 挪过的单位徽章变灰,不会被重复挑中;
#     ② **费用归零时我方全场徽章一起变灰**(§7 第 74 条),于是 `_pick_advancer`
#        自然挑不出人 -> 循环自己停下,**不需要引擎再传预算进来**;
#     ③ 任何一次"没动成"都会 `break`(见 `run_turn`),不会连续乱拖。
#   取 3 是"一回合多占两格"和"别把行动一次烧光"之间的折中;前线容量仍是 FRONT_LINE_MAX=5。
# 需要"上前线"才能打到东西的类型 —— 就是"从支援线够不着远处目标"的那些。
# 直接从规则表推,不另抄一份名单(否则两处会静默不一致,§7 第 60 条踩过)。
NEEDS_FRONT_TYPES = frozenset(
    t for t in FROM_SUPPORT_TARGETS if not (FROM_SUPPORT_TARGETS[t] & OWNERLESS_TARGETS)
)


class FrontMover:
    """
    "上前线"阶段的协调者:把**够不着目标**的步兵/坦克挪到前线空槽位。

    用法(在 `turn_engine` 的 attack 阶段之后):
        mv = FrontMover(hwnd, log=log, templates=templates)
        mv.run_turn(hard_stop=lambda: not end_turn_button_visible())
    """

    def __init__(self, hwnd, log=print, debug=False, templates=None,
                 max_moves=MOVE_TO_FRONT_MAX):
        self.hwnd = hwnd
        self.log = log
        self.debug = debug
        self.templates = templates
        self.max_moves = max_moves
        self.moved = 0
        self.tried = set()
        self.refused = 0
        # ★ 跨回合累计(**不随 reset_turn 清零**)—— §7 第 44 条:
        #   `think()` 点完结束回合会 `reset_turn()`,把回合内计数清零,
        #   于是在循环跑完之后断言"回合内计数"必然失败、而且看起来像功能坏了。
        #   要断言"这件事发生过",就数这个。
        self.moved_all = 0
        self.refused_all = 0

    def reset_turn(self):
        self.moved = 0
        self.tried = set()
        self.refused = 0

    # ---- helpers ----
    def _frame(self):
        return capture_client_bgr(self.hwnd)

    def _park(self):
        """读战场前先把光标停到安全点 —— 理由见 `Attacker._park`(同一个坑)。"""
        if PARK_CURSOR:
            park_cursor(self.hwnd)

    def _frontline_owner(self, frame):
        try:
            import frontline_line
            return frontline_line.read_frontline_owner(frame=frame)
        except Exception as e:
            return {"owner": None, "why": f"归属判据出错({type(e).__name__}: {e})"}

    def _pick_advancer(self, frame, field):
        """
        挑一个"该上前线"的单位,返回 {src, type, key, badge} 或 None。

        条件(缺一不可):
          ① 在**我方支援线**上(绝不动别的位置的卡);
          ② 徽章是**橙色**(这回合还能行动);
          ③ 类型是 **infantry / tank**(飞机/炮兵站支援线就能打,不用上去);
          ④ 它**没有可打的目标**(能打的应该去打,不该浪费行动去移动)——
             用 `attack_targets()` 判断:支援线上够得着"敌方支援线/总部"的类型不算。
        """
        own = []
        try:
            import unit_state
            own = unit_state.actionable_units(frame, templates=self.templates,
                                              debug=self.debug)
        except Exception as e:
            self.log(f"[move] 徽章判据出错({type(e).__name__}: {e})")
            return None
        # 我方支援线那一行的 y 范围(按行信息;拿不到就退回 our_support 的包围盒)
        rows = field.get("rows") or []
        our_rows = [r for r in rows if r.get("side") == "our"]
        if our_rows:
            r = our_rows[-1]
            y0, y1 = r["y0"] - 40, r["y1"] + 40
        else:
            boxes = field.get("our_support") or []
            if not boxes:
                return None
            y0 = min(b["y"] for b in boxes) - 40
            y1 = max(b["y"] + b["h"] for b in boxes) + 40
        scored = []
        for u in own:
            by = u["badge"]["y"]
            if not (y0 <= by <= y1):
                continue                      # ① 不在我方那一行
            ctype = u.get("type")
            if ctype is None:
                continue                      # 类型不明 -> 不动(和攻击同样保守)
            if ctype not in NEEDS_FRONT_TYPES:
                continue                      # ③ 飞机/炮兵不用上
            # ④ 它支援线上就有目标吗?有就去打,别用来移动
            if attack_targets(ctype, ROW_SUPPORT) & OWNERLESS_TARGETS:
                continue
            key = (u["badge"]["x"], u["badge"]["y"])
            if key in self.tried:
                continue
            scored.append((u["badge"]["x"], u, key))
        if not scored:
            return None
        scored.sort(key=lambda t: t[0])
        _x, u, key = scored[0]
        return {"src": u["src"], "type": u["type"], "key": key,
                "badge": u["badge"]}

    def run_turn(self, hard_stop=None):
        """
        挪单位上前线。返回 (moved, refused)。

        ★ "动成功了"的判据按 §12 清单第 3 条的教训做硬:**我方那一行 −1
          **并且** 前线那一行 +1**。旧脚本只看"我方那一行少了"就判成功,
          而实测同时出现 `前线 3->3` —— 单位离开了支援线却没出现在前线,
          到底去哪了没确认。只看一个方向的计数变化是 §7 第 46 条同一种错。
        """
        for _ in range(max(0, self.max_moves)):
            if hard_stop is not None and hard_stop():
                self.log("[move] 我方回合结束,停止上前线")
                break
            self._park()
            frame = self._frame()
            if frame is None:
                break
            field = board.read_field(frame, templates=self.templates,
                                     debug=self.debug)

            # ---- 前提一:前线不能是敌方的(用户确认:敌方占着我方上不去)----
            info = self._frontline_owner(frame)
            owner = info.get("owner")
            if owner is None:
                self.log(f"[move] 前线归属读不出({info.get('why')})-> 不上前"
                         f"(fail-closed:判错就是白拖/被游戏拒绝)")
                break
            if owner == "enemy":
                self.log("[move] 前线是敌方的 -> 不上前(游戏会弹"
                         "「前线已被敌方占领。」并拒绝);先打相邻战线清掉它")
                break

            # ---- 前提二:前线没满(用户确认最多 5 个)----
            frow = board.front_row(field)
            if frow is not None and len(frow["boxes"]) >= FRONT_LINE_MAX:
                self.log(f"[move] 前线已满({len(frow['boxes'])}/{FRONT_LINE_MAX})"
                         f"-> 不上前")
                break

            # ---- 挑人 ----
            adv = self._pick_advancer(frame, field)
            if adv is None:
                self.log("[move] 没有需要上前线的单位(没有「够不着目标」的"
                         "橙色步兵/坦克)")
                break
            self.tried.add(adv["key"])

            # ---- 落点:前线那一行的空槽位(y 现算,绝不用写死的常数)----
            fcy = board.front_line_cy(field)
            ocy = None
            our_rows = [r for r in (field.get("rows") or [])
                        if r.get("side") == "our"]
            if our_rows:
                ocy = our_rows[-1]["cy"]
            if fcy is None:
                self.log("[move] 算不出前线那一行的 y -> 不上前(fail-closed)")
                break
            if ocy is not None and fcy >= ocy - 40:
                # 前线那一行居然不低于我方支援线 -> 行结构读错了,别拖
                self.log(f"[move] 行结构可疑(前线 cy={fcy:.0f} 不高于我方支援 "
                         f"cy={ocy:.0f})-> 不上前(fail-closed)")
                break
            occupied = [int(u["cx"]) for u in (frow.get("units") or [])] if frow else []
            cands = deploy_mod.slot_candidates(occupied, int(fcy))
            if not cands:
                self.log("[move] 前线那一行算不出空槽位 -> 不上前")
                break

            n_sup_before = len(field.get("our_support") or [])
            n_front_before = len(field.get("frontline") or [])
            dx, dy = cands[0]
            self.log(f"[move] 上前线:我方 {adv['type']} x{adv['src'][0]}@"
                     f"y{adv['src'][1]} -> 前线空槽位 ({dx},{dy})"
                     f"(前线行 cy={fcy:.0f};归属={owner})")
            try:
                move_unit_to_front(self.hwnd, adv["src"], dst=(dx, dy),
                                   log=lambda m: None)
            except Exception as e:
                self.log(f"[move] 拖拽出错({type(e).__name__}: {e})-> 停止")
                break
            time.sleep(MOVE_SETTLE)

            self._park()
            after = self._frame()
            if after is None:
                break
            field2 = board.read_field(after, templates=self.templates)
            n_sup_after = len(field2.get("our_support") or [])
            n_front_after = len(field2.get("frontline") or [])
            if n_sup_after < n_sup_before and n_front_after > n_front_before:
                self.moved += 1
                self.moved_all += 1
                self.log(f"[move] 动成功了(我方支援 {n_sup_before}->{n_sup_after}"
                         f" 且 前线 {n_front_before}->{n_front_after})")
            else:
                self.refused += 1
                self.refused_all += 1
                # ★ 只变一个方向 = **不能算成功**(§12 清单第 3 条那个坑:
                #   实测出现过"我方少一张、前线 3->3",单位去哪了没确认)
                self.log(f"[move] 没动成:我方支援 {n_sup_before}->{n_sup_after},"
                         f"前线 {n_front_before}->{n_front_after}"
                         f"(判据要求**两边都变**:−1 且 +1)")
                break
        return self.moved, self.refused


class Attacker:
    """
    一次攻击尝试的协调者。

    用法(在 turn_engine 的 play 阶段之后):
        atk = Attacker(hwnd, log=log)
        atk.run_turn(hard_stop=lambda: end_turn_button_gone())
    """

    def __init__(self, hwnd, log=print, debug=False, max_attacks=MAX_ATTACKS,
                 templates=None):
        self.hwnd = hwnd
        self.log = log
        self.debug = debug
        self.max_attacks = max_attacks
        self.templates = templates   # 需要它来认场上单位的类型(攻击规则依赖类型)
        self.tried = set()          # 已经试过的"我方单位"坐标
        self.attempts = 0
        self.landed = 0
        # ★★ 2026-09-12 实机发现:这两个原因原来**共用一个计数器**,
        #   日志写成"需先上前线的 N 个已跳过" —— 而其中可能有一个是**类型没认出来**,
        #   两者的处置完全相反(前者是规则,后者是要去补的活)。
        #   实机那一局就是:唯一一个橙徽章被跳过,日志说"要上前线",
        #   真相不明 —— 而"类型识别"正是 §12 清单第 4 条没做完的事。
        self.skipped_needs_front = 0    # 规则上必须上前线才能打(目前几乎恒为 0)
        self.skipped_unknown_type = 0   # 类型认不出来(要补的活)
        # ★★ 2026-09-12 新增第三个桶:**"能打,但前线归属读不出"**。
        #   步兵/坦克在支援线上,规则允许它打敌方前线那一行 —— 但要先知道
        #   那一行是不是**敌方的**(§8 P0)。在没有归属判据之前,这不是"规则使然",
        #   而是**我们自己没做完的活**,所以**不许**并进 `needs_front` 里
        #   (那就是 §7 第 68 条 C 那个"日志在撒谎"的翻版)。
        self.skipped_no_front_owner = 0
        # ★ 跨回合的累计(不随 reset_turn 清零)。
        #   为什么要它:§7 第 44 条 —— `think()` 点完结束回合会 `reset_turn()`,
        #   把回合内计数清零,于是"循环跑完再断言回合内计数"必然失败、
        #   而且看起来像功能坏了。**要断言"发生过"就数跨回合累积的量。**
        self.skipped_needs_front_all = 0
        self.skipped_unknown_type_all = 0
        self.skipped_no_front_owner_all = 0
        # ★★ 2026-09-12(第七个会话):本回合"总部这一档"有没有被(非炮兵)封掉 ——
        #   起因见 `HQ_BLOCK_AFTER_MISS` 上面的说明。跨回合累计的那个只做诊断,
        #   用来回答"这条保守规则今天到底省了几次白拖"。
        self.hq_blocked = False
        self.hq_blocked_reason = None
        self.hq_blocked_all = 0
        # 本回合因为"总部被封"而没能打出去的次数(诊断)
        self.blocked_hq_skips = 0

    def reset_turn(self):
        self.tried = set()
        self.attempts = 0
        self.landed = 0
        self.skipped_needs_front = 0
        self.skipped_unknown_type = 0
        self.skipped_no_front_owner = 0
        self.hq_blocked = False
        self.hq_blocked_reason = None
        self.blocked_hq_skips = 0

    # ---- helpers ----
    def _frame(self):
        return capture_client_bgr(self.hwnd)

    def _park(self):
        """
        读战场前先把光标停到安全点(见 `actions.park_cursor` 的说明)。

        ★ 为什么非做不可(2026-09-12 实机):上一次拖拽把光标留在落点上,
          KARDS 会弹**放大的悬停面板**,把旁边那张卡**整张盖住** ——
          实测那一帧我方支援线 2 张卡只检出 1 张、徽章 0 个,
          于是"看不到橙色" -> 既不攻击也不上前线,支援线单位数也只能靠
          "行卡数−1"兜(4 个读成 2~3)。用户的实机日志逐条对上了这个因果链。
        """
        if PARK_CURSOR:
            park_cursor(self.hwnd)

    def _frontline_owner(self, frame):
        """
        读一次"前线那一行是谁的"(用户 2026-09-12 给的判据:那条**黑线**靠上=友方、
        在下边=敌方;工具/判据在 `frontline_line.py`)。

        ★ 为什么这件事必须先做:§10 写着"**把敌方单位当成自己人拖**是这个项目
          最危险的错误",而"把**我方**单位当成敌人打"是它的镜像 —— 两者都源自
          "不知道那一行是谁的"。所以归属读不出来时,步兵/坦克那条路
          **一律不接**(fail-closed),并记进 `skipped_no_front_owner`。
        """
        try:
            import frontline_line
            return frontline_line.read_frontline_owner(frame=frame)
        except Exception as e:
            return {"owner": None, "why": f"归属判据出错({type(e).__name__}: {e})"}

    def _guard_info(self, frame, field):
        """
        读一次"守护"标记(用户 2026-09-12 给的正样本 + 判据,实现在 `guard.py`)。

        返回 `{"hq_guarded": bool, "guard_units": [...], "detail": {...}}`。
        ★ fail-soft:**认不出就当"没有守护"** —— 代价不对称:
          "以为有守护"会放着总部不打(凭空丢掉确定的伤害),
          而"漏掉守护"最多白拖一次(`HQ_BLOCK_AFTER_MISS` 兜住)。
        ★ 整块包 try:观测/判据失败绝不许弄崩攻击(§7 第 57 条)。
        """
        try:
            import guard
            info = guard.read_guard(frame, field)
            if info.get("hq_guarded") or info.get("guard_units"):
                self.log(f"[attack] 守护判据: 敌方总部"
                         f"{'**被守护**' if info['hq_guarded'] else '未见守护标记'};"
                         f"带盾牌的敌方单位 {len(info['guard_units'])} 个"
                         f"(判据 = 卡右边缘那块盾牌字形,见 guard.py)")
            return info
        except Exception as e:
            self.log(f"[attack] 守护判据出错({type(e).__name__}: {e})"
                     f" -> 当没有守护(不拦)")
            return {"hq_guarded": False, "guard_units": [], "detail": {}}

    def _interceptors(self, field):
        """
        敌方**支援线**上有哪些单位会拦截我方轰炸机(用户规则:目前 = 战斗机)。

        返回 `[unit...]`(unit 就是 `field["enemy_support"]` 里的那些 dict,
        它们的 `type` 由 `board.read_field(templates=…)` 认好)。空列表 = 不拦。
        """
        out = []
        for u in (field.get("enemy_support") or []):
            if u.get("is_hq"):
                continue
            if u.get("type") in INTERCEPTOR_TYPES:
                out.append(u)
        return out

    def _pick_target(self, frame, field, item, owner, guard_info=None):
        """
        给这个攻击者挑一个目标;挑不到返回 None(**并且把原因写进
        `item["no_target_why"]`,调用方会汇总打出来**)。

        优先级(按**判据有多硬**排,不按伤害排),三档:
          ① **敌方总部** —— 血量的下降是最硬的语义判据(§7 第 46 条那条教训),
             而且**打总部不吃反击**;它同时是这局唯一能直接结束比赛的目标
             (总部 0 血 = 赢),所以我方有单位站在前线时**最该先打它**;
          ② **敌方支援线那一行的单位** —— 规则允许"站在前线的单位"打它
             (用户确认的矩阵:`FROM_FRONT_TARGETS` 里就有 `enemy_support`);
          ③ **敌方前线那一行** —— 只有**归属判到"敌方"**时才敢用:
             那一行是争夺线,归属判错就会去打自己的人。

        ★★★ 2026-09-12(第六个会话)补的是**第 ② 档** —— 规则表里一直写着它,
          但选目标这里**从来没有这一档**,于是"站在前线的单位"实际上**只能打总部**。
           实机症状(用户看画面指出、日志核对无误):最后 5~6 个回合
           **前线整段时间都是我们的、前线上的单位全是橙色(能行动)、却一次攻击都没发出**;
           原文 `我方支援线 4 张 ... 已试 5 个` 而 `尝试 0 次`。
           两个原因叠在一起:
             · ② 这一档不存在 -> 敌方**支援线**上的单位(画面里明明有、可打)选不中;
             · 同一帧 `find_enemy_hq` 返回 **None**(TRUK 那种"深色圆牌 + 白色单个数字"
               的血量 OCR 读不出来)-> ① 那一档也塌了 -> 一个目标都没有。
           ⇒ 所以这一轮同时修三处:补 ②、给总部加**卡名兜底**(见 `board.find_enemy_hq`)、
             把"挑不到目标的原因"写进日志(以前这里**一个字都不写**,
             用户只能看到"什么都没发生"—— 又一处"沉默失败")。
        """
        targets = item.get("targets") or frozenset()
        whys = []
        # ★ 这条攻击者会不会被"战斗机拦截"(用户规则:只有轰炸机)
        interceptors = (self._interceptors(field)
                        if item.get("type") in INTERCEPTED_ATTACKERS else [])
        _ixs = ",".join(f"x{int(u['x'])}" for u in interceptors)

        # ★★★ 2026-09-13(用户要求):**轰炸机在敌方没有战斗机时,50% 概率先打前线单位。**
        #
        # 用户原话:"轰炸机在对方没有战斗机守护的情况下可以增加一条 50% 概率打前线单位。"
        #   · "对方没有战斗机守护" = 这一条**只在不会被拦截时**才考虑
        #     (被拦截的轰炸机本来就打不到总部/支援线,只剩前线这一条路,
        #      那种情况下"优先打前线"就是它唯一的选择,不需要随机);
        #   · 目的:总部打不动(守护 / **烟幕**)或者场面需要清的时候,
        #     别让轰炸机每回合都往同一个打不动的目标上撞,顺手把前线清掉。
        #   ★ 随机量走 `random`,A/B 开关 `BOMBER_FRONT_CHANCE`(设 0 = 老行为,
        #     设 1 = 总是先打前线)。
        if (item.get("type") in BOMBER_FRONT_TYPES
                and not interceptors
                and TARGET_ENEMY_FRONT in targets
                and owner == "enemy"
                and random.random() < BOMBER_FRONT_CHANCE):
            _units = [u for u in (field.get("frontline") or [])
                      if not u.get("is_hq")]
            if _units:
                u = sorted(_units, key=lambda x: x["cx"])[0]
                self.log(f"[attack] 轰炸机掷骰命中({BOMBER_FRONT_CHANCE:.0%})"
                         f"且敌方支援线没有战斗机 -> 先打前线单位"
                         f"(用户规则;比每回合都撞总部更容易清场)")
                return {"cx": u["cx"], "cy": u["cy"], "hp": None,
                        "kind": TARGET_ENEMY_FRONT, "w": u.get("w", 0),
                        "label": "敌方前线单位"}

        if TARGET_ENEMY_HQ in targets:
            # ★★★ 2026-09-12(第七个会话):**战斗机拦截**先判 ——
            #   用户把范围定死了:"总部 + 敌方支援线单位都拦",被拦机型**只有轰炸机**。
            #   所以轰炸机在敌方支援线上有战斗机时,这一档不试(白拖)。
            if interceptors:
                self.log(f"[attack] 敌方支援线上有战斗机 {_ixs} -> 我方轰炸机"
                         f"打不到总部/敌方支援线(用户规则:战斗机会拦截轰炸机)")
                whys.append(f"敌方支援线上有战斗机({_ixs})-> 拦截轰炸机")
            # ★★★ 再判**守护**(硬判据:卡右边缘那块盾牌字形,见 `guard.py`):
            #   用户规则:"守护单位放在总部旁边会给总部上守护特效,**必须先把那个
            #   单位打掉**才能打总部" —— 所以总部被守护时这一档**根本不该试**,
            #   直接往下走 ②(守护单位就站在敌方支援线上,② 那档会去打它)。
            #   ★ 炮兵仍然放行:实机第 7 局就是"只有 artillery 打得进去"
            #     (见 `HQ_BLOCK_EXEMPT_TYPES`);用户 2026-09-12 再次确认
            #     "**战斗机也会吃守护**",所以这里只有炮兵豁免。
            elif ((guard_info or {}).get("hq_guarded")
                    and item.get("type") not in HQ_BLOCK_EXEMPT_TYPES):
                gx = ",".join(f"x{int(g['x'])}"
                              for g in (guard_info.get("guard_units") or []))
                whys.append("敌方总部**被守护**(卡上有盾牌标记"
                            + (f";守护单位 {gx}" if gx else "")
                            + ") -> 必须先打掉守护单位")
            # ★★ 本回合总部已经被"打不动"证伪过一次 ->
            #   非炮兵不再往上撞(见 `HQ_BLOCK_AFTER_MISS` 的整段说明)。
            #   ★ 跳过之后**不 return**,继续往下走 ②/③ —— 那正是"先把守护单位
            #     打掉"的方向(守护单位站在敌方支援线上)。
            elif self.hq_blocked and item.get("type") not in HQ_BLOCK_EXEMPT_TYPES:
                self.blocked_hq_skips += 1
                whys.append(f"总部这一档本回合已封(上一次没掉血:"
                            f"{self.hq_blocked_reason})")
            else:
                hq = board.find_enemy_hq(frame, field=field,
                                         templates=self.templates)
                if hq is None:
                    whys.append("总部认不出(血量数字 OCR 读不到、卡名兜底也没命中)")
                elif hq.get("w", 0) > 175:
                    # 框明显是两张卡粘在一起 -> 落点不可信。**不再直接放弃**,
                    # 而是跳过总部这一档,看看有没有别的合法目标(下面那两档)。
                    self.log(f"[attack] 敌方总部的框太宽({hq['w']}px,像是粘连)"
                             f" -> 这一档跳过")
                    whys.append(f"总部框粘连({hq['w']}px)")
                else:
                    return {"cx": hq["cx"], "cy": hq["cy"], "hp": hq.get("hp"),
                            "kind": TARGET_ENEMY_HQ, "w": hq.get("w", 0),
                            # ★ 把盾牌框带进目标:攻击之后复核血量时直接照它读
                            "shield_box": hq.get("shield_box"),
                            "label": "敌方总部"}

        # ② 敌方**支援线**那一行的单位(总部的另一种打法在 ① 那一档)
        #    ★★ 用户规则:"**总部 + 敌方支援线单位都拦**" —— 所以被拦截的轰炸机
        #       连这一档也打不到,直接跳过去看 ③(敌方前线)。
        if TARGET_ENEMY_SUPPORT in targets and interceptors:
            whys.append(f"敌方支援线上有战斗机({_ixs})-> 拦截轰炸机,"
                        f"支援线单位也打不到")
        elif TARGET_ENEMY_SUPPORT in targets:
            sup = list(field.get("enemy_support") or [])
            units = [u for u in sup if not u.get("is_hq")]
            units, guarded_n = self._drop_protected(units, frame)
            if units:
                # ★★ 2026-09-12(第七个会话):优先打**带盾牌标记**的那个
                #    (它就是守护单位)。用户规则要求"先打掉它",而且它本来就是
                #    最该清的目标 —— 不清它,我方所有非炮兵打总部都是白拖。
                guards = [u for u in units if u.get("guard")]
                u = sorted(guards or units, key=lambda x: x["cx"])[0]
                return {"cx": u["cx"], "cy": u["cy"], "hp": u.get("hp"),
                        "kind": TARGET_ENEMY_SUPPORT, "w": u.get("w", 0),
                        "label": ("敌方守护单位" if u.get("guard")
                                  else "敌方支援线单位")}
            whys.append(f"敌方支援线没有单位({len(sup)} 张卡,都是总部/认不出"
                        + (f";另有 {guarded_n} 张**被守护**,打它们会被游戏拒绝"
                           if guarded_n else "") + ")")

        if TARGET_ENEMY_FRONT in targets:
            if owner != "enemy":
                whys.append(f"前线归属是 {owner or '读不出'},不是敌方")
            else:
                units = [u for u in (field.get("frontline") or [])
                         if not u.get("is_hq")]
                units, guarded_n = self._drop_protected(units, frame)
                if units:
                    u = sorted(units, key=lambda x: x["cx"])[0]
                    return {"cx": u["cx"], "cy": u["cy"], "hp": None,
                            "kind": TARGET_ENEMY_FRONT, "w": u.get("w", 0),
                            "label": "敌方前线单位"}
                whys.append("敌方前线那一行没有单位"
                            + (f"(有 {guarded_n} 张**被守护**,打它们会被游戏拒绝)"
                               if guarded_n else ""))

        item["no_target_why"] = " / ".join(whys) or "这个类型没有可打的目标"
        return None

    def _drop_protected(self, units, frame):
        """
        把**被守护**的单位从"可打目标"里去掉 —— 打它们会被游戏**直接拒绝**。

        ★★★ 2026-09-13 深夜实机抓到(存帧 `shots/attack_frames/0913_232500_after.png`):
          引擎拖一个步兵去打敌方前线单位,游戏弹出一行白字
          **"此单位具有『被守护』。"** 然后把这次拖拽拒绝了 ——
          连跑三局里这样的白拖有 **4 次**(以前会记成"结论不可信",看不出是白拖;
          现在新加的徽章判据把它们如实记成了 `被拒绝(…徽章还是橙的…)`)。

        ★ 判据是**现成的**(`guard.glyph_at`,模板库 `config/guard_*.png`):
          · `which == "unit"`(**实心盾**)= 这张单位带【守护】-> 打它**是允许的**
            (而且该先打它,见下面"优先打守护单位");
          · `which == "hq"`(**半盾 + 盾牌外框**)= 这张卡**正被守护** ->
            拖上去必被拒,**从候选里去掉**。
          ⚠️ 两个文件名的 "hq/unit" 说的是**第一次在哪类卡上看到它**,不是语义
             (用户 2026-09-12 给的语义,见 §7 第 82 条)。
        ★ 实测(那一帧的前线三张):`hq` 0.941 / `unit` 0.921 / 0.721(不认) ——
          和游戏弹的那句话完全对得上。
        ★ fail-soft:判据读不出来(分数不够/没有模板)**当作没守护**,照打 ——
          代价被上面那条新判据兜住(打一次被拒就记出来),不会"因为读不出就永远不打"。

        返回 `(剩下的候选, 被判为'被守护'的个数)`。
        """
        if not PROTECTED_SKIP or not units:
            return list(units or []), 0
        try:
            import guard as guard_mod
        except Exception:
            return list(units or []), 0
        keep, dropped = [], 0
        for u in units:
            try:
                _s, d = guard_mod.glyph_at(frame, u)
            except Exception:
                keep.append(u)
                continue
            if d.get("ok") and d.get("which") == "hq":
                dropped += 1
                continue
            if d.get("ok") and d.get("which") == "unit":
                u["guard"] = True        # 守护单位:允许打,而且该先打
            keep.append(u)
        if dropped:
            self.log(f"[attack] {dropped} 张敌方卡带的是「**被守护**」标记"
                     f"(半盾+外框)-> 从可打目标里去掉"
                     f"(实机:拖上去游戏会弹「此单位具有『被守护』」并拒绝)")
        return keep, dropped

    def _relocate_target(self, target):
        """
        出手**之前**再看一帧,把落点更新到目标卡**现在**的位置。

        ★★★ 2026-09-13 深夜(**用户实测**):第二局第 13 回合 ——
          "对面前线单位被我方打掉一个,仅剩的另一张前线单位**移到中间**的时候
           触发的攻击,这时攻击指向**还在原位置**"。
        机理:目标是"读战场那一帧"里选出来的,而拖拽要等 1~2 秒之后才发生
        (中间还有徽章读取、落点计算),这期间**卡会动**(补位/动画)。
        往旧坐标拖 = 拖到空地上 = 游戏直接拒绝(白花一次拖拽 + 一次判定)。

        返回 `(cx, cy)`;目标已经不在原处附近 -> 返回 **None**(调用方跳过这一发)。

        ★ 只在**打单位**时用(总部不动);代价 = 一次 `read_field`(约 0.1~1s),
          换掉的是"整发白拖 + 一次误判"。
        """
        if not RELOCATE_BEFORE_ATTACK:
            return (target["cx"], target["cy"])
        f = self._frame()
        if f is None:
            return (target["cx"], target["cy"])
        key = {TARGET_ENEMY_SUPPORT: "enemy_support",
               TARGET_ENEMY_FRONT: "frontline"}.get(target.get("kind"))
        if key is None:
            return (target["cx"], target["cy"])
        try:
            field = board.read_field(f, templates=self.templates)
        except Exception:
            return (target["cx"], target["cy"])
        best = None
        for u in (field.get(key) or []):
            if u.get("is_hq"):
                continue
            d = (abs(u["cx"] - target["cx"]) + abs(u["cy"] - target["cy"]))
            if best is None or d < best[0]:
                best = (d, u)
        if best is None:
            return None
        if best[0] > RELOCATE_TOL:
            self.log(f"[attack] 目标卡不在原处附近了(最近的同类卡离 "
                     f"{best[0]}px > {RELOCATE_TOL})-> 这一发跳过,"
                     f"下一轮重新选(★用户实测:卡会补位移动,往旧坐标拖会被拒绝)")
            return None
        if (best[1]["cx"], best[1]["cy"]) != (target["cx"], target["cy"]):
            self.log(f"[attack] ★目标卡动了:({target['cx']},{target['cy']})"
                     f" -> ({best[1]['cx']},{best[1]['cy']}),落点跟着更新")
        return (best[1]["cx"], best[1]["cy"])

    def _dump_hp_bogus(self, frame, target, hp_before, hp_now, hp_late):
        """
        把"晚读读到不可能的值"那一帧**存下来**(观测代码整块包 try,§7 第 57 条)。

        为什么要存:2026-09-15 那三次(`17->20`、`11->20`、`10->87`)只留下了日志,
        而**读错的到底是哪块像素**光看日志说不出来 —— 下一次再出现就有帧可量。
        """
        if not DUMP_HP_BOGUS or frame is None:
            return
        try:
            import os
            import time as _t
            d = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "shots", "hp_bogus")
            os.makedirs(d, exist_ok=True)
            cv2.imwrite(os.path.join(
                d, _t.strftime("%m%d_%H%M%S") + "_late.png"), frame)
        except Exception:
            pass

    def _recover_from_bogus_hp(self, frame, target, hp_before, hp_now, hp_late):
        """
        晚读拿到一个**不可能**的值(比出手前还高)时,先把读数救回来再下结论。

        证据(2026-09-15 复验那轮 3 次):`17 -> 20`、`11 -> 20`、`10 -> 87`。
        总部血量**不可能变多**(上限就是 20,`87` 尤其离谱),所以这三条是
        **读数的错,不是"没打中"**;而当时那套代码把晚读当权威("以晚读的为准"),
        于是把已经打中的那一发写成"结论不可信,按'没打中'处理"。
        ★ 第 3 发尤其可惜:立刻那次读到 10(和出手前一样),而**下一发**出手前
          读到 7 —— 也就是那一发**确实打进了 3 点**。

        救的顺序(每一步都写进日志,不做无声的替换):
          ① **在同一帧上重新定位总部**(`find_enemy_hq`,不再用出手前那个盾牌框)——
             框可能因为版面重排/动画而漂到别的卡上;
          ② 退回**出手后立刻**那次读数(它可能才是对的);
          ③ 两个都不行 -> 返回 None,由调用方维持"结论不可信"那条老路(**不许伪造结论**)。

        返回:(hp 或 None, 说明文字)。开关 `HP_BOGUS_RECOVER` 关掉就是旧行为(A/B 用)。
        """
        if not HP_BOGUS_RECOVER:
            return None, "开关关掉(旧行为)"
        try:
            hq2 = board.find_enemy_hq(frame)
        except Exception as e:
            hq2 = None
            self.log(f"[attack] 重新定位总部出错: {type(e).__name__}: {e}")
        cand = (hq2 or {}).get("hp")
        if cand is not None and (hp_before is None or cand <= hp_before):
            return cand, (f"**重新定位总部**后读到 {cand}"
                          f"(不再用出手前那个盾牌框)")
        if hp_now is not None and (hp_before is None or hp_now <= hp_before):
            return hp_now, f"退回**出手后立刻**那次读数 {hp_now}"
        return None, (f"重新定位读到 {cand}、立刻那次 {hp_now} 也都不可信"
                      f"(出手前 {hp_before})")

    def _watch_hp_for_drop(self, frame, target, hp_now):
        """
        判"没打中"**之前**,把敌方总部的血量盯一会儿 —— 看它会不会自己掉下来。

        为什么要这样(实机 J2 逐发对账,见 `MISS_HP_VERIFY_S` 的整段说明):
          现在只等 `ATTACK_SETTLE + LATE_HP_WAIT ≈ 1.4s` 就读第二次,而**盾牌上的
          数字刷新得比这慢** —— 于是每一发都读回**旧值**,把已经打中的伤害判成
          "没打中",还顺手封掉总部这一档(本回合剩下的攻击者全被挡)。

        判据:每秒读一次,最多 `MISS_HP_VERIFY_S` 秒;**一旦掉下来就立刻返回新值**。
        返回值:掉下来的新血量,或者 None(这段时间里一直没变 / 读不到)。

        ★ 代价有界:每次"看起来没打中"最多多花 `MISS_HP_VERIFY_S` 秒,而且**一旦
          看到掉血就提前收工**;真打不动(守护/烟幕)时才会花满。
        ★ 只读:只截图 + `read_hq_hp`,不碰鼠标(拖拽早已结束)。
        """
        if not MISS_HP_VERIFY_S or MISS_HP_VERIFY_S <= 0:
            return None
        t0 = time.time()
        trace = []
        last = hp_now
        while time.time() - t0 < MISS_HP_VERIFY_S:
            time.sleep(1.0)
            f = self._frame()
            if f is None:
                continue
            try:
                v = board.read_hq_hp(f, target)
            except Exception:
                v = None
            trace.append((round(time.time() - t0, 1), v))
            if v is not None:
                last = v
                if hp_now is not None and v < hp_now:
                    if MISS_HP_TRACE:
                        self.log(f"[attack] 血量跟踪:{self._trace_text(trace)}"
                                 f" -> **掉血了**(数字是隔几秒才刷新的)")
                    return v
        if MISS_HP_TRACE:
            self.log(f"[attack] 血量跟踪(判'没打中'之前盯了 "
                     f"{MISS_HP_VERIFY_S:.0f}s):{self._trace_text(trace)}"
                     f" -> 一直没变")
        return last if (last is not None and hp_now is not None
                        and last < hp_now) else None

    @staticmethod
    def _trace_text(trace):
        return " ".join(f"+{t}s={v}" for t, v in trace[:12])

    def _attacker_acted(self, badge, frame):
        """
        出手之后再看**同一个徽章**:它从橙变灰了吗?(= 游戏接受了这次行动)

        §7 第 74 条(用户确认的规则):**橙 = 本回合还没行动过**(而且付得起行动费)。
        所以:
          · 拖之前是橙、拖之后**变灰** -> 游戏**接受了**这次行动(单位动过了);
          · 拖之后**还是橙** -> 这次拖拽**被游戏拒绝了**(单位没动)。

        ★★ 为什么这条判据值钱:**单位卡上没有能读的血量数字**
          (只有总部卡有盾牌数字),所以打单位的"打中了没有"一直只有
          "那一行还剩几张卡"这一条 —— 打伤但没打死就完全判不出来(实机 J2 报了 9 次
          "结论不可信")。而徽章这条信号是**现成的**(引擎每轮本来就在读它)。
        实机账(2026-09-13 J1~J4):**17/17 次打单位的拖拽,拖完之后我方都有一个
          橙色徽章变灰** —— 也就是说那些"结论不可信"其实都是"打伤了、没打死",
          而且我们**一次都没白拖**。

        返回:True(接受了)/ False(还是橙 = 被拒绝)/ None(判不了,不猜)。
        ★ 判不了就返回 None,由调用方退回老措辞 —— 不许把"读不出来"说成结论。
        """
        if not badge or frame is None:
            return None
        try:
            badges = unit_state.find_cost_badges(frame)
        except Exception:
            return None
        if not badges:
            return None                     # 一个徽章都没检出来 -> 判据塌了,不猜
        # 找**同一个位置**的那个徽章(12px 以内;卡不会在两次读之间平移)
        near = unit_state.nearest_badge(badges, {"x": badge["x"], "y": badge["y"]},
                                        max_dist=12)
        if near is None:
            return None
        st = near.get("state")
        if st == "grey":
            return True
        if st == "orange":
            return False
        return None

    def _hq_gone(self, frame, row_n_before=None):
        """
        出手之后再找一遍**敌方总部卡**:它是不是**从画面上消失了**?

        返回 `(gone, why)`。判据两条**缺一不可**(见 `HQ_GONE_IS_KILL` 的整段说明):
          ① **敌方那一行还读得到**(有行结构)-> 排除"整帧读不到/画面被盖住"这种假象;
             ★ 这一条是关键:**总部血量读不到恰恰常常是因为有东西挡着它**
               (伤害飘字、对手的展示卡、悬停面板),那种情况下 `find_enemy_hq`
               同样会返回 None —— 不先要求"别的行都读得到",就会把遮挡当成击毁。
          ② 用**同一套** `board.find_enemy_hq`(盾牌 -> 行内数字 OCR -> 卡名 OCR)
             找不到任何总部卡。

        `row_n_before`(出手前那一行有几张卡,可选)会写进说明里 ——
        这样万一是**误判**(卡还在、只是三条判据同时没读到),"出手前 2 张 -> 现在 2 张"
        在日志里一眼就能看出来。★ 本轮**故意不拿它当第三道闸**:总部被摧毁时那张卡
        还要播死亡动画,0.9 秒那一帧上很可能**还在**,拿它当闸会把真击毁挡掉。

        ★ 只读:不碰鼠标。
        """
        try:
            field = board.read_field(frame, templates=self.templates)
        except Exception as e:
            return False, f"读战场出错 {type(e).__name__}: {e}"
        rows = (field or {}).get("rows") or []
        if not rows:
            return False, "整帧读不到行结构(画面可能被盖住 -> 不能据此下结论)"
        try:
            hq = board.find_enemy_hq(frame, field=field, templates=self.templates)
        except Exception as e:
            return False, f"找总部出错 {type(e).__name__}: {e}"
        if hq is not None:
            return False, (f"总部卡还在(x{hq['x']},血量 {hq.get('hp')})"
                           f"-> 那是'读不到血量',不是'卡没了'")
        row0 = rows[0] if rows else {}
        n = len(row0.get("units") or row0.get("boxes") or [])
        seq = (f"出手前那一行 {row_n_before} 张 -> 现在 {n} 张,"
               if row_n_before is not None else f"敌方那一行还读得到 {n} 张卡,")
        return True, (f"{seq}但盾牌/数字/卡名三条判据全都找不到总部卡")

    def _in_our_row(self, field, badge_y, margin=40):
        """
        这个费用徽章是不是落在**我方那一行**里。

        ★★ 2026-09-11 下午新增的一道闸(准备第一次开 `--attack` 时发现的缺口):
          `unit_state.actionable_units()` 是**全盘**找橙色徽章,而且结果按 y 排序 ——
          最上面那一行(敌方支援线)排在最前。所以"徽章优先"这条路上,
          `usable[0]` 完全可能是**敌人的卡**。
          实测确实"敌方徽章通常是灰的"(§12 实测记录:2 橙我方 + 2 灰敌方),
          但那是**观察到的现象,不是规则** —— 一旦有张敌方卡在我们回合仍是橙的
          (例如刚打出的闪击单位),就会去拖敌人的单位。而 §10 明确写着
          **"把敌方单位当成自己人拖"是这个项目最危险的错误**。
        所以这里按"行"再判一次。判据分两级(都是"我方"的定义,不是猜的):
          ① 有行信息 -> 用**最下面那一行**(side == "our")的 y 范围;
          ② 没有行信息 -> 用 `our_support` 里那些卡的包围盒。
        两个都拿不到就**一律不攻击**(fail-closed)。
        """
        rows = field.get("rows") or []
        our = [r for r in rows if r.get("side") == "our"]
        if our:
            r = our[-1]
            return (r["y0"] - margin) <= badge_y <= (r["y1"] + margin)
        boxes = field.get("our_support") or []
        if boxes:
            y0 = min(b["y"] for b in boxes)
            y1 = max(b["y"] + b["h"] for b in boxes)
            return (y0 - margin) <= badge_y <= (y1 + margin)
        return False

    def _unit_row_kind(self, field, badge_y):
        """
        这个徽章落在**哪一行**:返回 ("support"|"front"|None)。

        ★★ 2026-09-12 新增,修的是一个把"我们已经挪到前线的单位"当外人的 bug:
          实机日志里出现过
          `1 个橙色徽章不在我方那一行 -> 已排除(很可能是敌方单位)`,
          而那个徽章的原始数值是 `S=157 V=207` —— **又亮又橙的真徽章**,
          位置在 **cy350/frontline**。它正是我们上一回合**刚挪上前线**的那个单位
          (用户也指出:033015 判成敌方,是 032808 那次漏检挖的坑)。
          旧代码只认"我方支援线"那一行,于是:
            · 挪上去的单位**下一回合不会攻击**(被自己排除了);
            · 日志还写"很可能是敌方单位" —— **那是句假话**。
        ★ 判据:橙色徽章在我们自己的回合里**就是我们的**(敌方这回合不能行动 -> 必灰,
          见 §7 第 71 条)。所以只要它落在我方支援行或前线行就算我们的;
          落**敌方那一行**的仍然排除(实测那种是假橙色:`S=132 V=97`,暗底)。
        """
        rows = field.get("rows") or []
        if not rows:
            return None
        bcy = badge_y - 4 + unit_state.CARD_H_EST // 2
        r = min(rows, key=lambda x: abs(float(x["cy"]) - bcy))
        side = r.get("side")
        if side == "our":
            return "support"
        if side == "frontline":
            return "front"
        return None

    def _our_attackers(self, frame, field, owner=None):
        """
        我方"这回合还能行动、而且**有合法目标**"的单位。

        返回 (usable, skipped, source)。`skipped` 是 **dict**,三个桶**必须分开报**
        (2026-09-12 实机 + 用户确认的规则):
          `unknown_type`   —— **类型认不出**:我们自己没做完的活
          `no_front_owner` —— **能打,但前线归属读不出**:步兵/坦克在支援线上,
                              规则允许它打敌方前线那一行,但归属判据没读出结果。
                              也是要补的活(工具 `frontline_line.py`)。
          `needs_front`    —— **规则使然**:归属**读出来了、而且不是敌方的**
                              (前线空着 / 我方控制)-> 那一行没有可打的敌人,
                              这类单位想打到东西就只能先上前线。
        ★ 三个桶的**处置完全不同**,合并成一个数就是"日志在撒谎"(§7 第 68 条 C)。

        owner: 'enemy' / 'our' / 'neutral' / None。None = 读不到 -> fail-closed。

        usable 里每项有 `src`(拖动起手点)、`type` 和 `targets`(能打的目标集合)。

        ★★ 判据分两层,**优先用橙色费用徽章**:
          用户确认:卡左上角的费用数字 **橙=还能行动 / 灰=本回合已行动**。
          实测这条路比走卡框可靠得多 —— 卡框在相邻卡粘连/被手牌挡住时
          会合并或整张漏掉(实测漏过卡),而徽章是独立小方块,不受影响。
        """
        usable = []
        skipped = {"needs_front": 0, "unknown_type": 0, "no_front_owner": 0}
        off_row = 0
        try:
            cands = unit_state.actionable_units(frame, templates=self.templates,
                                                debug=self.debug)
        except Exception as e:
            cands = []
            self.log(f"[attack] 徽章判据出错({type(e).__name__}: {e})"
                     f" -> 退回卡框判据")

        def _classify(u, row_kind):
            """把一张候选分到 usable / 三个跳过桶之一。"""
            ctype = u.get("type")
            if ctype is None:
                skipped["unknown_type"] += 1
                return None
            # ★★ 按"它站在哪一行"查规则表 —— 用户 2026-09-12 确认的矩阵里,
            #   同一类型站在支援线和站在前线**能打的目标不一样**:
            #     支援线的步兵/坦克只能打敌方前线;前线的步兵/坦克能打
            #     敌方支援线 + 敌方总部(规则②)。
            from_row = ROW_FRONT if row_kind == "front" else ROW_SUPPORT
            targets = attack_targets(ctype, from_row)
            if not targets:
                # 类型不在规则表里(多半是词汇不一致,如 counter/countermeasure)——
                # 同样算"没做完的活",**不许**混进 needs_front。
                skipped["unknown_type"] += 1
                return None
            if row_kind == "front":
                # 站在前线的单位:目标都在远处,不需要归属判据(归属只用来
                # 决定"能不能上去"和"支援线步兵打谁")。
                pass
            elif not (targets & OWNERLESS_TARGETS):
                # 只剩"打敌方前线那一行"这一条路(支援线上的步兵/坦克)。
                if owner == "enemy":
                    pass                      # 那一行是敌人的 -> 有得打
                elif owner in ("our", "neutral", "empty"):
                    # 归属读出来了、不是敌方 -> 那一行没有可打的敌人。
                    # 这是**规则使然**(想打到东西就得先上前线)。
                    skipped["needs_front"] += 1
                    return None
                else:
                    # 归属读不出来 -> **不敢判**,这是要补的活,不是规则。
                    skipped["no_front_owner"] += 1
                    return None
            u["targets"] = targets
            u["from_row"] = from_row
            return u

        if cands:
            for u in cands:
                key = (u["badge"]["x"], u["badge"]["y"])
                if key in self.tried:
                    continue
                # ★★ 2026-09-12:改判"落在哪一行" —— 我方支援行**或前线行**都算我们的
                #   (橙色徽章在我们回合就是我们的);只有落在**敌方那一行**才排除。
                #   旧版只认支援行,把我们自己挪上前线的单位也排除了,还在日志里
                #   写成"很可能是敌方单位"(假话)。详见 `_unit_row_kind`。
                row_kind = self._unit_row_kind(field, u["badge"]["y"])
                if row_kind is None:
                    off_row += 1
                    continue
                if _classify(u, row_kind) is not None:
                    u["key"] = key
                    usable.append(u)
            if off_row:
                # ★ 2026-09-12:措辞改准 —— 现在只有**落在敌方那一行**的橙色才被排除。
                #   以前写"很可能是敌方单位",而我们自己挪上前线的单位也被这条排掉,
                #   于是那句话变成了假话(§7 反复吃过"诊断撒谎"的亏)。
                self.log(f"[attack] {off_row} 个橙色徽章落在**敌方那一行**"
                         f" -> 已排除(不是我们的单位,多为暗底假橙色)")
            return usable, skipped, "橙色费用徽章"

        # ---- 兜底:卡框那一行 + 类型图标 ----
        # ★★ 2026-09-11 晚实机**默认关掉了**(见 ALLOW_BOX_FALLBACK 的说明)。
        if not ALLOW_BOX_FALLBACK:
            self.log("[attack] 没找到橙色费用徽章 -> 不攻击"
                     "(拿'这回合不能行动'的单位去拖只会白拖;宁可少打一次)")
            return [], skipped, "没有橙色徽章(不回退卡框)"
        for u in field["our_support"]:
            if u.get("is_hq"):
                continue
            key = (u["cx"], u["cy"])
            if key in self.tried:
                continue
            cand = {"src": (u["cx"], u["cy"]), "type": u.get("type"), "key": key}
            if _classify(cand, "support") is not None:
                usable.append(cand)
        return usable, skipped, "卡框(没找到费用徽章)"

    def _dump_badges(self, frame, field):
        """
        ★ 诊断(只读):把这一帧上**所有**费用徽章 + 颜色判据的原始数值打出来,
        并把这一帧存到 `shots/attack_frames/` 便于事后逐帧核对。

        要回答的问题只有一个:**我方支援线上那些单位,徽章到底是没有,还是被判成了灰?**
          · 日志里出现 `x.. y.. S=..` -> 徽章**检出来了**,S 的值直接说明判成什么;
          · 日志里我方那一行**一个徽章都没有** -> 是**漏检**(要修 find_cost_badges);
          · S 卡在 105~130 之间 -> 是**阈值/判据**问题(§7 第 67 条那个空档被测穿过)。
        整块包 try —— 诊断绝不许弄崩攻击(§7 第 57 条)。
        """
        try:
            import os
            import time as _t
            import unit_state
            rows = field.get("rows") or []
            badges = unit_state.find_cost_badges(frame, rows=rows)
            # 每个徽章属于哪一行(用徽章推出来的卡中心,和 board.support_line_units 同一套)
            def _row_of(b):
                bx = b["y"] - 4 + unit_state.CARD_H_EST // 2
                if not rows:
                    return None
                return min(rows, key=lambda r: abs(r["cy"] - bx))
            parts = []
            for b in badges:
                r = _row_of(b)
                tag = f"cy{round(r['cy'])}/{r.get('side')}" if r else "?"
                parts.append(f"x{b['x']}y{b['y']} S={b['digit_s']:.0f} "
                             f"V={b['digit_v']:.0f} {b.get('state')}[{tag}]")
            self.log(f"[attack] 徽章全表({len(badges)} 个;"
                     f"阈值 橙 S>={unit_state.SAT_ORANGE_MIN} / 灰 S<="
                     f"{unit_state.SAT_GREY_MAX}): "
                     + ("; ".join(parts) if parts else "(一个都没有)"))
            if not DUMP_ATTACK_FRAMES:
                return          # ★ 只关"存整帧",徽章全表那一行日志**照打**(那才是重点)
            d = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "shots", "attack_frames")
            os.makedirs(d, exist_ok=True)
            cv2.imwrite(os.path.join(d, _t.strftime("%m%d_%H%M%S") + "_attack.png"),
                        frame)
            # 只留最新的几张:观察窗够用就行,别把磁盘塞满(见 DUMP_MAX_FRAMES 的说明)
            try:
                files = sorted((os.path.join(d, f) for f in os.listdir(d)
                                if f.endswith(".png")),
                               key=os.path.getmtime)
                for old in files[:-DUMP_MAX_FRAMES]:
                    os.remove(old)
            except Exception:
                pass
        except Exception as e:
            self.log(f"[attack] 徽章诊断出错({type(e).__name__}: {e}) —— 不影响攻击")

    def _dump_after(self, frame):
        """
        把攻击**之后**那一帧也存下来(和 `_dump_badges` 的 before 帧配套)。

        ★ 为什么需要:实机第一发出现"出手前读到 18、出手后读不到" ——
          到底是**伤害动画把盾牌盖住了**,还是**卡框/盾牌位置变了**,
          光看日志分不出来,得把那一帧留下来看。观测代码整块包 try(§7 第 57 条)。
        """
        if not DUMP_ATTACK_FRAMES:
            return
        try:
            import os
            import time as _t
            d = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "shots", "attack_frames")
            os.makedirs(d, exist_ok=True)
            cv2.imwrite(os.path.join(d, _t.strftime("%m%d_%H%M%S") + "_after.png"),
                        frame)
        except Exception:
            pass

    def _attack(self, src, dst):
        """从 src(client 坐标)拖到 dst。"""
        # ★★ 2026-09-15:这一小段**可能抛异常**,而且抛了就会带走整个引擎。
        #   `win32gui.ClientToScreen` 在窗口句柄失效时抛 `pywintypes.error`;
        #   证据:上一轮实机整跑最后一行日志是 `[attack] #1 我方 infantry ...`,
        #   下一行本该是拖拽后的判据,却什么都没有 —— 中间只有这一段代码。
        #   这里 fail-soft(项目原则:宁可少打一次,也不能把整局弄崩):
        #   换算/拖拽失败 -> 记一条**醒目**日志,按"这一发没发出去"返回 False。
        #   调用方随后照常走"打中了没有"的判据,而判据看到的是"什么都没变",
        #   该报"被拒绝/结论不可信"就照报 —— 不会因为这里而伪造出结论。
        #   (顶层还加了兜底:真出了别的异常,`main_loop.main()` 会把 traceback
        #    写进 `logs/main_loop.log`,不再只丢给控制台。)
        try:
            sx, sy = client_to_screen(self.hwnd, src[0], src[1])
            dx, dy = client_to_screen(self.hwnd, dst[0], dst[1])
        except Exception as e:
            self.log(f"⚠️ 拖拽发不出去(坐标换算失败): {type(e).__name__}: {e}"
                     f" —— 多半是 KARDS 窗口句柄失效(窗口关了/重开了)")
            return False
        try:
            return move_drag(sx, sy, dx, dy)
        except Exception as e:
            self.log(f"⚠️ 拖拽发不出去: {type(e).__name__}: {e}")
            return False

    def run_turn(self, hard_stop=None):
        """
        用我方【这回合能行动、且有合法目标】的单位攻击敌方目标。
        返回 (attempts, landed)。

        每次循环做四件事:
          ① 抓帧 + `board.read_field`(自适应行带 + 相对定阵营);
          ② **读"前线那一行是谁的"**(`frontline_line.read_frontline_owner`)——
             步兵/坦克能不能打全看它,读不出来就 fail-closed;
          ③ `_our_attackers` 按"类型 × 所在行 → 目标集合"筛出可用的攻击者
             (三个跳过桶分开报,见那里的说明);
          ④ `_pick_target` 给攻击者挑目标:**优先敌方总部**(血量是硬判据、
             而且打总部不吃反击),其次**敌方前线那一行**的敌方单位。

        "打中了没有"的判据按目标种类分开,而且**不许把弱判据包装成结论**:
          · 打**总部** -> 敌方总部血量有没有下降(语义信号,§7 第 46 条);
          · 打**单位** -> 读不到那个单位的血量,只能看"敌方前线那一行少没少一张",
            日志里会明确写"结论不可信"(以前那种"画面差异"的退路只在总部血量
            读不到时才走,而且会写明)。
        """
        for _ in range(self.max_attacks):
            if hard_stop is not None and hard_stop():
                self.log("[attack] 我方回合结束,停止攻击")
                break

            self._park()
            before = self._frame()
            if before is None:
                break
            field = board.read_field(before, templates=self.templates,
                                    debug=self.debug)

            # ★★ 先读"前线那一行是谁的" —— 步兵/坦克能不能打,全看它。
            owner_info = self._frontline_owner(before)
            owner = owner_info.get("owner")

            # ★★★ 再读"守护"(用户 2026-09-12 给的正样本):敌方总部被守护 ->
            #   非炮兵**一次都不该试**它(见 `guard._pick_target` 那一档的说明)。
            guard_info = self._guard_info(before, field)

            # ★★ 2026-09-12 新增**诊断**:把这一帧上**所有**费用徽章连颜色一起打出来。
            #   为什么非要有它:实机一局"没有一个橙色徽章" -> 攻击一次都发不出,
            #   而旧日志**分不清**下面这两种完全不同的错法(修法也完全不同):
            #     ① 徽章根本没被检出(漏检)—— 要修行带补检;
            #     ② 检出来了、但把**橙色**判成了灰(判据/阈值错)—— 要修 analyze_digit。
            #   ★ 观测代码整块包 try:诊断失败只丢一行日志,绝不影响攻击(§7 第 57 条)。
            self._dump_badges(before, field)

            # ★★ 我方单位:优先橙色的费用徽章(见 _our_attackers)。
            #   徽章那一层已经天然排除了"本回合已行动"的单位 ——
            #   所以不会再"每个单位每回合白拖一次"。
            usable, skipped, source = self._our_attackers(before, field, owner=owner)

            # ★★★ 2026-09-13(实机,用户逐回合指出"第九/十一回合我方单位没行动"):
            #   **对手刚打出的牌会在屏幕正中放大展示好几秒,正好盖住【前线那一行】。**
            #   那张展示卡会被 `merged_card_boxes` 检出来、又因为太高
            #   (`BAND_ROW_H_MAX`)被当成"不是一行"丢掉 -> 行结构**只剩 2 行**
            #   -> `front_row()` 返回 None -> `frow_cards=0` -> **语义判据判成 `empty`**
            #   -> 攻击阶段:支援线上的步兵/坦克"够不着目标",一个都不打;
            #   而 2 秒后 `move_front` 再读一帧(展示已经消失)-> 判成 `enemy`
            #   -> **不许上前线**。
            #   ⇒ **那个单位整回合既不能攻也不能上,干站着**。
            #   (存帧 `shots/attack_frames/0913_033131_attack.png`:中央那张
            #    `U-375` 展示卡把前线那一行整条盖住,行结构只剩
            #    `cy176/enemy n3; cy526/our n1`;同一回合 `move_front` 却报
            #    "前线是敌方的 -> 不上前"。)
            #
            #   判据(窄而明确,三个条件同时成立才重读):
            #     ① `owner == "empty"`;② 行结构**不足 3 行**(前线那一行不在);
            #     ③ 确实有单位因为"归属不是敌方"被跳过(`needs_front`)。
            #   -> 这个 `empty` 不可信,等一下重读一帧,读到的才算数。
            #   ★ 只有**真有单位被卡住**时才付这次重读的钱,空场回合不受影响。
            if (not usable and skipped.get("needs_front")
                    and owner == "empty"
                    and len(field.get("rows") or []) < 3):
                time.sleep(DISPLAY_CARD_SETTLE)
                f2 = self._frame()
                if f2 is not None:
                    fi2 = board.read_field(f2, templates=self.templates)
                    oi2 = self._frontline_owner(f2)
                    if oi2.get("owner") not in (None, "empty"):
                        self.log(
                            f"[attack] 前线归属原来读成 empty(行结构只有 "
                            f"{len(field.get('rows') or [])} 行 —— 多半是**对手的"
                            f"展示卡盖住了前线那一行**)—— 等 {DISPLAY_CARD_SETTLE}s "
                            f"重读 -> {oi2['owner']}"
                            f"(行结构 {len(fi2.get('rows') or [])} 行),按重读的算")
                        before, field = f2, fi2
                        owner_info, owner = oi2, oi2["owner"]
                        guard_info = self._guard_info(before, field)
                        self._dump_badges(before, field)   # 重读那帧也留证据
                        usable, skipped, source = self._our_attackers(
                            before, field, owner=owner)

            self.skipped_needs_front = skipped["needs_front"]
            self.skipped_unknown_type = skipped["unknown_type"]
            self.skipped_no_front_owner = skipped["no_front_owner"]
            self.skipped_needs_front_all += skipped["needs_front"]
            self.skipped_unknown_type_all += skipped["unknown_type"]
            self.skipped_no_front_owner_all += skipped["no_front_owner"]

            # 挑一个"攻击者 + 目标"的组合来打这一发。
            # ★ 挑不到目标的攻击者要记进 `tried`,否则下一轮循环又会选中它 -> 死循环。
            src = None
            target = None
            for item in usable:
                t = self._pick_target(before, field, item, owner,
                                      guard_info=guard_info)
                self.tried.add(item["key"])
                if t is not None:
                    src, target = item, t
                    break
            if target is None:
                # ★★ 2026-09-12:把"**为什么**挑不到目标"写出来。
                #   以前这里只报"没有能攻击的我方单位或目标",而 `_pick_target`
                #   返回 None 时**一个字都不写** —— 于是"前线全是我们的、单位全是橙的、
                #   却整局不攻击"在日志里完全看不出原因(用户只能靠看画面发现)。
                #   两件事必须分开写:**没有攻击者** vs **有攻击者但没目标**,
                #   而"没目标"还要写清是哪一档塌了(总部认不出 / 支援线没单位 / 归属不是敌方)。
                whys = [it.get("no_target_why") for it in usable if it.get("no_target_why")]
                detail = ""
                if usable and whys:
                    from collections import Counter
                    c = Counter(whys)
                    detail = (";每个攻击者挑不到目标的原因: "
                              + ";".join(f"{w} x{n}" for w, n in c.most_common(3)))
                self.log(f"[attack] 没有能攻击的我方单位或目标(判据: {source};"
                         f"前线归属 {owner or '读不出'};"
                         f"能打但**前线归属读不出**的 {skipped['no_front_owner']} 个、"
                         f"**类型认不出**的 {skipped['unknown_type']} 个、"
                         f"归属已读出但不是敌方的 {skipped['needs_front']} 个 已跳过;"
                         f"总部这一档因"
                         f"{self.hq_blocked_reason or '未封'}"
                         f"而跳过 {self.blocked_hq_skips} 个;"
                         f"已试 {len(self.tried)} 个;"
                         f"我方支援线 {len(field['our_support'])} 张;"
                         f"**有攻击者但挑不到目标**的 {len(whys)} 个"
                         f"{detail})")
                break

            self.attempts += 1
            hp_before = target.get("hp")
            # ★★★ 2026-09-13 深夜(**用户实测的"目标会动"**):拖之前重新定位一次。
            #   目标是"读战场那一帧"选的,而拖拽在 1~2 秒之后才发生 ——
            #   这期间卡会补位移动(用户看到前线那张卡移到了中间,而攻击还指向
            #   原位置 -> 拖到空地上被拒绝)。
            drop = self._relocate_target(target)
            if drop is None:
                self.attempts -= 1              # 这一发根本没用出去,不算一次尝试
                self.tried.add(src["key"])      # 别再挑同一个攻击者原地打转
                continue
            self.log(f"[attack] #{self.attempts} 我方 {src.get('type')} "
                     f"x{src['src'][0]}@y{src['src'][1]} "
                     f"-> {target['label']} x{drop[0]}"
                     f"@y{drop[1]}(血量 {hp_before};判据 {source};"
                     f"前线归属 {owner or '读不出'})")
            self._attack(src["src"], drop)
            time.sleep(ATTACK_SETTLE)

            self._park()
            after = self._frame()
            if after is None:
                self.log("[attack] 截图失败,停止攻击")
                break
            self._dump_after(after)

            # ---- 打的是**单位** -> 没有血量读数,只能用"那一行还有没有它" ----
            #   ★ 这里**必须写明判据弱**:不能像打总部那样用"血量下降"这种硬信号。
            #     §7 第 46 条:宁可写"结论不可信",也不要把弱判据伪装成结论。
            if target["kind"] != TARGET_ENEMY_HQ:
                field_after = board.read_field(after, templates=self.templates)
                # ★ 2026-09-12:目标在哪一行,"打中了没有"就要数**哪一行** ——
                #   补上"敌方支援线"这一档之后,再沿用"只看前线那一行"的旧写法
                #   就会数错行(打掉了支援线的卡、却盯着前线数,永远报"结论不可信")。
                key = ("enemy_support" if target["kind"] == TARGET_ENEMY_SUPPORT
                       else "frontline")
                row_label = ("敌方支援线那一行" if key == "enemy_support"
                             else "敌方前线那一行")
                n_before = len([u for u in (field.get(key) or [])
                                if not u.get("is_hq")])
                n_after = len([u for u in (field_after.get(key) or [])
                               if not u.get("is_hq")])
                if n_after < n_before:
                    self.landed += 1
                    self.log(f"[attack] #{self.attempts} 打中了"
                             f"({row_label} {n_before}->{n_after} 张,目标没了)")
                else:
                    # ★★★ 2026-09-13 深夜:**打单位第一次有了硬判据。**
                    #   单位卡上没有能读的血量数字,所以"打中了没有"以前只有
                    #   "那一行还剩几张卡"这一条 —— 打伤但没打死就是"结论不可信"
                    #   (实机 J2 报了 9 次,用户看到的"打了半天没进展"就是这一族)。
                    #   现在加一条**结构判据**:我方攻击者的费用徽章**由橙变灰**
                    #   = 游戏接受了这次行动(§7 第 74 条)。实测 17/17 次打单位都成立。
                    acted = (self._attacker_acted(src.get("badge"), after)
                             if HIT_BY_BADGE else None)
                    if acted is True:
                        self.landed += 1
                        self.log(f"[attack] #{self.attempts} 打中了"
                                 f"({row_label}还是 {n_after} 张 -> **打伤、没打死**;"
                                 f"判据:我方 {src.get('type')} 的徽章由橙变灰"
                                 f"= 这次攻击被游戏接受了)")
                    elif acted is False:
                        self.log(f"[attack] #{self.attempts} 被拒绝"
                                 f"(我方 {src.get('type')} 的徽章**还是橙的**"
                                 f"= 单位没有行动 -> 这次拖拽被游戏拒绝了;"
                                 f"{row_label}还是 {n_after} 张)")
                    else:
                        self.log(f"[attack] #{self.attempts} 结论不可信:"
                                 f"打的是**单位**,读不到它的血量;"
                                 f"徽章判据也没读出来;{row_label}还是 {n_after} 张"
                                 f"(可能没打中 / 没打死 / 只是这一行读数没变)")
                continue

            # ---- 判"打中没有":优先用语义信号(敌方总部血量) ----
            # ★★ 2026-09-12(第六个会话,实机 + 存帧证据):**要读两次,以晚的为准**。
            #   出手前那个盾牌框可以直接照读(快),但"攻击刚落地"那一帧上面正盖着
            #   **伤害飘字/红闪**(存帧 `shots/attack_frames/0912_183108_after.png`:
            #   盾牌位置被一个红色的「2」盖住)—— 那个数字会被当成血量,
            #   于是"打中了没有"要么读不到、要么读成**伤害值**。
            #   所以:① 先照框读一次(能读就读);② 等 1.5 秒让动画放完,再抓一帧读一次,
            #   **第二次读到了就以它为准**,两次不一致时把这件事写进日志。
            hp_after = None
            try:
                hp_after = board.read_hq_hp(after, target)
            except Exception as e:
                self.log(f"[attack] 重读血量出错: {type(e).__name__}: {e}")
            again = None                     # ★ 晚读那一帧留着给"总部卡还在不在"用
            try:
                time.sleep(LATE_HP_WAIT)
                again = self._frame()
                if again is not None:
                    hp_late = board.read_hq_hp(again, target)
                    if hp_late is not None:
                        # ★★★ 2026-09-15:"晚读"读到**不可能的值**时不许直接当结论。
                        #   证据:`17->20`、`11->20`、`10->87`(复验那轮 3 次)—— 血量
                        #   不会变多,所以那是**读数错了**;旧代码把它当权威,于是把
                        #   已经打中的那一发写成"结论不可信"。这里先救读数,再走判据。
                        bogus = (hp_before is not None and hp_late > hp_before)
                        if bogus:
                            self._dump_hp_bogus(again, target, hp_before,
                                                hp_after, hp_late)
                            fixed, why = self._recover_from_bogus_hp(
                                again, target, hp_before, hp_after, hp_late)
                            self.log(f"[attack] 晚读血量 {hp_late} **不可能**"
                                     f"(出手前 {hp_before};血量不会变多)"
                                     f"-> {why}"
                                     + (f",改用 {fixed}" if fixed is not None
                                        else " -> 维持'结论不可信'"))
                            hp_after = fixed if fixed is not None else hp_late
                        else:
                            if hp_after is not None and hp_late != hp_after:
                                self.log(f"[attack] 血量读到两个值(立刻 {hp_after} / 等 1.5s "
                                         f"{hp_late})-> 以晚读的为准(早的那个多半是伤害飘字)")
                            hp_after = hp_late
            except Exception as e:
                self.log(f"[attack] 晚读血量出错: {type(e).__name__}: {e}")
            if hp_before is not None and hp_after is not None:
                if hp_after < hp_before:
                    self.landed += 1
                    self.log(f"[attack] #{self.attempts} 打中了"
                             f"(敌方总部血量 {hp_before} -> {hp_after})")
                elif hp_after > hp_before:
                    # ★ 血量**变多**在物理上不可能 -> 是读数错了,不是"没打中"。
                    #   实测同一回合里先读到 18、后读到 20(真值 20)——把这种
                    #   情况写成"没打中"会把"判据坏了"伪装成"结论"。
                    self.log(f"[attack] #{self.attempts} 血量读数不一致"
                             f"({hp_before} -> {hp_after},变多不可能)-> "
                             f"这次结论不可信,按'没打中'处理")
                else:
                    # ★★★ 2026-09-13 深夜(实机 J2 逐发对账):**"没打中"十有八九是误判**
                    #   —— 伤害生效了,只是盾牌上的数字还没刷新(见 MISS_HP_VERIFY_S)。
                    #   所以在下结论**之前**,先把血量盯一会儿;它掉下来了就按打中算。
                    hp_late2 = self._watch_hp_for_drop(after, target, hp_after)
                    if hp_late2 is not None and hp_late2 < hp_after:
                        self.landed += 1
                        self.log(f"[attack] #{self.attempts} 打中了"
                                 f"(敌方总部血量 {hp_before} -> {hp_late2};"
                                 f"★ 刚出手时读到的是旧值 {hp_after},"
                                 f"数字是隔几秒才刷新的)")
                        continue
                    if hp_late2 is not None:
                        hp_after = hp_late2
                    # ★★ 再问一句"总部卡还在不在"(制胜一击的第二种错法:
                    #    卡已经没了,而血量读数还停在旧值)。
                    if HQ_GONE_IS_KILL:
                        _rows = field.get("rows") or []
                        _row0 = _rows[0] if _rows else {}
                        _n_before = len(_row0.get("units") or _row0.get("boxes") or [])
                        gone, why = self._hq_gone(
                            again if again is not None else after,
                            row_n_before=_n_before)
                        if gone:
                            self.landed += 1
                            self.log(f"[attack] #{self.attempts} 打中了"
                                     f"(敌方总部**卡从画面上消失了** —— 血量读数"
                                     f"停在旧值 {hp_before}->{hp_after},但出手之后"
                                     f"再找一遍总部:{why})-> 判为**打掉了**")
                            continue
                    # ★★★ 2026-09-13 深夜:**再问一句"我方那个单位行动了没有"。**
                    #   这是比血量数字**更早、更硬**的信号(§7 第 74 条:
                    #   橙 = 本回合还没行动过):游戏接受了这次攻击 -> 徽章变灰;
                    #   拒绝了(守护/烟幕/规则不允许)-> **还是橙的**。
                    #   实机账:J1~J4 全部 17 次攻击(含打单位)**17/17 拖后都变灰**,
                    #   也就是说"没掉血"那几次其实都打出去了,只是数字没刷新。
                    acted = (self._attacker_acted(src.get("badge"), after)
                             if HIT_BY_BADGE else None)
                    if acted is True:
                        self.landed += 1
                        self.log(f"[attack] #{self.attempts} 打中了"
                                 f"(★我方单位徽章由橙变灰 = **这次攻击被游戏接受了**;"
                                 f"血量读数仍是 {hp_after} —— 数字还没刷新)"
                                 f"-> 不封总部这一档(它没被打不动,只是读数慢)")
                        continue
                    self.log(f"[attack] #{self.attempts} 没打中"
                             f"(敌方总部血量仍是 {hp_after};"
                             f"{'我方单位也**没有行动**(徽章还是橙的)'
                                if acted is False else '徽章判据读不出,没法佐证'};"
                             f"这个单位大概已经行动过,或类型不能直接攻击)")
                    # ★★★ 2026-09-12(第七个会话):**硬的"没掉血"读数 -> 封总部这一档**
                    #   (只对非炮兵封;炮兵继续试)。判据必须硬:出手前后**两个**读数
                    #   都有效、且一模一样 —— 这就是上面那个 if 的条件,
                    #   血量读不到时会走到下面的"画面差异"分支,**不会**封(§7 第 65 条)。
                    if (HQ_BLOCK_AFTER_MISS
                            and src.get("type") not in HQ_BLOCK_EXEMPT_TYPES):
                        if not self.hq_blocked:
                            self.hq_blocked_all += 1
                        self.hq_blocked = True
                        self.hq_blocked_reason = (f"{src.get('type')} 打它,"
                                                  f"血量 {hp_after} 一动不动")
                        self.log(f"[attack] -> 本回合把【总部】这一档对非炮兵封掉"
                                 f"(可能是敌方**守护**单位护着总部 / **战斗机拦截**了"
                                 f"轰炸机 / 或总部被上了**烟幕**(用户 2026-09-13:"
                                 f"烟幕只存在一回合、特效是无法被攻击);"
                                 f"只有炮兵继续试)。★ 别再拿别的单位白拖;"
                                 f"下面会改去打敌方支援线/前线的单位 —— "
                                 f"那正是「先打掉守护单位」的方向")
                continue

            # ---- ★★★ 2026-09-13 深夜:血量读不到 -> **先问一句"总部卡还在不在"** ----
            #   实机那一发制胜一击(总部 1 血)被记成"被拒绝",而它其实是打掉了。
            #   判据与理由见 `HQ_GONE_IS_KILL` 的整段说明。
            #   ★ 只有真读不到血量时才付这次 `read_field`(约 0.1~1s)。
            if HQ_GONE_IS_KILL and hp_after is None:
                _rows = field.get("rows") or []
                _row0 = _rows[0] if _rows else {}
                _n_before = len(_row0.get("units") or _row0.get("boxes") or [])
                gone, why = self._hq_gone(again if again is not None else after,
                                          row_n_before=_n_before)
                if gone:
                    self.landed += 1
                    self.log(f"[attack] #{self.attempts} 打中了"
                             f"(敌方总部**卡从画面上消失了** —— 血量读不到 "
                             f"{hp_before}/{hp_after},但出手之后再找一遍总部:"
                             f"{why})-> 判为**打掉了**")
                    continue
                self.log(f"[attack] #{self.attempts} 血量读不到,"
                         f"而且总部卡还在/判不了({why})-> 退回画面差异")

            # ---- 血量读不到 -> 退回画面差异,并明确标注 ----
            d = _changed(before, after)
            if d is None:
                self.log("[attack] 画面差异也算不出来,停止攻击")
                break
            if d >= BOARD_CHANGE_MIN:
                self.landed += 1
                self.log(f"[attack] #{self.attempts} 大概打中了"
                         f"(血量读不到 {hp_before}/{hp_after} -> 退回画面差异 "
                         f"{d:.0f})")
            else:
                self.log(f"[attack] #{self.attempts} 被拒绝"
                         f"(血量读不到,画面几乎没变 {d:.0f})")
        return self.attempts, self.landed
