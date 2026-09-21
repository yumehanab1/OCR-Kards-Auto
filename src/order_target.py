"""
order_target.py - 「这张 target 指令现在该往哪个坐标拖」的**唯一来源**(纯函数,可离线测)。

为什么需要它
------------
2026-09-20 用户把 674 张指令/反制的打法逐张给了出来(`config/order_plays.json`),
其中 **211 张是 `target`(需要目标)**。而"指令怎么选目标"这件事上,用户确认的模型是
(`docs/order_cards_review.md` 第 5~6 行原话):

    「打指令卡有两种手势(你确认的)——**不需要选目标的拖到中线以下**就打出,
     **需要选目标的要拖到那张卡/总部上**。」

⇒ target 指令 = **把牌从手牌拖到那张目标卡(或总部)身上再松手**,和部署单位走同一套
  拖拽,只是**落点 = 目标卡的中心**,而不是空槽位。**没有"打出之后再点目标"这一步。**
所以这个模块只回答一件事:**落点 (x, y) 是多少**。
拖拽本身仍走现成的 `deploy.drag_deploy(...)`,成/败仍走现成的
`turn_engine._judge_deploy(..., is_order=True)`(指令不占槽位,只看费用对账)。

判据从哪来(★ 一处都不自己造)
------------------------------
* 目标码/行码/两步:`orders.target_spec()` —— **只有 `orders.py` 读那个 JSON**;
* 战场上的单位/总部:`board.read_field()` 的返回值(本模块**不截屏、不悬停、不动鼠标**);
* **前线那一行的归属**:`frontline_line.read_frontline_owner()` ——
  `board.py` 第 1411~1414 行明确警告:前线归属读不出时**绝不能**把前线单位当我方;
* 落点的合法范围:`board` 里那几条战场分区定义(`BOARD_X0/X1`、`BOARD_Y0`、`HAND_MIN_Y`)。

★★ fail-closed(这个模块的纪律,一条都不许松)
  下面任何一项不成立,一律返回 **None**,由调用方放弃打这张牌并如实写日志:
    · 这张牌不在「需要目标」那一档 · 目标码不认识 · kind 7(三选一)· follow 非空(两步卡)
    · 战场没读出来(field 没有行结构 / 结构不对)· 行码要求前线归属、而归属读不出
    · 候选为空 · 候选卡没有坐标 · 坐标越界(不在战场区 / 落进手牌区)
  **绝不允许"猜一个点拖过去"** —— 指令打错目标的代价是白扔一张牌 + 一次真实拖拽,
  而"乱拖打不出去的牌"正是这个项目最想消除的举报源。

★★ kind 6「随意阵营单位」:一条规则 —— **一律指敌方**(2026-09-21 用户决定)
  用户 2026-09-21 明确说"**kind6 全部指敌方**",包括之前被逐卡定向表判成"我方"的
  那三张。所以这一档**不再有**"逐卡定向表 + 表外 fail-closed"那两层结构,
  就一条常量 `KIND6_SIDE`(见常量区);依据是**用户决定**,不是卡面推断。
  ★ 留一行备查(不参与判定):`帝国指令`(完全修复 1 个单位,使其获得 +1+1)、
    `运输补给`(使前线 1 个单位获得 +2+3)、`捕风捉影`(使其移至前线)这三张的**卡面**
    看着像"我方受益"(打在敌方单位上像是给对手加成)—— 上一版就是按卡面把它们
    判成"我方"的,用户**看过这条提醒之后**仍然要求"全部指敌方",故以用户为准。
    ⇒ 若实机发现这三张打出去不对劲(例如给对手回血/加成),先来这里对账。

★ 多个合法目标时挑哪个(用户**没有**给偏好规则,这里是本模块的确定性默认)
  固定顺序一句话:
      阵营(kind 6 = 敌方;其它档本来就只有一侧有候选)
      -> 单位优先于总部
      -> 行(顺序由 `ROW_RANK` 现生成:敌方前线 > 敌方支援 > 我方支援 > 我方前线)
      -> 靠左优先(x 小的先)
  每一级的依据(能追到项目里已有的判据,不是新发明的口味):
  · **单位优先于总部**:① kind 1 的语义就是"指定敌方单位(**打不了总部**)" —— 单位才是
    这类指令的默认对象;② `board.py` 记着总部判定的已知误报(带【守护】的步兵卡被读成
    "盾牌 + 血量 22",57 帧 / 142 行里出现 4 行)—— 有单位可打时,不赌总部那一档。
  · **敌方前线优先于敌方支援**:用户确认的规则链是"先能打相邻战线 -> 才能清掉前线 ->
    才能上前线"(`frontline_line.py` 文件头引 §7 第 69 条 / §10);挡在前线的那一批
    正是**最靠近我们、且挡着我们推进**的目标。
  · **靠左优先**:纯粹是确定性的 tie-break —— 左右偏好**没有任何画面证据**,写成"靠左"
    只为了两件事:同一帧跑两次结果一样、日志里能一句话讲清(见 `dev/order_target_test.py`)。

★ kind 5「选择一张手牌」:**本模块现在收不到它**(2026-09-21 起整档归黑名单)
  用户 2026-09-21 决定"kind5进黑名单",判据与 A/B 开关在 `orders.py` 的
  `KIND5_AS_BLACKLIST`(`playable()` 不放行、`is_blacklisted()` 返回 True ->
  引擎会给"别带这张"的提示)。本模块**保留** kind 5 那段实现当兜底:
  万一以后开关翻回 True,它对"认不出是单位的那张手牌"仍然 fail-closed(不打),
  不会退回"瞎挑最靠左那张"。为什么当初要这么严:这一档里有几张天生要求
  "选一张**单位**"(例如 `势不可挡` / `金属废料` / `特别任务`),选到非单位时
  游戏多半忽略这一下,而引擎只按费用对账会记成"指令打出",
  还会把那个下标从手牌记忆里删掉(手牌/记忆错位)。

用法(引擎侧只有两行)
--------------------
    got = order_target.pick(name, field, frame=frame, hand_xs=..., hand_y=...,
                            debug=self.debug, log=self.log)
    if got is None:   # 判不出目标 -> 不打(原因已经由 log 打出去了)
        ...
    drop = (got["x"], got["y"])

`dev/order_target_test.py` 是本模块的离线用例(不需要游戏、不需要屏幕)。
"""

