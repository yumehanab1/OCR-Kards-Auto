# -*- coding: utf-8 -*-
"""
dismiss_test.py - **结算页/尾巴页跳过**的离线用例(不需要游戏、不需要窗口、不碰鼠标)。

为什么值得单独一套
------------------
2026-09-21 用户报的"卡在结算页出不来",根因有两条**互相咬住**的:
  ① `tick_dismiss` 里 `if state in ("victory","defeat"): sleep(1.0); return True`
     —— **只睡、不点、也不增 `dismiss_tries`** ⇒ 12 次上限永不触发;
  ② 主循环在 dismiss 期间 `continue`,**绕过** `max_rounds` 退出检查
     ⇒ 引擎既出不来、也不会自己停。
两条都已经修掉(①②分别有下面的 ③/④ 两节钉死)。而这一块在这之前
**零覆盖**(全仓库搜 `import main_loop` 0 命中)—— 所以这一套用例的作用
不是"再验一遍",而是**把这几条判据钉住,以后不许再退化**。

`Controller` 唯一的副作用出口是两个模块级函数(`main_loop.click` 和
`main_loop.client_to_screen`)外加 `Controller.grab_frame`,所以打桩成本极低;
**整套用例不产生任何真实点击**(`click` 被换成记账用的假函数)。

用法(★ 这条用例**不依赖任何帧**,`shots\\` 里没有真值帧也照样全绿):
  set PYTHONPATH=D:\\kards-auto-repo\\src
  D:\\kards-auto\\python\\python.exe -u dev\\dismiss_test.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

import main_loop  # noqa: E402
import actions  # noqa: E402

ALLOK = True


def C(label, cond, extra=""):
    global ALLOK
    ALLOK &= bool(cond)
    print(f"  {'OK ' if cond else 'FAIL'} {label}" + (f"   {extra}" if extra else ""))


# --------------------------------------------------------------------------
# 打桩:①日志只进内存(别写仓库的 logs\)②假时钟(用例不真的睡)
#   ③假帧(不抓屏)④假 click(绝不碰鼠标)
# --------------------------------------------------------------------------
LOGLINES: list[str] = []
main_loop.log = lambda msg: LOGLINES.append(str(msg))     # noqa: E731

#: 源码原文(⑦ 节要钉"退出检查在 `continue` **之前**"这个**位置**,不是行为)。
_SRC_MAIN = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                              "src", "main_loop.py"), encoding="utf-8").read()

#: `_dismiss_note_frame` 的函数体(⑤ 节要断言它**没有**引用 numpy)。
#  ★ 先把两处"`np.abs(...)`"的文字说明剔掉:它们出现在**注释**和**日志文案**里
#    (记录第一版写错过什么),不是代码 —— 一开始没剔,断言把说明当成代码,
#    红了一次。剔完再断言"这一整段里不出现 `np.`"。
_BODY_OF_NOTE_FRAME = (_SRC_MAIN.split("def _dismiss_note_frame")[1]
                       .split("def handle_state")[0].replace("np.abs(...)", ""))


class FakeClock:
    """假时钟:用例里 `sleep(n)` = 时间往前走 n 秒,于是"1.8s 才点一下"这类
    节奏判据可以**确定性地**跑出来,而且整套用例耗时接近 0。"""

    def __init__(self, t0=1_700_000_000.0):
        self.t = t0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += float(s)


CLOCK = FakeClock()
main_loop.time.time = CLOCK.time
main_loop.time.sleep = CLOCK.sleep


class FakeFrames:
    """假截屏:按调用顺序发帧;发完了就重复最后一帧(模拟"画面不动")。"""

    def __init__(self):
        self.frames = []
        self.calls = 0

    def set(self, *frames):
        self.frames = list(frames)

    def grab(self):
        self.calls += 1
        if not self.frames:
            return None
        i = min(self.calls - 1, len(self.frames) - 1)
        return self.frames[i]


FRAMES = FakeFrames()
CLICKS: list[tuple] = []          # 每一次"点了哪里"(客户端坐标)
CLICK_RET = True                  # 让用例能模拟"这一下没点成"


def fake_click(sx, sy):
    CLICKS.append((sx, sy))
    return CLICK_RET


main_loop.click = fake_click
actions.click = fake_click        # `from actions import click` 的另一种取法也堵上


def new_ctl(dry=False, max_rounds=0):
    """造一个不碰窗口的 Controller:只保留被判据用到的那些状态。

    ★ 默认 `dry=False`:这个项目里 `dry`(干跑)意味着 **`click_center` 根本不调
      click**(只看日志),而本用例要看的就是"点了哪个点" —— 所以只有考"干跑不许
      动手"的第 ⑧ 节才用 `dry=True`。
    ★ 无论 dry 是真是假都**不会碰真鼠标**:`main_loop.click` 已经被换成只记账的
      假函数(见文件头)。
    """
    c = main_loop.Controller("kards", dry=dry, max_rounds=max_rounds, end_turn=False)
    c.grab_frame = FRAMES.grab
    # 假换算:客户端坐标直接当屏幕坐标(用例只关心"点了哪个点")。
    c.client_to_screen = lambda x, y: (int(x), int(y))
    return c


def flat_frame(w=320, h=180, val=40):
    """一小张假帧 —— 内容不重要,尺寸/差分才重要(用例**不需要真帧**)。"""
    return np.full((h, w, 3), val, dtype=np.uint8)


def frame_with_patch(w=320, h=180, val=40, patch=250, n=4000):
    """和 `flat_frame` 差一点点的一张帧(用来模拟"画面真的变了")。"""
    f = flat_frame(w, h, val)
    f.reshape(-1, 3)[:n] = patch
    return f


def live_frames(step=60):
    """模拟"**画面在响应**"的客户端:每次抓帧都和上一次明显不同(亮度来回跳)。

    ★ 为什么需要它:2026-09-21 加的 M3 判据是"连点 3 次画面几乎没变就停手"
      —— 拿**不动**的假帧去考"点了 12 次会点到哪",考出来的是 M3 生效之后
      只点 4 次,而不是轮换本身。想考轮换就得先把画面弄成"在变"。
    ★ 为什么是**来回跳**而不是"一直变亮":第一版写的是
      `40 + n*60` 一路变亮,到第 4 帧就**顶到 255 饱和**了 —— 后面每帧都一样,
      于是 M3 照样在第 4 下停手,用例红在一片"莫名"上。
      教训:假帧序列自己也会**饱和**,而饱和的假帧会让判据在**测试里**失效;
      真机上抓的是屏幕,不会这样,所以这个坑只有用例会踩。
    ★ 相邻两帧的亮度差必须 **> DISMISS_DIFF_THRESHOLD(25)** —— 判据是
      "最大差 > 25",差正好 25 **不算变**(第一版取 25,红过一次)。
    """
    box = {"n": 0}
    vals = (40, 40 + step, 40 + 2 * step, 40, 40 + step, 40 + 2 * step)

    def grab():
        box["n"] += 1
        return flat_frame(val=vals[box["n"] % len(vals)])
    return grab


def _fill(c, gap=None):
    """把间隔攒满,让下一 tick 一定会点一下(等价于把真实的等待走掉)。

    ★ 为什么是 `now - (间隔 + 0.2)` 而不是 `now`:一 tick 里
      `_dismiss_note_frame` 自己会 sleep 0.6s,所以"刚设成 now"其实**不足以**
      跨过那道闸 —— 那样写出来的用例会静默地一次都不点
      (本用例第一版真踩到这个坑,是量出来的,不是猜的)。
    ★ `gap` 默认是**快速**闸(1.8s);走慢速重试时要传
      `c._dismiss_retry_gap()`(3~15s),否则同样一次都点不出去。
    """
    g = main_loop.DISMISS_FAST_GAP if gap is None else gap
    c.dismiss_last = CLOCK.time() - g - 0.2


print("=" * 86)
print("① 候选点几何:首选左上角、顺序 左上→右上→左下→右下、不含正中、四点对称")
print("=" * 86)
PTS = main_loop.Controller.dismiss_points()
print(f"  1280x720 基准候选点 = {PTS}")
C("★ 首选是**左上角**(用户 2026-09-21 指定的第一顺位)",
  PTS[0] == (153, 86), f"实得 {PTS[0]}")
C("顺序就是 左上→右上→左下→右下",
  PTS == ((153, 86), (1127, 86), (153, 634), (1127, 634)), f"实得 {PTS}")
C("★ **不含屏幕中心**(用户两次实测'点中心不生效')",
  (640, 360) not in PTS)
# 离中心的距离:四个点必须**一样远**(对称),否则"轮换"就变成了"有的点更靠近中心"
_d = [round(((px - 640) ** 2 + (py - 360) ** 2) ** 0.5, 3) for px, py in PTS]
C("四点离屏幕中心**等距**(对称)", len(set(_d)) == 1, f"距离 {_d}")
C("四点离中心的距离都 > 400px(确实在四个角上,而不是中右部)",
  all(v > 400 for v in _d), f"最近 {min(_d):.0f}px")
for _bad in ((960, 360), (960, 410), (960, 310), (900, 360)):
    C(f"老那套候选点 {_bad}(四个全挤在中右部)已经不在里面了", _bad not in PTS)
C("1920x1080 会跟着比例走(不是写死的像素)",
  main_loop.Controller.dismiss_points(1920, 1080)
  == ((230, 129), (1690, 129), (230, 951), (1690, 951)),
  main_loop.Controller.dismiss_points(1920, 1080))

print()
print("=" * 86)
print("② 轮换 + 12 次上限;取点用的是 tries-1(钉死 off-by-one)")
print("=" * 86)
PTS4 = main_loop.Controller.dismiss_points(320, 180)   # 假帧是 320x180(M7 之后按实际帧算)


def arm(c, tries=0):
    """把控制器摆到"间隔已攒满、下一 tick 就会点"的状态。

    ★ 为什么是 `now - (间隙+0.2)` 而不是 `now`:一 tick 里 `_dismiss_note_frame`
      自己会 sleep `DISMISS_FRAME_SETTLE`(0.6s),所以"刚 arm 完"其实**不足以**
      跨过 1.8s 的快速闸 —— 那样写出来的用例会静默地一次都不点。
      ★ 也不写 `dismiss_last = 0`:假时钟的起点是 1.7e9,那等于"上次点击是
      1.7e9 秒前",和真实运行时的语义差太远。
    """
    c.dismiss = True
    c.dismiss_tries = tries
    c.dismiss_last = CLOCK.time() - main_loop.DISMISS_FAST_GAP - 0.2


FRAMES.set(flat_frame())
CLICKS.clear()                               # ★ 只看本节这些点击
# ★ 本节的控制器必须 `dry=False`:这个项目里 `dry`(干跑)的意思是
#   **只记日志、绝不碰鼠标** —— `click_center` 在 dry 下**根本不调 click**
#   (第 ⑧ 节专门钉这一条)。所以"看点的是哪个点"这件事只能在 `dry=False` 下考。
#   本用例的 `click` 已经是**只记账的假函数**,不会真的动鼠标。
ctl = new_ctl(dry=False)
# ★ 用"画面在响应"的假帧:不然 M3 会在第 4 下就停手,考出来的是 M3 而不是轮换。
ctl.grab_frame = live_frames()
arm(ctl)
picked = []                                  # 每一次**真正点出去**时 tries 的值
# ★ 轮换的真相:一 tick 里"点一下 + 回读一帧(0.6s)"总共推 0.6s,而快速闸是
#   1.8s -> **不是每个 tick 都点**。所以这里按"每次点击"数,不按 tick 数:
#   每轮先把间隔攒满(等价于把真实的等待走掉),再看这一 tick 点没点。
#   ★ 循环上限是硬兜底:判据写坏了也必须**失败退出**,不许把用例挂在这儿
#     (这个仓里栽过"用例自己空转"这种事)。
_guard = 0
while len(CLICKS) < 12 and _guard < 200:
    _guard += 1
    ctl.dismiss_last = CLOCK.time() - main_loop.DISMISS_FAST_GAP - 0.2
    n_before = len(CLICKS)
    ctl.tick_dismiss("level_up")
    if len(CLICKS) > n_before:               # 这一 tick 真的点了一下
        picked.append(ctl.dismiss_tries)
C("12 次点击全都发生了(没卡在别处)", len(CLICKS) == 12, f"实得 {len(CLICKS)}")
C("tries 随每一次点击 +1(1 -> 12)", picked == list(range(1, 13)), picked)
C("12 次之后 dismiss_tries == 12(上限 `>= 12` 正好落在它上面)",
  ctl.dismiss_tries == 12, ctl.dismiss_tries)
# ★ off-by-one 判据:第 n 次点出去的落点必须是 pts[(n-1) % 4]。
#   老写法 `pts[tries % 4]` 会让**第一次点出索引 1(右上)**,首选左上要等第 5 次。
#   ★★ 注意这里的基准**不是 1280x720**:假帧是 320x180,而 M7 之后候选点按
#      **实际帧尺寸**算 —— 所以期望值要用 `dismiss_points(320, 180)` 现算,
#      不许写死 (153,86)。这正好也是 M7 生效的旁证。
WANT_FULL = main_loop.Controller.dismiss_points(320, 180)
WANT = [WANT_FULL[(n - 1) % 4] for n in range(1, 13)]
GOT = [(c[0], c[1]) for c in CLICKS[-12:]]
# 落点带 ±25/±15 的随机抖动(`click_center` 故意加的人味),所以判"落在哪个角附近"。
C("★ 第 1 次点出去的是**索引 0 = 左上角**(老写法会点到索引 1 = 右上)",
  abs(GOT[0][0] - WANT_FULL[0][0]) <= 25 and abs(GOT[0][1] - WANT_FULL[0][1]) <= 15,
  f"实得 {GOT[0]},期望 {WANT_FULL[0]}±抖动")
_NEAR = all(abs(g[0] - w[0]) <= 25 and abs(g[1] - w[1]) <= 15
            for g, w in zip(GOT, WANT))
C("★ 12 次的落点序列 == pts[(tries-1) % 4](off-by-one 钉死)", _NEAR,
  f"实得 {GOT}\n        期望(±抖动) {WANT}")
def _corner(p, w, h):
    """把落点归到"四个角里的哪一个"(抖动范围内)。"""
    return (p[0] < w // 2, p[1] < h // 2)


C("12 次正好把四个角轮了 3 遍",
  [(_corner(g, 320, 180)) for g in GOT]
  == [(_corner(w, 320, 180)) for w in WANT],
  f"出现过的角 {[(_corner(g, 320, 180)) for g in GOT]}")

print()
print("=" * 86)
print("③ ★ 死锁那条:state=='victory' 且已经点过一次之后,tick_dismiss **仍然会点**")
print("=" * 86)
# 老代码在这里 `sleep(1.0); return True` —— 只睡不点、也不增计数,
# 于是 12 次上限永不触发。这条用例就是要让那种写法**再也过不去**。
FRAMES.set(flat_frame())
ctl = new_ctl()
arm(ctl)
n0 = len(CLICKS)
busy = ctl.tick_dismiss("victory")
C("第一次(tries 0->1)点出去了", busy is True and ctl.dismiss_tries == 1,
  f"busy={busy} tries={ctl.dismiss_tries}")
n1 = len(CLICKS)
# 刚点完 -> 给它 1.2s 切画面的宽限期:这一段**不该**再点(也不该丢计数)
busy = ctl.tick_dismiss("victory")
C("刚点完的 1.2s 宽限期内**不点**、也不涨计数(只是等画面切走)",
  busy is True and ctl.dismiss_tries == 1 and len(CLICKS) == n1,
  f"tries={ctl.dismiss_tries} clicks={len(CLICKS) - n1}")
# 等过 1.2s 画面还是 victory -> 必须**当成'那一下没生效'继续点**
CLOCK.sleep(1.3)
busy = ctl.tick_dismiss("victory")
C("★ 等过 1.2s 画面还停在 victory -> **继续点**(老代码在这里只睡不点,永远卡住)",
  busy is True and ctl.dismiss_tries == 2 and len(CLICKS) > n1,
  f"tries={ctl.dismiss_tries} 新增点击={len(CLICKS) - n1}")
C("★ 在 victory 上连点也会**涨计数**(老代码不涨 -> 上限永不触发)",
  ctl.dismiss_tries >= 2, ctl.dismiss_tries)
defeat_ctl = new_ctl()
arm(defeat_ctl)
d0 = len(CLICKS)
defeat_ctl.tick_dismiss("defeat")
C("defeat 同一条路(也要点)", len(CLICKS) > d0 and defeat_ctl.dismiss_tries == 1,
  f"tries={defeat_ctl.dismiss_tries}")
# 反向:切回已知画面就该收手(别把正常流程也一直点着)
ctl2 = new_ctl()
ctl2.dismiss = True
ctl2.dismiss_tries = 7
C("切回 main_menu -> dismiss 关掉、计数归零、返回 False(不再插手)",
  ctl2.tick_dismiss("main_menu") is False
  and ctl2.dismiss is False and ctl2.dismiss_tries == 0)

print()
print("=" * 86)
print("④ ★ M5:12 次用尽之后**不许'什么都不做'**(保留 dismiss + 退避重试)")
print("=" * 86)
FRAMES.set(flat_frame())
ctl = new_ctl()
# ★ "画面在响应"的假帧:本节考的是 **M5**(12 次之后怎么办),得先把 12 次点出去;
#   拿不动的假帧会被 M3 在第 4 下就拦下(那条判据在第 ⑤ 节单独考)。
ctl.grab_frame = live_frames()
arm(ctl)

# ★ 先"垫"一次基准帧:`_dismiss_frame` 的**第一次**取值只是建立基准帧
#   (没有可比的上一次,不算"没动"),所以想凑够 3 次帧差判据就要点 **4** 下。
ctl._dismiss_note_frame()                       # 垫基准帧(不点,只回读一帧)
for _ in range(12):
    _fill(ctl)
    ctl.tick_dismiss("reward_unknown")          # 认不出的奖励页
C("12 次之后 dismiss **仍然是 True**(老代码在这里置 False -> 主循环空转)",
  ctl.dismiss is True, f"dismiss={ctl.dismiss}")
C("dismiss_tries **没有被清零**(计数只有一个真值,快慢两段共用)",
  ctl.dismiss_tries == 12, ctl.dismiss_tries)
# ★ ⚠️ 是**跨过上限那一刻**打的(`dismiss_tries == 12` 时),所以还要再走一 tick
#   让它落进"慢速重试"那一段 —— 这也正是真实运行时的顺序:先点满 12 下,
#   第 13 个 tick 才宣布改走慢速。
_fill(ctl)
ctl.tick_dismiss("reward_unknown")
C("★ 打了一条 ⚠️ 说明'放弃快速跳过、改成慢速重试'",
  any("放弃快速跳过" in s and "慢速重试" in s for s in LOGLINES),
  next((s for s in LOGLINES if "放弃快速跳过" in s), "(没找到)"))
C("⚠️ 里说清了'这不是放弃'(否则用户还是会以为它不动了)",
  any("这不是放弃" in s for s in LOGLINES if "放弃快速跳过" in s))
C("慢速间隔从 DISMISS_SLOW_BASE=3s 起,逐次拉长到 15s 封顶",
  ctl._dismiss_retry_gap() == 3.0, ctl._dismiss_retry_gap())
ctl.dismiss_tries = 13
C("第 13 次:间隔 5s", ctl._dismiss_retry_gap() == 5.0, ctl._dismiss_retry_gap())
ctl.dismiss_tries = 30
C("拉长到封顶 15s 就不再涨(别涨到几分钟,那就等于不试了)",
  ctl._dismiss_retry_gap() == main_loop.DISMISS_SLOW_CAP,
  ctl._dismiss_retry_gap())
# 关键的一条:慢速阶段**还在点**,不是"不动了"
ctl = new_ctl()
ctl.grab_frame = live_frames()      # "画面在响应" -> 本节先不触发 M3
arm(ctl)
for _ in range(12):
    _fill(ctl)
    ctl.tick_dismiss("reward_unknown")
n_before = len(CLICKS)
clicked_slow = 0
for _ in range(8):                              # 再走 8 个 tick
    if ctl.tick_dismiss("reward_unknown") and len(CLICKS) > n_before + clicked_slow:
        clicked_slow = len(CLICKS) - n_before
C("★ 12 次之后**还在点**(慢速重试,不是'什么都不做')", clicked_slow >= 1,
  f"慢速阶段又点了 {clicked_slow} 次")
C("慢速阶段点得**比快的那段稀**(同样 8 个 tick 里,快点能点 8 次)",
  clicked_slow < 8, f"{clicked_slow} < 8")
C("慢速阶段每一个 tick 仍然返回 True(主循环继续把这一屏当'正在跳过')",
  ctl.tick_dismiss("reward_unknown") is True)

print()
print("=" * 86)
print("⑤ ★ M3:帧差判据(连点 3 次画面几乎没变 -> 停手 + ⚠️ 日志)")
print("=" * 86)
C("判据常量就是开发树那套(阈值 25 / 占比 0.001 / 连续 3 次)",
  (main_loop.DISMISS_DIFF_THRESHOLD, main_loop.DISMISS_DIFF_MIN,
   main_loop.DISMISS_STUCK_LIMIT) == (25, 0.001, 3),
  (main_loop.DISMISS_DIFF_THRESHOLD, main_loop.DISMISS_DIFF_MIN,
   main_loop.DISMISS_STUCK_LIMIT))
# 画面**完全不动**:点完回读的帧和上一帧逐像素相同
FRAMES.set(flat_frame())
ctl = new_ctl()
arm(ctl)
# ★ 每 tick 都要先攒满间隔才会点(见 ④ 节 `_fill` 的说明)。
# ★ 判据要**连点 4 次**:第 1 下的回读只是建立基准帧(没有可比的上一次),
#   后面 3 下才各判一次 -> 第 4 下之后 `_dismiss_stuck` 才到 3。
for n in range(1, 5):
    _fill(ctl)
    ctl.tick_dismiss("reward_unknown")
C("连点 3 次画面没变 -> _dismiss_stuck == 3",
  ctl._dismiss_stuck == 3, ctl._dismiss_stuck)
C("★ 打出了 ⚠️ '连点 3 次画面几乎没变' (M3 的核心:把'点了没生效'变成看得见的事实)",
  any("连点 3 次画面几乎没变" in s for s in LOGLINES),
  next((s for s in LOGLINES if "连点 3 次画面几乎没变" in s), "(没找到)"))
C("⚠️ 里带上了帧差数值 dd 和已试次数(没有数字的告警等于没有)",
  any("dd=" in s and "已试" in s
      for s in LOGLINES if "连点 3 次画面几乎没变" in s))
C("⚠️ 里明确**不许**下'客户端卡死'的结论(开发树那次误判过)",
  any("别急着说" in s for s in LOGLINES if "连点 3 次画面几乎没变" in s))
C("★ 判定'没生效'之后**快速那一段不再点**(不然 M3 只是多打一行日志)",
  ctl._dismiss_stuck >= main_loop.DISMISS_STUCK_LIMIT)
n_before = ctl.dismiss_tries
_ = [ctl.tick_dismiss("reward_unknown") for _ in range(3)]
C("接下来几个 tick 里 dismiss_tries 几乎不涨(快点确实停了)",
  ctl.dismiss_tries - n_before <= 1, f"涨了 {ctl.dismiss_tries - n_before}")
# 反向:画面**真的变了** -> M3 的判定要作废,点击恢复
# ★ 这里刻意**从"已经卡住"出发**,而不是"先把画面换成在变的、再看它是 0" ——
#   后者是同义反复(它本来就是 0),等于没考。
C("先把状态摆成'已经卡住'(stuck == 3)", ctl._dismiss_stuck == 3, ctl._dismiss_stuck)
# ★★ 这里是**设计取舍**,不是 bug,写清楚免得读用例的人误会:
#   判据判定"点了没生效"之后,恢复只能发生在**下一次真的点了并回读帧**的时候。
#   而快的那一段已经被 M3 停了,所以恢复点落在**慢速重试那一侧**:
#   慢速那一下(间隔 3~15s)点出去、回读一帧,就会看到画面变了 ->
#   `_dismiss_stuck` 归零 -> 快点立刻恢复。
#   代价:从"判定卡住"到"确认恢复了"中间要等一次慢速间隔(3s 起)。
#   这是有意的:那一刻我们**还不知道**它会不会动,先少抢几次鼠标没坏处。
#   ★ 注意 `main_loop` 里那条判据(main_loop.py `slow_mode`)特意写成
#     "M3 一触发就立刻改走慢速",**不必等计数满 12** —— 否则会出现
#     "快速段被停、计数又到不了 12、两段都不点"的缝(这个缝是本用例量出来的)。
_prev_clicks = len(CLICKS)
ctl.grab_frame = live_frames()                        # 画面开始在变
for _ in range(200):                                  # 推进到"慢速那一下点出去"
    _fill(ctl, ctl._dismiss_retry_gap())
    ctl.tick_dismiss("reward_unknown")
    if ctl._dismiss_stuck == 0:
        break
C("慢速那一下点出去之后,回读发现画面在变 -> `_dismiss_stuck` 归零",
  ctl._dismiss_stuck == 0,
  f"stuck={ctl._dismiss_stuck} tries={ctl.dismiss_tries} clicks={len(CLICKS)}")
C("★ 画面一变 -> 点击恢复(先是慢速那一下;M3 不是'关掉',是'别再无脑重复')",
  len(CLICKS) > _prev_clicks, f"新增点击 {len(CLICKS) - _prev_clicks}")
ctl.dismiss_tries = 0                                 # 回到快的阶段看它会不会恢复
for _ in range(3):
    _fill(ctl)
    ctl.tick_dismiss("reward_unknown")
C("画面持续在变时 `_dismiss_stuck` 一直是 0(不会误判成'卡住')",
  ctl._dismiss_stuck == 0, ctl._dismiss_stuck)
n_fast = len(CLICKS)
for _ in range(3):
    _fill(ctl)
    ctl.tick_dismiss("reward_unknown")
C("★ 恢复之后**快速那一段照常点**(三次里点了三次)",
  len(CLICKS) - n_fast == 3, f"实得 {len(CLICKS) - n_fast}")
# 帧差判据自己:一张"没变"的帧和一张"变了一点"的帧,dd 必须跨过 0.001
_a = flat_frame()
_b = flat_frame()
_c = frame_with_patch(n=20000)
_dd_same = float((np.abs(_a.astype(int) - _b.astype(int)) > 25).mean())
_dd_diff = float((np.abs(_a.astype(int) - _c.astype(int)) > 25).mean())
C("同一帧 dd == 0 < 0.001(判成'没动')", _dd_same == 0.0, _dd_same)
C("真的变了 dd > 0.001(判成'动了')", _dd_diff > main_loop.DISMISS_DIFF_MIN, _dd_diff)
# ★★ 这一条是**踩过才加的**:第一版判据写成 `np.abs(...)`,而 `main_loop` 里
#    根本没有 `import numpy` —— 每次都比出一个 NameError、被 except 吞掉,
#    判据一次都没生效,而日志里只有一行不显眼的"没算成"。所以这里**要求
#    整个用例跑到现在一次都没出现过这条失败** —— 判据"跑过了"必须等于"算出来了"。
_no_calc_error = [s for s in LOGLINES if "帧差判据这次没算成" in s]
C("★ 帧差判据**一次都没有算崩**(算崩 = 告警永远不会响,而日志看不出区别)",
  not _no_calc_error, _no_calc_error[:1])
_np_lines = [l.strip() for l in _BODY_OF_NOTE_FRAME.splitlines() if "np." in l]
# ★ 判据要的是"模块**没有真的 import numpy**" —— 不能直接搜 `import numpy`,
#   因为注释里正好写着"这里没有 import numpy"(第一版就这么把自己判红了)。
_NUMPY_IMPORTED = any(l.strip().startswith(("import numpy", "from numpy"))
                      for l in _SRC_MAIN.splitlines())
C("★ 判据只用了 cv2,没引入 numpy 依赖(本模块**没有** `import numpy`)",
  (not _NUMPY_IMPORTED) and (not _np_lines),
  f"真的 import 了 numpy={_NUMPY_IMPORTED};"
  f" `_dismiss_note_frame` 里的 np. 行={_np_lines[:1]}")
C("回读不到帧(grab_frame -> None)时**不炸、也不算'没变'**",
  (lambda: (setattr(ctl, "grab_frame", lambda: None),
            setattr(ctl, "_dismiss_stuck", 0),
            ctl._dismiss_note_frame(), ctl._dismiss_stuck == 0)[-1])())

print()
print("=" * 86)
print("⑥ ★ M7:四个角按**实际帧尺寸**算,不再写死 1280x720")
print("=" * 86)
# 实测过的坑:上一局结束后窗口会变成 1024x576,那时按 1280 算会让右侧两个点
# 跑到客户区外面(110% 宽度),SetCursorPos 静默夹回 -> 两个点变成同一个位置。
CLICKS.clear()
FRAMES.set(np.full((576, 1024, 3), 40, dtype=np.uint8))
ctl = new_ctl()
arm(ctl)
ctl.tick_dismiss("reward_unknown")
got = CLICKS[-1]
want = main_loop.Controller.dismiss_points(1024, 576)
# ★ 落点带 ±25(横向)/±15(纵向)的随机抖动(`click_center` 故意加的),所以判据是
#   "落在**按 1024x576 算出来的那个角**附近",不是逐像素相等。老写法在这里会给出
#   (1127,86) —— 明显超出 1024 宽的客户区,jitter 再小也兜不住。
C("1024x576 的帧 -> 首选点是按 1024x576 算的左上角 (122,69) 附近",
  want[0] == (122, 69)
  and abs(got[0] - want[0][0]) <= 25 and abs(got[1] - want[0][1]) <= 15,
  f"实得 {got},期望 {want[0]}±抖动")
C("★ 老写法 (1127,86) 会**超出** 1024 宽的客户区(所以 M7 是必须改的)",
  1127 > 1024 and not (abs(got[0] - 1127) <= 25))
C("★ 四个角都落在客户区内(按实际尺寸算出来的)",
  all(0 <= x <= 1024 and 0 <= y <= 576 for x, y in
      main_loop.Controller.dismiss_points(1024, 576)),
  main_loop.Controller.dismiss_points(1024, 576))
C("比例没漂:1024x576 的内缩仍是 12%(153/1280 == 122/1024 那个 0.12)",
  abs(122 / 1024 - 153 / 1280) < 0.001, f"{122 / 1024:.4f} vs {153 / 1280:.4f}")
CLICKS.clear()
FRAMES.set(None)                                  # 抓不到帧 -> 退回 1280x720 兜底
ctl = new_ctl()
arm(ctl)
ctl.tick_dismiss("reward_unknown")
C("抓不到帧时退回 1280x720 兜底(老行为不变;也是 A/B 回退路径)",
  abs(CLICKS[-1][0] - 153) <= 25 and abs(CLICKS[-1][1] - 86) <= 15, CLICKS[-1])
C("帧尺寸变了(1024->1280)不会让帧差相减抛异常",
  (lambda: (setattr(ctl, "_dismiss_frame",
                    np.zeros((144, 256), dtype=np.uint8)),
            setattr(ctl, "grab_frame",
                    lambda: np.full((720, 1280, 3), 40, dtype=np.uint8)),
            ctl._dismiss_note_frame(), True)[-1])())

print()
print("=" * 86)
print("⑦ ★ M6:`--max-rounds` 的退出检查必须在 dismiss 的 `continue` **之前**")
print("=" * 86)
C("`_max_rounds_hit()` 判据只有一处:主循环两条路径都调它",
  hasattr(main_loop.Controller, "_max_rounds_hit"))
ctl = new_ctl(max_rounds=0)
ctl.round_count = 99
C("max_rounds=0 表示'不停'", ctl._max_rounds_hit() is False)
ctl = new_ctl(max_rounds=3)
ctl.round_count = 2
C("还没打满 -> False", ctl._max_rounds_hit() is False)
ctl.round_count = 3
C("打满了 -> True", ctl._max_rounds_hit() is True)
C("数的是'打完一整局'(整个模块里 `round_count += 1` 只出现在 `finish_round` 里)",
  _SRC_MAIN.count("self.round_count += 1") == 1)
# ★ 真正要钉的是**源码里的位置**:dismiss 分支的 `continue` 之前必须有这道检查
_SRC = _SRC_MAIN
_i_dismiss = _SRC.index("busy = self.tick_dismiss(state)")
_i_check = _SRC.index("self._max_rounds_hit()", _i_dismiss)
_i_continue = _SRC.index("continue", _i_check)
C("★ dismiss 分支里:`_max_rounds_hit()` 出现在 `continue` **之前**",
  0 < _i_check < _i_continue,
  f"check@{_i_check} continue@{_i_continue}")
C("而且循环末尾那一处检查还在(正常路径不受影响)",
  _SRC.count("self._max_rounds_hit()") >= 2,
  f"出现 {_SRC.count('self._max_rounds_hit()')} 次")
# ★★★ 光有"位置对"还不够 —— 这里**真的把 run() 跑起来**,在"卡在结算页"的状态下
#   验证循环会退出。为什么非要跑一次:老 bug 恰恰是"源码看起来没问题、
#   运行时被 `continue` 绕过去",这种病只有跑一遍才照得出来。
#   全部依赖(抓帧/状态识别/窗口可见性/click)都打桩,**不碰窗口、不碰鼠标**。
_main_window_is_capturable = main_loop.window_is_capturable
_main_classify = main_loop.classify
try:
    main_loop.window_is_capturable = lambda hwnd, quiet=True: True
    main_loop.classify = lambda frame, templates, states: ("这一屏认不出", {})
    _run_ctl = new_ctl(max_rounds=1)
    FRAMES.set(flat_frame(1280, 720))   # run() 每个 tick 都抓帧,得给一张(不碰真窗口)
    _run_ctl.hwnd = 123
    _run_ctl.max_ticks = 3        # 兜底:万一没停住,用例也不会挂在这儿
    _run_ctl.dismiss = True       # ★ 一进循环就处在"正在跳过"状态(老 bug 的现场)
    _run_ctl.round_count = 1      # 已经打满 --max-rounds 1
    _n_logs = len(LOGLINES)
    _run_ctl.run()
    _run_logs = LOGLINES[_n_logs:]
    C("★ 端到端:卡在结算页(dismiss=True)且打满 max_rounds -> run() **真的退出了**",
      any("max_rounds reached" in s for s in _run_logs),
      f"这一段日志里没出现 max_rounds reached:{_run_logs[-2:]}")
    C("而且**不是**被 max_ticks 兜下来的(那样只证明兜底有用,不证明 M6 修好了)",
      not any("max_ticks reached" in s for s in _run_logs))
finally:
    main_loop.window_is_capturable = _main_window_is_capturable
    main_loop.classify = _main_classify

print()
print("=" * 86)
print("⑧ 既有行为没被弄坏:已知画面收手 / --dry-run 不点鼠标 / 点失败照实记")
print("=" * 86)
for st in ("main_menu", "deck_select", "queueing", "mulligan", "in_game"):
    c = new_ctl()
    c.dismiss = True
    c.dismiss_tries = 5
    C(f"state={st} -> 立刻收手(dismiss=False, tries 归零)",
      c.tick_dismiss(st) is False and c.dismiss is False and c.dismiss_tries == 0)
c = new_ctl()
c.dismiss = False
C("本来就没在 dismiss -> 一个 tick 都不碰", c.tick_dismiss("victory") is False)
CLICKS.clear()
FRAMES.set(flat_frame())
c = new_ctl(dry=True)                 # dry-run:只记日志,绝不碰鼠标
arm(c)
c.tick_dismiss("reward_unknown")
C("--dry-run 下**一次都不点**(click 没被调用)", len(CLICKS) == 0, CLICKS)
CLICKS.clear()
FRAMES.set(flat_frame())
c = new_ctl(dry=False)
arm(c)
CLICK_RET = False                      # 模拟"鼠标被系统挡住、这一下没点成"
try:
    c.tick_dismiss("reward_unknown")
finally:
    CLICK_RET = True
C("点失败(click 返回 False)时**照实记一条**,不假装点过了",
  any("这一下没点成" in s for s in LOGLINES))
C("点失败也照样涨计数(否则会无限重试同一个点)",
  c.dismiss_tries == 1, c.dismiss_tries)

print()
print("=" * 86)
print("全部通过" if ALLOK else "存在失败项")
print("=" * 86)
sys.exit(0 if ALLOK else 1)