from __future__ import annotations

import board
import frontline_line
import orders

# ---------------------------------------------------------------------------
# 常量(每一个都写清来源 —— 这个项目里"看着差不多"的数都是坑)
# ---------------------------------------------------------------------------

#: 客户端坐标系(client 1280x720)。来源:`win.set_window_client_size(hwnd, 1280, 720)`
#: 是项目里唯一的窗口尺寸(`deploy.py` 的 `__main__`、`frontline_line.save_region`
#: 的注释都按这个坐标系写)。
CLIENT_W, CLIENT_H = 1280, 720

#: 「选择一张手牌」那一档的落点 y = **手牌悬停行**。
#: = `hand_scanner_v2.PROBE_Y`(700) = `deploy.drag_deploy(card_y=700)`。
#: ★ 引擎会用 `hand_y=self.scanner.y` 显式把扫描器当前的悬停行传进来(那才是真判据);
#:   这里是"调用方拿不到时的默认值",不是一个我们自己拍的数。
HAND_ROW_Y = 700

#: ★★ kind 6「随意阵营单位」指向哪一侧 —— **一条规则:`enemy`(敌方的单位)**。
#:
#: 依据:**用户 2026-09-21 的决定,原话"kind6全部指敌方"**。
#:   ★ 这不是"按卡面推断"出来的:上一版曾经按卡面把三张判成"我方" ——
#:     `帝国指令`(完全修复 1 个单位,使其获得 +1+1)、
#:     `运输补给`(使前线 1 个单位获得 +2+3)、
#:     `捕风捉影`(指向 1 个单位,使其移至前线);
#:     理由是这三张打在**我方**单位上才像"帮自己"。
#:     用户**看过这条提醒之后**仍然明确要求"全部指敌方",故以用户为准,
#:     这里不留逐卡例外、也不留"表外 fail-closed"的中间态 —— 就一条规则。
#:   ★ 备查(不参与判定):若实机发现这三张打出去不对劲(例如像是给对手回血/加成),
#:     先来这里对账 —— 改法就是把这一条常量翻成 "our" 或重新引入逐卡例外,
#:     而不是去动别的地方。
#: ★ rows 的收窄**照旧生效**:这条规则只决定"哪一侧",具体哪一行仍由 units 表的
#:   `rows` 决定(例:`6-cd` + 敌方 => 实际只有 c 那一侧;`运输补给` `6-ab` + 敌方
#:   => 实际只有 a,即敌方前线)。
#: 值 ∈ {'enemy', 'our'};`None` = 这一档不打(现在不会用到,留着是为了让"翻成不打"
#: 也能一句话做到)。
KIND6_SIDE = "enemy"

#: 行码 -> 排序权重(越小越先挑):敌方前线 > 敌方支援 > 我方支援 > 我方前线。
#: ★ 行码的语义以 `dev/order_plan.py` 的 `ROW_KIND` 为准:
#:   a=仅前线敌方单位 / b=仅前线友方单位 / c=仅敌方支援阵线 / d=仅我方支援阵线。
#:   这里是"**多个候选都合法**时先挑哪一行",不是合法性判断(合法性由 rows 过滤做)。
ROW_RANK = {"a": 0, "c": 1, "d": 2, "b": 3}

#: 行码 -> 人话(只用于日志)
ROW_TEXT = {"a": "敌方前线", "b": "我方前线", "c": "敌方支援线", "d": "我方支援线"}


def row_order_text():
    """
    "行偏好顺序"那句话 —— **从 `ROW_RANK` 现生成**。

    ★ 为什么要现生成:上一版在 `why` 里手写了 `行(敌前线>敌支援>我支援)`,
      把真实存在的第 4 档"我方前线"(`ROW_RANK["b"] = 3`)漏掉了 —— 而 kind 6 +
      rows=ab + 归属=我方那一路上**真的会**挑我方前线。手写副本 = 日志撒谎
      (§7 第 67/68 条:诊断与代码分家就是这个项目反复吃的亏)。
    """
    order = sorted(ROW_RANK.items(), key=lambda kv: kv[1])
    return ">".join(ROW_TEXT.get(k, k) for k, _v in order)


#: 认得出"是单位"的手牌类型 —— 和 `orders.playable()` 认的那五个**同一套词汇**
#: (`src\orders.py` 的 `playable()`:`infantry / tank / fighter / bomber / artillery`)。
#: ★ 只用于 kind 5「选择一张手牌」:那几张"选择并弃 1 张**单位**"的卡必须拿到单位。
UNIT_TYPES = ("infantry", "tank", "fighter", "bomber", "artillery")


def _side_text(side):
    return {"enemy": "敌方", "our": "我方"}.get(side, str(side))


def _kind6_side_text():
    """kind 6 那条规则的人话 —— 写进 why / "不打"的日志里,连带把依据写出来。"""
    return (f"{_side_text(KIND6_SIDE)}(依据:用户 2026-09-21 决定「kind6 全部指敌方」)"
            if KIND6_SIDE else "不打(KIND6_SIDE 被设成 None)")


#: 目标码 -> 人话(**只用于日志**)。
#: ★ 语义**以 `dev/order_plan.py` 的 `TARGET_KIND` 为准**(用户原话的落点)。
#:   这里是它的"展示副本":选目标只按**数字**分支(见下面的 if),抄错只会让日志难看,
#:   不会让选错目标。`dev/order_target_test.py` 会逐条比对这两份,抄错就跑红。
KIND_TEXT = {
    "1": "指定敌方单位(打不了总部)",
    "2": "敌方单位或总部",
    "3": "指定敌方总部",
    "4": "我方单位",
    "5": "选择一张手牌",
    "6": "随意阵营单位",
    "7": "三选一",
}


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _unit_list(field, key):
    """
    取 `field[key]` 这个单位列表,返回 `(列表, 出错原因)`。

    ★ 必须把"空列表"和"结构不对"分开:`board.read_field` **一定会**给出这三个键
      (哪怕是空列表),所以"键不是列表"只可能意味着**调用方传了别的东西** ——
      最常见的是 `board.battlefield_snapshot` 的返回值(那个结构里 `our_support`
      是 `(张数, 诊断)` 的元组)。那种情况必须 fail-closed,
      **不许**把它当成"这一行没有卡"(那就是"诊断在撒谎").
    """
    v = (field or {}).get(key)
    if isinstance(v, list):
        return v, ""
    if v is None:
        return None, f"field 里没有 {key!r}"
    return None, f"field[{key!r}] 不是列表(是 {type(v).__name__})"


def _cand(u, side, letter, src, is_hq=None):
    """
    把一个 `board.read_field` 里的单位 dict 变成候选。

    ★ 坐标读不出来 -> 返回 None(那一张**直接不算候选**,不许拿 0 当坐标)。
    """
    if not isinstance(u, dict):
        return None
    try:
        x = int(round(float(u["cx"])))
        y = int(round(float(u["cy"])))
    except Exception:
        return None
    hq = bool(u.get("is_hq")) if is_hq is None else bool(is_hq)
    return {"x": x, "y": y, "side": side, "is_hq": hq, "row": letter, "src": src,
            "what": f"{src}{'总部' if hq else '单位'}"}


def _field_point_ok(x, y):
    """
    这个落点在**战场卡片区**里吗。

    ★ 边界全部借用 `board.py` 的战场分区定义,不在这里另写常数:
      · x ∈ [BOARD_X0, BOARD_X1] —— 那句话本身就是"避开左右两侧的装饰/HUD";
      · y ∈ [BOARD_Y0, HAND_MIN_Y) —— 上边界"避开顶部手牌堆",下边界是
        "这个 y 以下是我方手牌"。**落进手牌区 = 拖到自己的手牌上**,那不是打目标。
    """
    try:
        return (board.BOARD_X0 <= int(x) <= board.BOARD_X1
                and board.BOARD_Y0 <= int(y) < board.HAND_MIN_Y)
    except Exception:
        return False


def _coerce_x(v):
    """一个候选值(裸数字 或 {'x':..})-> 合法 x 或 None(越界/非数字/布尔值一律丢)。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, dict):
        v = v.get("x")
    try:
        x = int(round(float(v)))
    except Exception:
        return None
    return x if 0 < x < CLIENT_W else None


def _hand_cards_clean(hand_cards, hand_xs):
    """
    kind 5 的候选 -> `[{"x": int, "type": str|None, "i": int|None}]`(按 x 升序去重)。

    两种输入都收:
      · `hand_cards`(推荐):`[{"x": 492, "type": "infantry", "i": 3}, ...]`
        —— `type` 是扫描器认出来的类型,**kind 5 靠它判"这是不是单位"**;
      · `hand_xs`(旧写法,裸 x 列表):类型一律 **None(未知)** —— 于是 kind 5
        fail-closed(见 `_pick_hand` 的说明:认不出是单位就不许选)。

    ★ 丢掉而不是夹取:夹取会把落点推到一张**别的**牌上(`deploy.slot_candidates`
      里为同一个理由也是"越界的直接丢")。
    """
    out = {}
    src = list(hand_cards or []) + list(hand_xs or [])
    for k, item in enumerate(src):
        x = _coerce_x(item)
        if x is None:
            continue
        typ = None
        idx = None
        if isinstance(item, dict):
            typ = (item.get("type") or "").strip().lower() or None
            idx = item.get("i") if isinstance(item.get("i"), int) else None
        cur = out.get(x)
        if cur is None:                     # 第一次见到这个 x
            out[x] = {"x": x, "type": typ, "i": idx}
        else:                               # 同一张牌被两个来源各报一次 -> 合并身份
            if cur["type"] is None and typ is not None:
                cur["type"] = typ
            if cur["i"] is None and idx is not None:
                cur["i"] = idx
    return [out[x] for x in sorted(out)]


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def pick(name, field, frame=None, hand_xs=None, hand_y=None,
         hand_cards=None, debug=False, log=None):
    """
    这张 target 指令现在该往哪个坐标拖。

    参数
    ----
    name      卡名(引擎手里只有卡名;`kind/rows/follow` 由 `orders.target_spec` 现查)。
    field     **`board.read_field()` 的返回值**(不是 `battlefield_snapshot` 的那个结构):
              用到的键是 `rows` / `enemy_support` / `our_support` / `frontline` /
              `hq_enemy`(`hq_enemy` 就是"敌方总部"那一条 —— `read_field` 从敌方支援线
              那一行里按 `is_hq` 找出来的;它没有单独的坐标,`cx/cy` 在单位 dict 里)。
    frame     **和 `field` 同源的那一帧**(用来读前线归属)。
              ★ 不传也能跑,但那时"前线归属"要另抓一次当前画面,和 `field` 就对不上了
                (不同源的两份读数做同一个决定 = 早晚出鬼)。
    hand_cards
              **可以作为目标的手牌各张(带身份)** —— kind 5「选择一张手牌」用,
              这是**推荐**写法:`[{"x": 492, "type": "infantry", "i": 3}, ...]`。
              ★ `type` 决定"能不能选它":这一档里有几张天生要求"选一张**单位**",
                认不出类型的一律不算候选(fail-closed)。
              ★ 调用方应当把**正在拖出去的那张牌自己排除掉** —— 拖到自己身上不是
                "选择一张手牌"。
    hand_xs   旧写法的裸 x 列表(可与 `hand_cards` 混用)。**没有类型信息** ->
              kind 5 一律 fail-closed(不打)。留它是为了兼容与可测。
    hand_y    手牌悬停行 y(引擎传 `scanner.y`);不传用 `HAND_ROW_Y`。
    debug     True 时额外 print 候选清单(诊断用,不影响返回值)。
    log       可调用的日志函数(通常是引擎的 `self.log`)。**判不出目标时**它会收到
              **一行**完整的人话原因(`[order_target] 「X」不打(判不出目标)—— ...`);
              判得出目标时不打任何东西(调用方拿返回值自己写那一行)。

    返回
    ----
    成功:`{"x": int, "y": int, "why": str, "kind": str, "what": str, ...}`
          · `what` 是人话目标名(如 "敌方支援线单位" / "敌方总部" / "手牌"),
            日志里直接写成 `目标{what}({x},{y})`;
          · `why` 是**一行**"为什么挑它"(候选几个、按什么顺序挑的、前线归属是什么),
            和结论写在一起 —— 这个项目反复吃过"判据和结论分家"的亏;
          · 另有 `rows` / `row` / `src` / `side` / `is_hq` / `n`(候选数)几个附加键,
            只给日志/诊断用(`row` 是选中那张所在的行码 a/b/c/d;手牌目标是空串)。
            kind 5 另有 `hand_x` / `hand_type` / `hand_index`(挑中的是哪一张)。
    失败:**None**(并且已经通过 `log` 说清原因)。调用方必须放弃这张牌。
    """
    spec = orders.target_spec(name)
    kind = str((spec or {}).get("kind") or "").strip()
    rows = str((spec or {}).get("rows") or "").strip().lower()
    follow = str((spec or {}).get("follow") or "").strip()

    def _fail(why):
        line = f"[order_target] 「{name}」**不打**(判不出目标)—— {why}"
        if log is not None:
            try:
                log(line)
            except Exception:            # 日志坏了绝不许弄崩一次决策
                pass
        if debug:
            print("    " + line)
        return None

    # ---- ① 这张牌本身合不合格(判据在 orders.py,这里只是"我没实现它"的显式拒绝)----
    #   ★ 这一层是**兜底**:调用方本来就不该把这种牌送进来(`orders.playable()` 已经
    #     挡住 kind 7 和两步卡)。两层都指向同一个结论,真正的判据仍在 `orders.py`。
    if not spec:
        return _fail("它不在「需要目标」那一档(打法表里没有这张牌,或者 mode 不是 target)")
    if kind == "7":
        return _fail(f"目标码 7 = {KIND_TEXT['7']}(打出后弹三张卡)—— 本次不做")
    if kind not in ("1", "2", "3", "4", "5", "6"):
        return _fail(f"目标码 {kind!r} 不认识(fail-closed)")
    if follow:
        return _fail(f"两步卡(follow={follow}:打出后还要再来一次)—— 本次不做")

    # ---- ② kind 5「选择一张手牌」:目标在**手牌**里,和战场结构无关 ----
    if kind == "5":
        return _pick_hand(name, rows, hand_cards, hand_xs, hand_y, _fail, debug)

    # ---- ③ 其余几档都要读战场 ----
    if (not isinstance(field, dict) or not isinstance(field.get("rows"), list)
            or not field.get("rows")):
        return _fail("战场读不出来(field 没有行结构)—— 这一档要从盘面上挑目标")
    enemy_sup, w1 = _unit_list(field, "enemy_support")
    our_sup, w2 = _unit_list(field, "our_support")
    front, w3 = _unit_list(field, "frontline")
    bad = w1 or w2 or w3
    if bad:
        return _fail(f"field 结构不对({bad})—— 传进来的不是 board.read_field 的返回值?")

    # ---- ④ 前线归属(★ 只有真需要时才读:它要去找那条黑线,不便宜)----
    #   "需要"的两种情况:
    #     · 行码里有 a/b —— 合法性**本身**就建立在归属上;
    #     · 前线那一行有卡,而这一档的候选包含"敌方前线单位"。
    #   拿不到归属时的处置**分两种**(不能一刀切):
    #     · 行码要 a/b -> 判不出归属就没法确认合法 -> fail-closed(不打);
    #     · 只是"前线有卡" -> **把前线单位排除在候选之外**,其余照常挑
    #       (board.py 1411 行:前线归属读不出时绝不许把前线单位当我方;
    #        对称地,也不许当敌方 —— 少几个候选是安全侧)。
    owner, owner_why = None, "没读(这一档不需要前线归属)"
    if front or ("a" in rows) or ("b" in rows):
        try:
            info = frontline_line.read_frontline_owner(frame=frame, field=field) or {}
        except Exception as e:
            info = {"owner": None, "why": f"{type(e).__name__}: {e}"}
        owner = info.get("owner")
        owner_why = info.get("why") or "(没说原因)"
        if debug:
            print(f"    [order_target] 前线归属={owner!r} | {owner_why}")
    if ("a" in rows or "b" in rows) and owner is None:
        return _fail(f"行码 {rows} 要求按前线归属挑,但归属读不出({owner_why})")

    # ---- ⑤ 按 kind 收集候选(来源映射见 orders.TARGET_KINDS_OK 上方的语义)----
    #   ★ kind 6 的方向 = `KIND6_SIDE` 那**一条规则**(2026-09-21 用户决定"全部指敌方")。
    #     它说"敌方"就**不**收集我方单位 —— 否则排序第一级还会把另一侧挑出来,
    #     那就等于规则没生效。`KIND6_SIDE` 被设成 None 时这一档直接不打。
    k6_side = KIND6_SIDE if kind == "6" else None
    if kind == "6" and k6_side is None:
        return _fail("kind 6 被判成不打(KIND6_SIDE=None)-> fail-closed")
    want_enemy = kind in ("1", "2") or (kind == "6" and k6_side == "enemy")
    want_our = kind == "4" or (kind == "6" and k6_side == "our")
    cands = []
    if want_enemy:
        # 敌方支援线上的**单位**(总部单列,见下)
        for u in enemy_sup:
            if u.get("is_hq"):
                continue
            c = _cand(u, "enemy", "c", "敌方支援线")
            if c:
                cands.append(c)
    if kind in ("2", "3"):
        # 敌方总部。★ 只用 `field["hq_enemy"]`(盾牌判据),**不**退到 `find_enemy_hq`
        #   的 OCR 兜底 —— board.py 量过:盾牌 45 帧里 91/92 读得出,而 OCR 那条老路
        #   20 张存帧里只有 3 张读得到,还可能把**单位卡**认成总部(§10 记过)。
        #   指令打错目标的代价是白扔一张牌,所以"读不出就不打"比"赌一个总部"好。
        hq = field.get("hq_enemy")
        c = _cand(hq, "enemy", "c", "敌方", is_hq=True) if hq else None
        if c is None and kind == "3":
            return _fail("敌方总部读不出来(field 里没有 hq_enemy)"
                         "—— kind 3 只打总部,没有别的目标可挑")
        if c:
            cands.append(c)
    if want_our:
        # 我方单位。★★ **只从 `our_support` 取**(总部的 `is_hq` 也排除:用户确认
        #   上限 4 是【单位卡】,总部不是单位)。绝不从 `frontline` 里取我方单位 ——
        #   `board.py` 1411~1414 行:那一行的归属是争夺的,认错了就是"拖自己人"
        #   (§10 记的本项目最危险的错误)。
        for u in our_sup:
            if u.get("is_hq"):
                continue
            c = _cand(u, "our", "d", "我方支援线")
            if c:
                cands.append(c)
    if want_enemy and owner == "enemy":
        # 敌方前线(★ 只有**判出归属是敌方**时才算敌方 —— 见 ④ 的说明)
        for u in front:
            if u.get("is_hq"):
                continue           # 前线行不会有总部:read_field 不对前线跑总部判定
            c = _cand(u, "enemy", "a", "敌方前线")
            if c:
                cands.append(c)
    if kind == "6" and owner == "our":
        # 我方前线(**只有 kind 6 会算**):归属明确是"我方"时,`frontline_line` 的
        # 结论可以直接用(front_mover / attack 两路已经在用同一个判据)。
        # ★ kind 4 不走这里 —— 那一档按硬规矩只从 `our_support` 取,所以行码 b
        #   (仅前线友方单位)对 `战术撤退`(4/b)会**永远挑不出目标**(fail-closed,不打)。
        for u in front:
            if u.get("is_hq"):
                continue
            c = _cand(u, "our", "b", "我方前线")
            if c:
                cands.append(c)

    # ---- ⑥ 行码:先把候选项收窄(收窄后没有候选 = 返回 None)----
    #   ★ rows 照旧生效:`6-cd` + 敌方 => 行码把 d(我方支援)滤掉,实际只剩 c;
    #     `运输补给` `6-ab` + 敌方 => 只剩 a(敌方前线)。
    n_before_rows = len(cands)
    if rows:
        cands = [c for c in cands if c["row"] in rows]
    # ★ kind 6:行码把 rule 那一侧的候选全滤掉了 -> 也要 fail-closed,
    #   不许拿另一侧的卡凑数(规则说指敌方,就不能拿我方的卡顶上)。
    if kind == "6" and cands and (not any(c["side"] == k6_side for c in cands)):
        return _fail(
            f"kind 6 这张牌按规则该指**{_side_text(k6_side)}**单位,但行码 "
            f"{rows} 下候选里一张{_side_text(k6_side)}的都没有"
            f"(收窄前 {n_before_rows} 个)-> 不许拿另一侧凑数,不打")
    if not cands:
        extra = (f";行码 {rows} 把候选全滤掉了(收窄前 {n_before_rows} 个)"
                 if (rows and n_before_rows) else "")
        return _fail(
            f"没有候选目标(kind={kind} {KIND_TEXT.get(kind, '')},rows={rows or '不限'};"
            f"盘面:敌支援 {len(enemy_sup)} 张 / 我支援 {len(our_sup)} 张 / "
            f"前线 {len(front)} 张,前线归属 {owner!r}){extra}")

    # ---- ⑦ 坐标合法性(越界的一律丢,一个都不许"夹取")----
    okc, bad_pts = [], []
    for c in cands:
        (okc if _field_point_ok(c["x"], c["y"]) else bad_pts).append(c)
    if not okc:
        return _fail(f"{len(cands)} 个候选的坐标**全部越界**(战场区 x "
                     f"{board.BOARD_X0}~{board.BOARD_X1} / y {board.BOARD_Y0}~"
                     f"{board.HAND_MIN_Y - 1})—— 多半是读错了行,不打")

    # ---- ⑧ 确定性排序,取第一名(顺序的依据见模块 docstring)----
    #   ★ 阵营那一级:kind 6 只给 `KIND6_SIDE` 那一侧权重 0(别的侧即使进了候选
    #     也排后面);其余各档两侧本来就只有一侧有候选,给了也不改变任何结果。
    pref_side = k6_side
    side_rank = {pref_side: 0} if pref_side else {}
    if kind == "6":
        side_txt = _kind6_side_text()
    else:
        side_txt = "/".join("敌" if s == "enemy" else "我"
                            for s in ("enemy", "our"))
    okc.sort(key=lambda c: (side_rank.get(c["side"], 9),
                            1 if c["is_hq"] else 0,
                            ROW_RANK.get(c["row"], 9),
                            c["x"]))
    best = okc[0]
    why = (f"kind={kind}({KIND_TEXT.get(kind, '?')}) rows={rows or '不限'} "
           f"候选{len(okc)}个 -> 多个合法目标时按固定顺序取第一名"
           f"[阵营({side_txt}) > 单位优先于总部 > 行({row_order_text()}) > 靠左]"
           f" -> 取「{best['what']}」;落点=目标卡中心"
           f"(用户没给偏好规则,这是 order_target.py 的确定性默认,见它的文件头);"
           f"前线归属={owner!r}")
    if bad_pts:
        why += f";⚠️{len(bad_pts)}个候选坐标越界已丢"
    if debug:
        print(f"    [order_target] {why}")
        print("      候选:" + ", ".join(
            f"{c['what']}({c['x']},{c['y']})/行{c['row']}" for c in okc[:8]))
    out = {"x": int(best["x"]), "y": int(best["y"]), "why": why,
           "kind": kind, "what": best["what"], "rows": rows,
           "row": best["row"], "src": best["src"], "side": best["side"],
           "is_hq": best["is_hq"], "n": len(okc)}
    if kind == "6":
        out["kind6_side"] = k6_side      # 诊断:这一个是按定向表哪一侧挑的
    return out


def _pick_hand(name, rows, hand_cards, hand_xs, hand_y, _fail, debug):
    """
    kind 5「选择一张手牌」的落点。

    ★★ 挑哪一张:**只挑认得出是单位的那张**,并且取其中最靠左的一张。
      为什么必须按单位挑(2026-09-21 修):这一档 10 张里有 `势不可挡` /
      `金属废料` / `特别任务` 天生要求"选一张**单位**"(卡面见
      `docs\\order_cards_plan.md`),而旧版无条件取最靠左那张 —— 选到非单位时
      游戏多半不认这一下,引擎却按费用对账记成"指令打出",还会把那个下标从
      手牌记忆里删掉(手牌/记忆错位)。
      ★ 另外 7 张(**试验飞行 / 好高骛远 / HMAS 瓦拉孟加号 / 权衡 / 黑夜巡视 /
        调整 / 贝克街分队**)接受任意手牌,但给它们一张单位**永远不会选错**
        (它们要么"选一张弃掉"、要么"选一张挪位置/洗回卡组",单位都是合法选择),
        所以统一按单位挑是**保守且永不选错**的做法。代价:手牌里一张单位都没有
        (或者身份没认出来)时,这 7 张也不打 —— 这是**有意**的 fail-closed。
    ★ 落点 y = 手牌悬停行(引擎传 `scanner.y`;见 `HAND_ROW_Y` 的说明)。
      这一档的 y **必须落在手牌区**(`board.HAND_MIN_Y` 以下)—— 和别的档正好相反。
    """
    if rows:
        return _fail(f"行码 {rows} 是**战场上哪一行**的约束,而 kind 5 的目标在"
                     f"**手牌**里 -> 对不上(fail-closed)")
    cands = _hand_cards_clean(hand_cards, hand_xs)
    if not cands:
        return _fail("拿不到可用的手牌候选(hand_cards / hand_xs 空,或全是越界值)"
                     " —— 调用方要传「能当目标的那几张手牌」并排除掉正在拖出去的那张")
    units = [c for c in cands if c["type"] in UNIT_TYPES]
    if not units:
        seen = ", ".join(f"x={c['x']}({c['type'] or '类型未知'})" for c in cands[:6])
        return _fail(f"手牌里**没有认得出是单位**的那张(候选 {len(cands)} 张:{seen}"
                     f")—— 这一档有几张要求「选一张单位」,选错会被游戏忽略而引擎"
                     f"照样记成功 -> fail-closed 不打(不退回'挑最左')")
    y = HAND_ROW_Y if hand_y is None else int(hand_y)
    if not (board.HAND_MIN_Y <= y < CLIENT_H):
        return _fail(f"手牌行 y={y} 不在手牌区(要求 {board.HAND_MIN_Y} <= y < "
                     f"{CLIENT_H})—— 这个 y 是扫描器的悬停行,传错就会点到战场上")
    best = units[0]                       # 单位候选里最靠左那张(_hand_cards_clean 已按 x 排序)
    x = best["x"]
    nth = (f"第 {best['i'] + 1} 张" if isinstance(best.get("i"), int)
           else "手牌里最靠左的那个单位")
    # ★ 把候选逐张写出来(x:类型)—— 候选本身也要能核对,不能只有结论
    seen_txt = ", ".join(f"x={c['x']}:{c['type'] or '类型未知'}" for c in cands[:6])
    why = (f"kind=5({KIND_TEXT['5']}) rows=不限 候选{len(cands)}张"
           f"[{seen_txt}{'…' if len(cands) > 6 else ''}]"
           f" -> 只挑**认得出是单位**的(type ∈ {'/'.join(UNIT_TYPES)}),"
           f"其中取**最靠左**那张:{nth} x={x} 类型={best['type']}"
           f"(有几张要求'选一张单位',选非单位会被游戏忽略;用户没给偏好规则,"
           f"所以只做确定不会选错的那一步);落点 y={y}=手牌悬停行")
    if debug:
        print(f"    [order_target] {why}")
    return {"x": x, "y": y, "why": why, "kind": "5", "what": f"手牌(第{len(units)}选1)",
            "rows": "", "row": "", "src": "手牌", "side": "our", "is_hq": False,
            "n": len(units), "hand_x": x, "hand_type": best["type"],
            "hand_index": best.get("i")}
