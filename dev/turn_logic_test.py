"""turn_logic_test.py - drive TurnEngine with fake frames (no game window).

Regression test for the turn state machine: run this after ANY change to
turn_engine.py, before spending a live game session on turn_test.py.

It monkeypatches everything that touches the real world:
  - capture_client_bgr   -> synthetic frames
  - match_one            -> scripted end-turn button visibility
  - drag_deploy / click  -> recorded instead of moving the mouse
  - scanner.scan         -> scripted hand snapshots
  - _panel_at            -> no real screen reads
  - _panel_looks_same    -> scripted "was the deploy refused?"
  - _current_kredits     -> scripted Kredits readout (None = unreadable)

Usage:
  .venv\\Scripts\\python.exe dev\\turn_logic_test.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np

import turn_engine

FRAME = np.zeros((720, 1280, 3), dtype=np.uint8)
FRAME[440:476, 1120:1250] = 255

state = {"end_turn": True, "deploy_ok": True, "kredits": None,
         "our_units": [(500, 500)], "enemy_hq": (640, 180),
         # 战场卡数(四条线):部署成功/被拒绝由它决定
         "our_support": 0, "our_front": 0,
         "enemy_front": 0, "enemy_support": 0,
         "deploy_adds_card": True,
         # board_unreadable=True 时模拟"战场读不到" -> 引擎要退回面板判据
         "board_unreadable": False}
drags: list = []
clicks: list = []
attack_drags: list = []
move_drags: list = []       # "上前线"的拖拽(和攻击分开记,否则分不清这一拖是干嘛的)

turn_engine.capture_client_bgr = lambda hwnd: FRAME
turn_engine.match_one = lambda hay, needle: (
    (0.95, (1120, 453, 130, 36)) if state["end_turn"] else (0.10, None)
)
turn_engine.client_to_screen = lambda hwnd, cx, cy: (cx + 100, cy + 100)


def fake_drag_deploy(hwnd, card_x, card_y=700, drop=None, jitter=6,
                     hover_wait=None, on_pressed=None):
    drags.append(card_x)
    # ★★ 2026-09-13(第十个会话):记下"按下之前等了多久"。
    #   判据:从手牌拖牌时**必须**等扇形展开(扫描器的 HOLD),否则
    #   "读身份用展开态、按下用中立态",同一个 x 底下可能已经换成邻居那张牌。
    state.setdefault("hover_waits", []).append(hover_wait)
    if on_pressed is not None:
        # 实机这里会存一帧(地面真值:光标上挂的是哪张牌);离线替身只数调用。
        try:
            on_pressed()
        except Exception as e:                       # 诊断不许弄崩拖拽
            state["pressed_dump_error"] = f"{type(e).__name__}: {e}"
    # 记录落点最靠上的那一次:部署必须拖到中线以下(y > ~360),否则会变成
    # 把牌拖到敌方那半边,是 M4 最容易搞错的地方之一。
    if drop:
        state["min_drop_y"] = min(state.get("min_drop_y", 9999), drop[1])
        # 记下落点,用来验证"换了另一个空槽位"而不是原地重拖一次
        state.setdefault("drop_points", []).append((drop[0], drop[1]))
    # ★ 部署"成功"意味着场上真的多了一张卡 —— 由 deploy_adds_card 控制,
    #   从而模拟"被拒绝"(阵线满/费用不够)的情况。
    if state["deploy_adds_card"]:
        state["our_support"] += 1
        # ★★ 场上读数会**跟着变**:部署成功后,我方支援线的单位数 +1。
        #   (只加 `our_support` 而不加 `support_units` 会让替身自相矛盾:
        #    引擎信任的那个数永远停在原地,于是它每回合都以为还有空位。)
        if state.get("support_units") is not None:
            state["support_units"] += 1
        # ★★ 同时**费用也要真的少掉这张卡的费**(2026-09-11 下午加):
        #   引擎现在用"费用读数 vs 账本"判部署成没成(见 _judge_deploy),
        #   而实机上牌出去了,左下角的剩余费用**就是会往下走**。
        #   替身如果一直返回常数,就会让每一次成功部署都长成"牌回手"的样子 ——
        #   那不是引擎错,是替身不真实。
        cost = state.get("hand_costs", {}).get(card_x)
        if cost and state.get("kredits_left") is not None:
            state["kredits_left"] = max(0, state["kredits_left"] - cost)
    # queued_delta:拖牌之后"下一次读战场"要额外叠加的抖动(由用例设定)
    if state.get("queued_delta"):
        state["pending_delta"] = state["queued_delta"]
        state["queued_delta"] = 0
    return True


turn_engine.drag_deploy = fake_drag_deploy
turn_engine.click = lambda x, y, jitter=5: clicks.append((x, y))

# ---- 战场读数替身 ----
# 用假的四条线卡数;真实的 board 依赖真实画面,离线测不了。
def fake_snapshot(frame, debug=False):
    if state.get("board_unreadable"):
        return None
    # pending_delta:模拟"读数抖动" —— 在拖牌之后的**那一次**读战场时,
    # 总数凭空变化(实测抖出过 4->2)。
    d = state.get("pending_delta") or 0
    state["pending_delta"] = 0
    snap = {
        "our_support": (state["our_support"] + max(0, d), {}),
        "our_front": (state["our_front"], {}),
        "enemy_front": (state["enemy_front"] + max(0, -d), {}),
        "enemy_support": (state["enemy_support"], {}),
        "total": (state["our_support"] + state["our_front"]
                  + state["enemy_front"] + state["enemy_support"] + d),
    }
    # ★★ `our_support_units` = 我方支援线上的**单位**数(**不含总部**,
    #    真实实现是数费用徽章,见 `board.support_line_units`)。
    #    默认**不给这个键** -> 引擎退回"只信本回合部署数"(= 旧行为, CASE 17 测这条);
    #    用例想测"场上读数可信"时显式设 `state["support_units"]`。
    su = state.get("support_units")
    if su is not None:
        snap["our_support_units"] = (su, {"why": "用例指定"})
    return snap


turn_engine.board.battlefield_snapshot = fake_snapshot

# ---- M4 攻击阶段的替身 ----
# 攻击现在用 `board.read_field`(自适应行带 + 相对定阵营)+ `board.find_enemy_hq`
# + `board.read_hq_hp`(语义判据:敌方总部血量有没有下降)。真机之外没法提供,
# 所以脚本化一个假战场。这样攻击阶段的**状态机**也能被离线验证。
import attack as attack_mod  # noqa: E402
import deploy as deploy  # noqa: E402
import frontline_line  # noqa: E402
import hand_scanner_v2  # noqa: E402


# ★★ 2026-09-12:"前线那一行是谁的"是攻击规则的一部分(步兵/坦克只打得到敌方前线)。
#   真判据要抓真实帧(黑线位置),离线测不了 -> 用 state["frontline_owner"] 脚本化。
#   None = 读不出来 -> 引擎必须 fail-closed。
# ★★★ 2026-09-21:签名补上 `field=None`(**只加参数,判据与用例逻辑一字未动**)。
#   为什么必须补:`order_target.pick()` 是按**真函数的签名**调的 ——
#   `frontline_line.read_frontline_owner(frame=frame, field=field)`(见
#   `order_target.py` 第 ④ 段)。这个替身少一个形参,于是**只要有一个用例喂进
#   target 卡、走到"要读前线归属"那一步**,这里就会
#   `TypeError: fake_frontline_owner() got an unexpected keyword argument 'field'`
#   —— 报出来的是替身的签名问题,和被测逻辑一点关系都没有,最费时间的错法。
def fake_frontline_owner(frame=None, hwnd=None, debug=False, field=None):
    # ★ 2026-09-13:`state["frontline_owner_seq"]` 给出**逐次不同**的读数
    #   (测"展示卡盖住前线 -> 读成 empty -> 重读 -> enemy"那条路)。
    seq = state.get("frontline_owner_seq")
    if seq:
        o = seq.pop(0) if len(seq) > 1 else seq[0]
    else:
        o = state.get("frontline_owner")
    return {"owner": o, "band_y": None, "front_y": None, "delta": None,
            "score": 1.0, "why": f"用例指定:{o}"}


frontline_line.read_frontline_owner = fake_frontline_owner


def fake_read_field(frame, templates=None, debug=False):
    # 单位类型由 state["unit_types"] 指定(攻击规则要看类型:
    # 只有 fighter/bomber/artillery 能从支援阵线直接攻击)。
    types = state.get("unit_types") or ["artillery"] * len(state["our_units"])
    ours = []
    for (x, y), t in zip(state["our_units"], types):
        ours.append({"cx": x, "cy": y, "x": x - 60, "y": y - 80, "w": 120,
                     "h": 160, "side": "our", "type": t, "is_hq": False,
                     "hp": None, "row_idx": 1})
    if state.get("our_hq"):          # 我方总部卡也在支援线上(而且不能出战)
        hx, hy = state["our_hq"]
        ours.append({"cx": hx, "cy": hy, "x": hx - 60, "y": hy - 80, "w": 120,
                     "h": 160, "side": "our", "type": None, "is_hq": True,
                     "hp": 20, "row_idx": 1})
    # ★ 前线那一行的卡:归属判到 "enemy" 时它们才是可打的敌方单位。
    #   ★ 2026-09-13:`front_units_seq` 给出**逐次不同**的前线内容 ——
    #     用来重现"对手的展示卡盖住前线那一行"(第一次读**看不到**那一行
    #     -> 行结构只有 2 行 -> 判成 empty;重读时才看得到)。
    _fseq = state.get("front_units_seq")
    _fu = (_fseq.pop(0) if len(_fseq) > 1 else _fseq[0]) if _fseq \
        else (state.get("front_units") or [])
    front = []
    for (x, y) in _fu:
        front.append({"cx": x, "cy": y, "x": x - 60, "y": y - 80, "w": 120,
                      "h": 160, "side": "frontline", "type": None,
                      "is_hq": False, "hp": None, "row_idx": 1})
    # ★★ 行结构:攻击和"上前线"都依赖它。
    #   · 攻击:步兵/坦克只打得到"敌方前线那一行",靠 `rows` 里的 side 分辨;
    #   · 上前线:要知道**前线那一行的 y** —— 前线空着时它根本不在 `rows` 里,
    #     那时用"最上/最下两行的中点"(实测 180/520 -> 350,和真实帧一致)。
    #   行中心取实测值:敌方支援 180 / 前线 350 / 我方支援 520。
    rows = []
    # ★★ 2026-09-12(第六个会话):敌方**支援线**上的单位也要能被脚本化 ——
    #   补上的那一档目标(`TARGET_ENEMY_SUPPORT`)就是打它们,用例 CASE 19m 要用。
    enemy_sup = []
    _sup_types = state.get("enemy_support_types") or []
    for _i, (x, y) in enumerate(state.get("enemy_support_units") or []):
        enemy_sup.append({"cx": x, "cy": y, "x": x - 60, "y": y - 80, "w": 120,
                          "h": 160, "side": "enemy", "type": None,
                          "is_hq": False, "hp": None, "row_idx": 0})
        if _i < len(_sup_types):
            enemy_sup[-1]["type"] = _sup_types[_i]     # ★ CASE 35:战斗机拦截用
    # ★ CASE 47:出手之后总部卡**没了**(那一发把它打掉了)-> 盘面上也不该再有它
    _hq_visible = not (state.get("attack_settled")
                       and state.get("hq_after_attack") in ("gone", "stale_gone"))
    if state.get("enemy_hq") and _hq_visible:
        ex, ey = state["enemy_hq"]
        rows.append({"cy": float(ey), "y0": ey - 80, "y1": ey + 80,
                     "side": "enemy", "n": 1,
                     "boxes": [{"cx": ex, "cy": ey, "x": ex - 60, "y": ey - 80,
                                "w": 120, "h": 160}] + enemy_sup})
    elif enemy_sup:
        rows.append({"cy": 180.0, "y0": 100, "y1": 260, "side": "enemy",
                     "n": len(enemy_sup), "boxes": enemy_sup})
    if front:
        rows.append({"cy": 350.0, "y0": 270, "y1": 430, "side": "frontline",
                     "boxes": front, "n": len(front)})
    if ours:
        rows.append({"cy": 520.0, "y0": 440, "y1": 600, "side": "our",
                     "boxes": ours, "n": len(ours)})
    # ★ CASE 47:整帧读不到行结构(画面被盖住)-> 不许据此下结论
    if state.get("attack_settled") and state.get("hq_after_attack") == "no_rows":
        rows = []
    return {
        "rows": rows, "our_support": ours, "enemy_support": enemy_sup,
        "frontline": front, "our_units": ours, "enemy_units": enemy_sup,
        "hq_enemy": None, "hq_our": None,
    }


def fake_find_enemy_hq(frame, field=None, templates=None):
    if not state["enemy_hq"]:
        return None
    # ★ CASE 47:出手之后总部卡**没了**(那一发把它打掉了)。
    #   "gone" = 血量也读不到; "stale_gone" = 血量读数**停在旧值**(实机 J2 的制胜一击)
    if state.get("attack_settled") and state.get("hq_after_attack") in (
            "gone", "stale_gone"):
        return None
    ex, ey = state["enemy_hq"]
    # ★ CASE 49:"**出手之后重新定位**总部会读到什么"(默认还是 hq_hp)。
    #   ★ 只在 `attack_settled` 之后生效 —— 出手**前**那个血量必须还是 hq_hp,
    #     否则连"出手前是多少"都被替身改掉了,用例就没在考真实那条路。
    hp = state.get("hq_hp")
    if state.get("attack_settled") and state.get("hq_relocate_hp") is not None:
        hp = state["hq_relocate_hp"]
    return {"cx": ex, "cy": ey, "x": ex - 60, "y": ey - 80, "w": 120,
            "h": 160, "side": "enemy", "type": None, "is_hq": True,
            "hp": hp, "row_idx": 0}


def fake_read_hq_hp(frame, hq_unit, min_h=24.0):
    """
    脚本化"重读敌方总部血量"。

    state["hq_drop_on_attack"] 为真 = 这次攻击让血量下降(打中);
    为假 = 血量不变(没打中)。

    ★★ 2026-09-12 修:**掉血必须"一次攻击只掉一次"**,不能"每读一次掉一次"。
      起因:攻击落地后现在要**读两次**(立刻一次 + 等 1.5 秒一次,见 `attack.run_turn`
      对伤害飘字的处理),而旧替身是"每调用一次就扣一次" -> 20 被扣成 16,
      用例报 `这次攻击该打中 1 次: 16`。**是替身不真实,不是功能坏了。**
      现在:掉血挂一个 `hq_drop_pending` 标记,由"攻击拖拽"(`fake_move_drag`)置位,
      读过一次就清掉 -> 同一发攻击读多少次都读到同一个值。
    """
    hp = state.get("hq_hp")
    if hp is None:
        return None
    # ★★★ CASE 47(2026-09-13 深夜):出手之后**血量读不到**的三种样子。
    #   `hq_after_attack`:
    #     "gone"       总部卡从画面上消失(打掉了)-> 血量读不到、找总部也找不到;
    #     "stale_gone" 同上,但**血量读数停在旧值**(实机 J2 的制胜一击就长这样);
    #     "unreadable" 卡还在,只是被动画/遮挡盖住 -> 血量读不到、**找总部找得到**;
    #     "no_rows"    整帧读不到行结构(画面被盖住)-> 不许据此下任何结论。
    #   ★ 只在"这一发攻击已经落地"之后生效(`attack_settled`),不影响别的用例。
    if state.get("attack_settled") and state.get("hq_after_attack") in (
            "gone", "no_rows", "unreadable"):
        return None
    # ★★★ CASE 49(2026-09-15):出手之后按脚本**依次**给读数 ——
    #   用来复现实机那三次"晚读读到不可能的值"(`17->20` / `11->20` / `10->87`)。
    #   list 里第一个给"立刻"那次,第二个给"等 1.5s"那次;给完就回落到 hq_hp。
    seq = state.get("hp_read_seq")
    if seq and state.get("attack_settled"):
        return seq.pop(0)
    if state.get("hq_drop_on_attack") and state.get("hq_drop_pending"):
        state["hq_drop_pending"] = False
        state["hq_hp"] = hp - state.get("hq_drop", 1)
        return state["hq_hp"]
    return hp


def fake_move_drag(sx, sy, ex, ey, **kw):
    attack_drags.append((sx, sy, ex, ey))
    # ★ 一次攻击拖拽 = 一次伤害结算的机会(见 fake_read_hq_hp 的说明)
    state["hq_drop_pending"] = True
    # ★ CASE 47:从这一刻起,"出手之后"的脚本化读数才生效
    state["attack_settled"] = True
    return True


# ★★ "上前线"用的**另一条接缝**(2026-09-12)。
#   为什么不复用 `fake_move_drag`:攻击和移动都会走鼠标拖拽,混在一个 list 里就
#   分不清"这一拖是去打人还是去占位" —— CASE 19c 那种"步兵不许打那一行"的断言
#   会被一次合法的移动拖拽污染,于是用例要么变松、要么改得看不懂。
#   所以:`attack_mod.move_unit_to_front` 单独记 `move_drags`。
def fake_move_unit_to_front(hwnd, src, dst=None, log=print):
    move_drags.append({"src": tuple(src), "dst": tuple(dst) if dst else None})
    mode = state.get("move_front_effect", "ok")
    if mode == "ok":
        # 模拟游戏真的把单位挪走了:我方支援线 −1 **且** 前线 +1
        units = state["our_units"]
        if units:
            i = min(range(len(units)), key=lambda k: abs(units[k][0] - src[0]))
            state["our_units"] = units[:i] + units[i + 1:]
            state.setdefault("front_units", []).append(tuple(units[i]))
    elif mode == "vanished":
        # ★ 历史坑(§12 清单第 3 条):单位**离开支援线却没出现在前线**。
        #   旧脚本只看"我方那一行少了"就判成功 —— 这一档专门钉死"不许这么判"。
        units = state["our_units"]
        if units:
            i = min(range(len(units)), key=lambda k: abs(units[k][0] - src[0]))
            state["our_units"] = units[:i] + units[i + 1:]
    return True, {"src": src, "dst": dst}


# ★ 攻击的第一层判据是"橙色费用徽章"(unit_state.actionable_units):
#   橙 = 这回合还能行动。测试里脚本化它 —— 默认把 state["our_units"] 里
#   前 state["actionable_n"] 个当成"橙色"(可行动)。
def fake_actionable_units(frame, templates=None, debug=False):
    types = state.get("unit_types") or ["artillery"] * len(state["our_units"])
    n = state.get("actionable_n")
    if n is None:
        n = len(state["our_units"])
    out = []
    for (x, y), t in list(zip(state["our_units"], types))[:n]:
        out.append({"badge": {"x": x - 60, "y": y - 70, "state": "orange"},
                    "box": {"x": x - 60, "y": y - 70, "w": 120, "h": 160,
                            "cx": x, "cy": y},
                    "src": (x, y), "type": t})
    # ★ 2026-09-12:还要能模拟"我们**自己挪上前线**的单位" —— 它的橙色徽章
    #   落在**前线那一行**(cy≈350),用来钉 CASE 19k(旧代码把它当敌方排除)。
    for (x, y) in (state.get("front_our_units") or []):
        out.append({"badge": {"x": x - 60, "y": y - 70, "state": "orange"},
                    "box": {"x": x - 60, "y": y - 70, "w": 120, "h": 160,
                            "cx": x, "cy": y},
                    "src": (x, y), "type": (state.get("unit_types") or [None])[0]})
    return out


attack_mod.board.read_field = fake_read_field
attack_mod.board.find_enemy_hq = fake_find_enemy_hq
attack_mod.board.read_hq_hp = fake_read_hq_hp
attack_mod.unit_state.actionable_units = fake_actionable_units


# ★★★ CASE 48(2026-09-13 深夜):**打单位的硬判据 —— "我方单位徽章由橙变灰"**。
#   单位卡上没有能读的血量数字,所以"打中了没有"以前只有"那一行还剩几张卡";
#   打伤但没打死就是"结论不可信"(实机 J2 报了 9 次)。
#   现在加一条结构判据(§7 第 74 条:橙 = 本回合还没行动过):
#   拖之后**同一个位置的徽章**变灰 = 游戏接受了这次行动。
#   ★ 替身必须能脚本化"出手之后那个徽章是什么颜色"(`state["badge_state_after"]`)。
def fake_find_cost_badges(frame, rows=None, debug=False):
    st = state.get("badge_state_after") or "orange"
    if st == "none":                      # "一个徽章都没检出来" = 判据塌了
        return []
    u = (state.get("our_units") or [(500, 500)])[0]
    x, y = u
    return [{"x": x - 60, "y": y - 70, "w": 18, "h": 18, "state": st,
             "digit_n": 40, "digit_s": 170.0 if st == "orange" else 30.0,
             # ★ 诊断(`_dump_badges`)会读这几个字段;替身缺字段会让那行诊断报错
             #   (不影响攻击,但日志会多一行噪音 —— 实测踩过)。
             "digit_v": 210.0 if st == "orange" else 180.0}]


attack_mod.unit_state.find_cost_badges = fake_find_cost_badges
attack_mod.move_drag = fake_move_drag
# ★ 读战场前的"停车"在离线用例里必须替身掉(否则会真去动鼠标)
attack_mod.park_cursor = lambda hwnd, settle=0.3: True
attack_mod.move_unit_to_front = fake_move_unit_to_front


# ★★★ 2026-09-12(第七个会话)"守护"判据的替身(用户给的正样本 -> `src/guard.py`)。
#   真判据是**图像**的(卡右边缘那块盾牌字形 + 模板匹配),离线用例没法画出来,
#   所以这里只替身"读出来的结论",用于验证**决策那一层**:
#     hq_guarded = 总部被守护 -> 非炮兵不该试总部,该去打敌方支援线上的守护单位。
def fake_read_guard(frame, field, hq=None, debug=False):
    units = [u for u in (field.get("enemy_support") or []) if not u.get("is_hq")]
    n = state.get("guard_units_n")
    if n is None:
        n = len(units) if state.get("hq_guarded") else 0
    marked = units[:n]
    for u in marked:
        u["guard"] = True
    return {"hq_guarded": bool(state.get("hq_guarded")),
            "guard_units": marked, "detail": {}}


import guard as _guard_mod  # noqa: E402
_guard_mod.read_guard = fake_read_guard
# ★ 离线用例会跑很多次攻击阶段 —— 把"存整帧"关掉,否则一次测试就写出几十张图
#   (实测一跑 24MB)。徽章全表那一行日志仍然会打(它不写磁盘)。
attack_mod.DUMP_ATTACK_FRAMES = False
# ★ attack 模块自己 import 了 capture_client_bgr / client_to_screen,所以必须
#   在【那个模块的命名空间】里也替身 —— 只改 turn_engine 的那份没用:
#   - capture_client_bgr(0) 返回 None -> 攻击循环直接 break(表现成"攻击 0 次")
#   - client_to_screen(0,...) 抛 pywintypes.error 1400 -> 被 think() 的保护性
#     except 吞掉(同样表现成"攻击 0 次")
#   这两个坑都踩过,而且失败信息完全指不出原因。
attack_mod.capture_client_bgr = lambda hwnd: FRAME
attack_mod.client_to_screen = lambda hwnd, cx, cy: (cx + 100, cy + 100)
# 攻击"是否被接受"由画面差异判断 -> 用 state 控制
attack_mod._changed = lambda a, b, scale=0.02: (
    5000.0 if state["attack_ok"] else 0.0)
state["attack_ok"] = True

# Patch read_kredits (the HUD reader), NOT _current_kredits: the engine method
# is what feeds the value into Affordability, and overriding it would skip that.
# Patch read_kredits (the HUD reader), NOT _current_kredits: the engine method
# ★ 返回 `kredits_left`(画面上的**当前**剩余费用),而不是回合初的那个常数 ——
#   引擎现在拿它和账本对账来判"部署成没成",替身必须跟着往下走(见 fake_drag_deploy)。
turn_engine.read_kredits = lambda frame, **kw: state.get("kredits_left", state["kredits"])
# ★ 2026-09-12(第七个会话第三局):部署那一路读战场前也会 `park_cursor`
#   (把光标停到 SAFE_POINT,免得悬停面板盖住我方那一行)—— 离线用例里必须替身掉,
#   否则会**真去动鼠标**(和 attack 那边同一条规矩)。
turn_engine.park_cursor = lambda hwnd, settle=0.3: True
# ★★ 2026-09-13(第十个会话):`_panel_at` 原来恒返回 None,而引擎那条退路的判据是
#   `ok = not _panel_looks_same(base, after)` —— `_panel_looks_same(None, 非None)`
#   返回 False -> `ok=True`:**在惰性模式下这条退路是一枚橡皮图章**
#   (实机第 6/7 回合两次"部署成功"就是这么来的)。
#   现在引擎要求"基准面板和拖后面板**都在**",所以替身必须能给出真实形状:
#   `state["panel_none"]=True` 用来演"扫描那一帧没拍到面板"那种情况。
turn_engine.TurnEngine._panel_at = lambda self, x: (
    None if state.get("panel_none") else "PANEL_AFTER")
# "same panel" means KARDS refused the deploy (could not afford it)
turn_engine.TurnEngine._panel_looks_same = staticmethod(
    lambda before, after: not state["deploy_ok"]
)
# ★★ 2026-09-13(第十个会话):"按下瞬间存帧"是实机取证手段(会写 png),
#   离线必须替身掉 —— 但**要留下调用痕迹**,否则"这一帧到底拍没拍"无法断言。
turn_engine.TurnEngine._dump_drag_frame = (
    lambda self, name, target:
    state.__setitem__("pressed_dumps", state.get("pressed_dumps", 0) + 1)
)
# ★ 攻击阶段的"画面变化"判据在 attack 模块里。测试里把它脚本化(见上),
#   否则攻击会把结束回合按钮的遮挡也算成"变化"。


class FakeScanner:
    """
    脚本化的扫描器替身。

    注意:惰性扫描(`lazy_scan=True`)需要真实的左边缘测量 + 布局表,
    离线没法真跑,所以回合状态机的用例统一 `lazy_scan=False`
    (走"回合开始全量扫一次"的老路径);惰性扫描的路径另有 CASE 28 覆盖。
    """

    def __init__(self, cards):
        self.cards = list(cards)
        self.calls = 0
        self.scan_calls = 0          # 全量盲扫次数(惰性模式下应为 0)
        self.find_calls = 0          # 惰性扫描次数
        # ★ 2026-09-13:引擎会读它决定"手牌多不多"(用户要求:手牌多时最多部署 2 个)。
        #   默认 None = **不知道** -> 那个上限不生效,老用例的行为不受影响;
        #   要测那条规则的用例自己传 `hand_count=`。
        self.last_hand_count = None
        # ★★ 2026-09-13(第十个会话):`turn_engine` 现在会把**扫描器的悬停等待**
        #   传给 `drag_deploy`(判据:读身份用哪个扇形状态,按下就用哪个状态)。
        #   替身必须跟着有 —— 否则引擎一访问就 AttributeError。
        self.hold = hand_scanner_v2.HOLD
        self.last_layout = None
        self.last_probe_seen = []
        # ★ 2026-09-13(第十个会话):引擎会把**手牌记忆**注入扫描器(`scanner.memory`),
        #   并在每次扫描后读 `last_probe_seen` 回写记忆。替身给个空记录即可。
        self.memory = None
        self.last_memory = None

    def scan(self, max_cards=10, debug=False):
        self.calls += 1
        self.scan_calls += 1
        return list(self.cards)

    # --- 惰性扫描接口(只有 CASE 28 用) ---
    def measure_left_edge(self):
        return state.get("left_edge", 459)

    def measure_edges(self):
        """★ 2026-09-13:引擎现在一次测**两个**边缘(见 LAYOUT_MATCH_BOTH_EDGES)。"""
        return (state.get("left_edge", 459), state.get("right_edge"))

    def find_playable(self, budgets, edge=None, right=None, exclude=None,
                      max_cards=10, debug=False, allow_draw=False):
        self.calls += 1
        self.find_calls += 1
        # ★ 2026-09-13:引擎只会在这个回合的**第 1 次**扫描时允许"右端补未知"
        #   (回合开始的抽牌)。用例要能断言这一点。
        state.setdefault("allow_draw_seen", []).append(bool(allow_draw))
        limit = state.get("lazy_scan_limit", len(self.cards))
        exclude = exclude or set()
        for c in self.cards[:limit]:
            if c["x"] in exclude:      # 本回合已经试过这张 -> 跳过
                continue
            cost = c.get("cost")
            ctype = c.get("type")
            if (ctype in ("infantry", "tank", "fighter", "bomber",
                          "artillery")
                    and cost is not None and cost <= budgets[0]):
                # ★★ 真实扫描器会把"这张牌的悬停面板"一起带回来当部署判据的基准
                #   (见 `_probe_layout_until` / `_lazy_find_playable`)。
                #   替身必须也给一个,否则惰性模式下 `_before` 恒为 None,
                #   引擎那条退路就永远"判不出来"(用例反而测不到真实路径)。
                c = dict(c)
                c["panel"] = "PANEL_BEFORE"
                return [c], cost
        return [], None


def hand(*specs):
    """specs: (name, type, cost, x)"""
    cards = [{"name": n, "type": t, "cost": c, "x": x} for n, t, c, x in specs]
    # 给替身用:某张手牌 x 拖出去被接受时,剩余费用要少掉它的费
    state["hand_costs"] = {c["x"]: c["cost"] for c in cards}
    return cards


# ★ 2026-09-12:把引擎的日志也**收进一个 list** —— 有些判据只能从日志文本上断言
#   (例:"有攻击者但挑不到目标"必须写出原因,CASE 19n)。以前日志只往 stdout 打,
#   于是"日志在撒谎/不说话"这类问题在离线用例里根本测不到。
engine_logs = []


def _eng_log(m):
    engine_logs.append(m)
    print("      " + m)


def new_engine(cards, kredits=None, deploy_refused=False, lazy=False):
    """
    deploy_refused=True 表示"拖出去会被拒绝"(阵线满 / 费用不够 / 规则不允许),
    表现为【场上卡数不变】—— 这正是实机上"乱拖好多次但没出牌"的情况。
    lazy=True 走惰性扫描路径(默认 False:状态机用例走全量扫描那条,更可控)。
    """
    state["kredits"] = kredits
    # ★ 替身里"画面上的剩余费用"从本回合初始费用开始,成功部署时跟着往下走
    state["kredits_left"] = kredits
    # ★ 手牌 x -> 费用 的对照表:**由传进来的 cards 推导**,不能只靠 hand() 设 ——
    #   有用例是手工构造卡列表的,只认 hand() 的话会拿到上一条用例的旧表,
    #   于是替身"漏扣费用",看起来就像"这次部署被拒绝了"(实测就把同一张牌拖了两次)。
    state["hand_costs"] = {c.get("x"): c.get("cost") for c in cards}
    state["deploy_adds_card"] = not deploy_refused
    state["board_unreadable"] = False
    state["end_turn"] = True
    state["our_units"] = [(500, 500)]
    state["unit_types"] = None
    state["enemy_hq"] = (640, 180)
    state["our_hq"] = None
    # ★ 攻击的判据现在是**语义信号**:敌方总部血量有没有下降。
    #   hq_hp = 当前血量;hq_drop_on_attack = 这次攻击会不会让它下降。
    state["hq_hp"] = 20
    state["hq_drop_on_attack"] = True
    state["attack_ok"] = True
    # ★ 攻击的第一层判据是"橙色费用徽章"(还能行动)。
    #   actionable_n = 前几个我方单位是橙色的;None = 全部橙色。
    state["actionable_n"] = None
    state["min_drop_y"] = 9999
    state["max_cost_seen"] = None
    state["our_support"] = 0
    state["our_front"] = 0
    state["enemy_front"] = 0
    state["enemy_support"] = 0
    # ★ None = 替身不提供"我方支援线单位数" -> 引擎退回"只信本回合部署数"
    state["support_units"] = None
    # ★ None = 替身不提供"前线归属" -> 步兵/坦克必须 fail-closed(CASE 19)
    state["frontline_owner"] = None
    state["frontline_owner_seq"] = None
    state["front_units_seq"] = None
    # ★ 前线那一行上的卡(归属判到 enemy 时它们才是可打的敌方单位)
    state["front_units"] = []
    # ★ "我们**自己挪上前线**的单位"(橙色徽章落在前线那一行)—— 见 fake_actionable_units
    state["front_our_units"] = []
    # ★ "上前线"的模拟结果(见 fake_move_unit_to_front):
    #   ok = 支援线 −1 且 前线 +1(真的挪走);vanished = 只离开了支援线
    state["move_front_effect"] = "ok"
    state["lazy_scan_limit"] = 10 ** 6
    # ★ 2026-09-12:敌方**支援线**上的卡(补上的那一档目标用)—— 每个用例都要复位,
    #   否则上一条用例放上去的卡会漏到下一条里(CASE 19m 就是靠它建的场景)。
    state["enemy_support_units"] = []
    # ★ 2026-09-12(第七个会话):守护判据(fake_read_guard)的两个旋钮
    state["hq_guarded"] = False
    state["guard_units_n"] = None
    # ★ 2026-09-12(第七个会话):敌方支援线每张卡的类型(战斗机拦截用,CASE 35)
    state["enemy_support_types"] = []
    # ★ CASE 47:"出手之后"的脚本化读数(默认关,见 fake_read_hq_hp 的说明)
    state["attack_settled"] = False
    state["hq_after_attack"] = None
    # ★ CASE 49:"出手之后"按脚本依次给的读数 + "重新定位总部"读到的值
    state["hp_read_seq"] = None
    state["hq_relocate_hp"] = None
    drags.clear()
    clicks.clear()
    attack_drags.clear()
    move_drags.clear()
    engine_logs.clear()
    eng = turn_engine.TurnEngine(0, {"end_turn_btn": FRAME},
                                 log=_eng_log,
                                 lazy_scan=lazy)
    # ★★ 2026-09-13(第十个会话):引擎里的 `KreditsTracker` 会在回合开始时
    #   真去"等费用数字停止滚动"(真 `time.sleep`)—— 离线用例必须关掉它,
    #   否则**每条用例的每个回合都要真等 2~3 秒**(实测把整套用例拖到超时)。
    #   那条判据由 CASE 44 用虚拟时钟单独考。
    eng.kredits.turn_start_settle = 0
    eng.scanner = FakeScanner(cards)
    return eng


def run_turn(eng, max_steps=12):
    """
    一直 think() 到这个回合真正结束(点了结束回合并把 phase 复位)。

    ★ 不要在每个用例里写死 think() 的次数:状态机每加一个阶段
    (M4 就加了 attack 阶段),写死的次数会立刻失效,而失败信息
    ("clicks 少了一次")完全指不出原因 —— 这次就中了。
    """
    statuses = []
    for _ in range(max_steps):
        statuses.append(eng.think())
        # 每个 think() 之后都记一下"本回合学到的费用上限":结束回合时
        # reset_turn() 会把它清掉,循环跑完再读就一定是 None。
        if eng.afford.max_cost is not None:
            state["max_cost_seen"] = eng.afford.max_cost
        if statuses[-1] == "ended_turn":
            break
    return statuses


def show(status):
    print(f"    think() -> {status:<16} phase={eng.phase:<14} "
          f"attempts={len(eng.attempted_x)} deploys={eng.deployed_this_turn} "
          f"maxcost={eng.afford.max_cost}")


# ★ turn_engine 的 think() 内部异常会被保护性 except 吞掉(实机上是对的:
#   一次识别出错不该让整局崩)。但测试里必须让它冒出来,否则异常表现成
#   "攻击 0 次"这种完全看不出原因的结果 —— 这次就中了(ClientToScreen 抛 1400)。
_orig_attacker_run = attack_mod.Attacker.run_turn


def loud_run_turn(self, hard_stop=None):
    try:
        return _orig_attacker_run(self, hard_stop=hard_stop)
    except Exception as e:
        print(f"    !! Attack 抛异常: {type(e).__name__}: {e}")
        raise


attack_mod.Attacker.run_turn = loud_run_turn


print("=" * 78)
print("CASE 1: opponent -> our turn -> deploy every unit -> attack -> end turn")
print("=" * 78)
# ★ 这里显式给 kredits=5:以前靠 kredits=None(读不到)来"不设预算上限",
#   而那种语义本身就是 §7 第 51 条那个 bug(费用未知 -> 引擎以为钱一直够 ->
#   连着拖)。现在费用读不到会走**保守估计**(见 CASE 31),所以用例要显式给钱。
eng = new_engine(hand(("轻步兵", "infantry", 1, 500),
                      ("步兵第89团", "infantry", 1, 380)), kredits=5)
state["end_turn"] = False
show(eng.think())                      # opponent
state["end_turn"] = True
statuses = run_turn(eng)
# ★ 这里【不能】在循环之后读 eng.deployed_this_turn / attacker.landed:
#   think() 点完结束回合作者会 reset_turn(),这些计数一律归零。
#   要断言"这次拖拽发生了"就数 list 里的记录(它们是跨回合累积的)。
print(f"    drags={drags} clicks={clicks} attack_drags={attack_drags}")
assert drags == [500, 380], drags
assert len(clicks) == 1, clicks
assert len(attack_drags) == 1, attack_drags      # 一个我方单位 -> 一次攻击

print()
print("=" * 78)
print("CASE 2: THE KREDITS BUG - every deploy is refused (no Kredits)")
print("        this is what the user diagnosed in the first live run")
print("        ★ 现在从【最便宜】的开始试(1 费那张),而不是手牌最左那张")
print("=" * 78)
eng = new_engine(hand(("喀秋莎", "artillery", 2, 388),
                      ("喷烟者42型", "artillery", 3, 532),
                      ("45毫米反坦克炮", "artillery", 2, 592),
                      ("轻步兵", "infantry", 1, 700)),
                 deploy_refused=True)
statuses = run_turn(eng)
print(f"    drags={drags}")
# 1 费那张先试 -> 被拒绝 -> 学到上限 0 -> 后面都不再试
assert drags == [700], \
    f"学到上限后就该停手,不该把每张都试一遍,got {drags}"
assert state["max_cost_seen"] == 0, state["max_cost_seen"]

print()
print("=" * 78)
print("CASE 3: 5 费 + 牌面 5/3/1 -> 便宜的先出(1 然后 3),5 费那张留下")
print("        ★ 原来按手牌顺序会先把 5 费打出去,两张便宜的反而出不了")
print("=" * 78)
eng = new_engine(hand(("105毫米轻型榴弹炮", "artillery", 5, 640),
                      ("152毫米榴弹炮", "artillery", 3, 532),
                      ("轻步兵", "infantry", 1, 700)), kredits=5)
run_turn(eng)
print(f"    drags={drags} (预算 5)")
assert drags == [700, 532], \
    f"必须先出 1 费再出 3 费,5 费那张钱不够就不出: {drags}"

print()
print("=" * 78)
print("CASE 4: Kredits=2,牌面 3/2/1 -> 先出 1 费,然后只剩 1 费,2 费和 3 费都不出")
print("=" * 78)
eng = new_engine(hand(("152毫米榴弹炮", "artillery", 3, 532),
                      ("45毫米反坦克炮", "artillery", 2, 592),
                      ("轻步兵", "infantry", 1, 700)), kredits=2)
run_turn(eng)
print(f"    drags={drags}")
assert 532 not in drags, f"cost-3 card must not be tried with 2 Kredits: {drags}"
assert drags == [700], f"2 费先出 1 费那张,剩下的钱不够 2 费: {drags}"
assert state["min_drop_y"] > 360, \
    f"部署落点必须在中线以下,实测最靠上 {state['min_drop_y']}"

print()
print("=" * 78)
print("CASE 5: 指令卡按「打法表」决定能不能拖 —— 2026-09-20 起**不再是一律不拖**")
print("=" * 78)
# ★ 这条用例原来断言的是"orders must never be dragged"(旧行为)。
#   2026-09-20 用户把 674 张指令/反制的打法逐张给了出来(config/order_plays.json),
#   其中 `direct` 那一档(286 张)**拖到中线以下就打出**、和放单位同一个手势。
#   所以这里从**表里现取**卡名来考,而不是写死某一张卡(表更新了用例不会跟着烂)。
import orders as _ord  # noqa: E402
_direct = next(n for n, r in _ord._CARDS.items() if r["mode"] == _ord.MODE_DIRECT)
_black = next(n for n, r in _ord._CARDS.items() if r["mode"] == _ord.MODE_BLACKLIST)

# ① direct 的指令:允许拖出去,而且日志要写「指令打出」(不是"部署成功")
drags.clear(); engine_logs.clear()
eng = new_engine(hand((_direct, "order", 1, 780)), kredits=5)
run_turn(eng)
print(f"    direct 指令「{_direct}」drags={drags}")
assert drags == [780], f"direct 的指令应当被拖出去: {drags}"
assert any("指令打出" in m for m in engine_logs), \
    f"指令成功时日志要写「指令打出」: {engine_logs}"

# ② 反制 / 黑名单指令:一律不拖(fail-closed)
drags.clear(); engine_logs.clear()
eng = new_engine(hand(("伏击", "counter", 2, 700), (_black, "order", 1, 660)),
                 kredits=9)
run_turn(eng)
print(f"    反制+黑名单指令「{_black}」drags={drags}")
assert drags == [], f"反制与黑名单卡不许被拖: {drags}"
assert any("黑名单卡" in m for m in engine_logs), \
    f"手里有黑名单卡要说一句(用户要求): {engine_logs}"

# ③ ★★ 指令的成/败**不看战场卡数**(它不占槽位):费用对得上就是成功。
_flat_before = {"total": 10, "our_support": (2, {}), "rows": []}
_flat_after = {"total": 10, "our_support": (2, {}), "rows": []}
eng = new_engine(hand((_direct, "order", 1, 780)), kredits=5)
eng.kredits_left = 4                     # 账本:已经扣掉这张的 1 费
state["kredits_left"] = 4                # 画面读数也是 4 -> 对上
ok_o, note_o, ref_o = eng._judge_deploy(
    _flat_before, _flat_after, {"name": _direct, "type": "order"}, 1, is_order=True)
print(f"    指令:卡数没变 + 费用对上 -> ok={ok_o} note={note_o}")
assert ok_o is True and ref_o is False, \
    f"指令不占槽位,费用对上就必须判成功: {(ok_o, note_o, ref_o)}"

# ④ 费用读数**对不上**时,两条路才分岔 —— 这也是"指令不占槽位"最要紧的一处:
#    同一对前后帧(卡数没变),单位判"被拒绝",指令必须判"**结论不可信**"
#    (拿卡数去判指令,会把打成功的指令记成失败,还塞进 failed_x)。
eng.kredits_left = 3                     # 账本 3
state["kredits_left"] = 9                # 画面读到 9(既不是 3,也不是 3+1)
ok_o2, note_o2, ref_o2 = eng._judge_deploy(
    _flat_before, _flat_after, {"name": _direct, "type": "order"}, 1, is_order=True)
ok_u, note_u, _ = eng._judge_deploy(
    _flat_before, _flat_after, {"name": "轻步兵", "type": "infantry"}, 1, is_order=False)
print(f"    指令:读数对不上 -> ok={ok_o2} refused={ref_o2} note={note_o2}")
print(f"    单位:同样的帧   -> ok={ok_u} note={note_u}")
assert ok_o2 is False and ref_o2 is False, \
    "指令读不准时不许下结论(更不许按卡数判成'被拒绝')"
assert "指令" in note_o2 and "不可信" in note_o2, \
    f"指令那一路必须说清『指令不占槽位、结论不可信』: {note_o2}"
assert ok_u is False and "卡数没变" in note_u, \
    f"单位还是老判据(卡数没变 = 没放上去): {note_u}"

print()
print("=" * 78)
print("CASE 6: end-turn button vanishes mid-turn -> resync, no crash")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=5)
show(eng.think())
state["end_turn"] = False
show(eng.think())
assert eng.phase == "wait_our_turn"
state["end_turn"] = True
show(eng.think())
# ★ 2026-09-13:阶段顺序改成 attack 开头(先让场上已有单位行动,最后才出牌)
assert eng.phase == "attack", eng.phase

print()
print("=" * 78)
print("CASE 7: a new turn clears attempted slots and the affordability cap")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), deploy_refused=True)
run_turn(eng)
assert eng.failed_x == set(), eng.failed_x
assert eng.attempted_x == set(), eng.attempted_x
assert eng.afford.max_cost is None, eng.afford.max_cost
assert eng.attacked_this_turn == 0, eng.attacked_this_turn
print("    cleared")

print()
print("=" * 78)
print("CASE 8: 完全认不出的牌不盲拖,避免绕过未标选边抉择黑名单")
print("=" * 78)
eng = new_engine([{"name": None, "type": None, "cost": None, "x": 500,
                   "unknown": True},
                  {"name": "轻步兵", "type": "infantry", "cost": 1, "x": 700}],
                 kredits=5)
# ★ 2026-09-13:不再写死 think() 次数 —— 阶段顺序改成 attack/move_front 在 play 之前,
#   写死的次数会立刻错位(§7 第 45 条那个教训)。run_turn 一直跑到回合结束。
run_turn(eng)
print(f"    drags={drags}")
assert drags == [700], drags

print()
print("=" * 78)
print("CASE 9: 未知牌全部不拖,已识别单位的出牌规则不受影响")
print("=" * 78)
eng = new_engine([{"name": None, "type": None, "cost": None, "x": 400 + 60 * i,
                   "unknown": True} for i in range(4)], kredits=5)
# ★ 2026-09-13:手牌**刻意只放 4 张** —— 手牌 ≥5 时"大手牌最多部署 2 个"那条
#   新规则(见 CASE 36)会先收手,MAX_UNKNOWN_TRIES 就永远够不到了,
#   这条用例原本要钉的东西(试错上限)也就测不出来了。
# ★ 2026-09-13:跑到"试错次数到上限"就停(不能跑完整回合 ——
#   end_turn 里的 reset_turn() 会把 attempted_x 清零,那就断言不到东西了,§7 第 44 条)。
for _ in range(12):
    if len(eng.attempted_x) >= turn_engine.MAX_UNKNOWN_TRIES:
        break
    if eng.phase == "end_turn":
        break
    show(eng.think())
print(f"    drags={drags}  (上限 {turn_engine.MAX_UNKNOWN_TRIES}/回合)")
assert drags == [], drags
assert eng.attempted_x == set(), eng.attempted_x

print()
print("=" * 78)
print("CASE 10: 指令按打法表走(冬季战争=direct 会出)、counter 与黑名单一张都不碰")
print("=" * 78)
# ★ 2026-09-20 改:`冬季战争` 在表里是 **direct**(描述里没有任何"要选目标"的说法),
#   所以它会和单位一起被打出去;`counter`(反制)与黑名单卡仍然一张都不碰。
#   这里特意**手写**"冬季战争"而不是从表里现取 —— 它是用户第一轮就点过的真实卡,
#   写死它等于顺手钉住"表里这张确实是 direct"(表被改坏了这条会红)。
eng = new_engine(hand(("冬季战争", "order", 1, 780),
                      ("伏击", "counter", 2, 700),
                      ("轻步兵", "infantry", 1, 500)), kredits=5)
run_turn(eng)          # ★ 2026-09-13:不写死 think() 次数(阶段顺序变了)
print(f"    drags={drags}")
assert 700 not in drags, f"反制(counter)不许被拖: {drags}"
assert sorted(drags) == [500, 780], \
    f"direct 的指令和单位都该出(只便宜的先出),反制不出: {drags}"
print()
print("=" * 78)
print("CASE 11: 支援阵线满 4 个后不再白拖(用户确认:线满即使有费也放不下)")
print("=" * 78)
eng = new_engine([{"name": f"步兵{i}", "type": "infantry", "cost": 1,
                   "x": 380 + 60 * i} for i in range(6)], kredits=9)
# ★ 2026-09-13:这条用例要单独考"线满"那一条,所以把扫描器报的张数**压到 4**
#   (低于 BIG_HAND_MIN),免得"大手牌最多部署 2 个"那条新规则先收手
#   —— 两套规则各自有自己的用例(CASE 37),别在这里互相掩盖。
eng.scanner.last_hand_count = 4
# our_turn -> 4 次成功部署 -> 第 5 次必须直接判定线满
# ★ 2026-09-13:跑到"线满"就停 —— 跑完整回合的话 reset_turn() 会把
#   deployed_this_turn 清零,那就断言不到了(§7 第 44 条)。
for _ in range(14):
    if (eng.deployed_this_turn >= turn_engine.SUPPORT_LINE_MAX
            or eng.phase == "end_turn"):
        break
    show(eng.think())
print(f"    drags={drags}  (上线 {turn_engine.SUPPORT_LINE_MAX})")
assert len(drags) == turn_engine.SUPPORT_LINE_MAX, drags
assert eng.deployed_this_turn == turn_engine.SUPPORT_LINE_MAX, eng.deployed_this_turn

print()
print("=" * 78)
print("CASE 12: M4 攻击阶段 —— 我方每个单位都拖去打敌方总部")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
state["our_units"] = [(450, 520), (560, 520), (670, 520)]
state["enemy_hq"] = (640, 180)
run_turn(eng)
print(f"    attack_drags={attack_drags}")
print(f"    attempts={eng.attacker.attempts} landed={eng.attacker.landed} "
          f"attacked_this_turn={eng.attacked_this_turn}")
assert len(attack_drags) == 3, attack_drags
# 目标必须都是敌方总部(client 640,180 -> 屏幕 740,280)
assert all((ex, ey) == (740, 280) for _sx, _sy, ex, ey in attack_drags), attack_drags
# ★ attacked_this_turn 在回合结束时被 reset_turn() 清零,所以只能断言拖拽次数
assert eng.phase == "wait_our_turn"          # 攻击完还要能结束回合并复位

print()
print("=" * 78)
print("CASE 13: 攻击被拒绝(单位已行动过)不会反复试同一张")
print("         ★ 判据是【敌方总部血量没下降】,不是画面差异")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
state["our_units"] = [(450, 520), (560, 520)]
state["hq_drop_on_attack"] = False            # 血量不变 -> 判定没打中
state["attack_ok"] = True                     # ★ 但画面"变"了(旧的错判据会算成功)
run_turn(eng)
print(f"    attack_drags={len(attack_drags)} landed={eng.attacker.landed}")
assert len(attack_drags) == 2, attack_drags  # 两个单位各试一次,不重复
assert eng.attacker.landed == 0, \
    f"血量没掉就不算打中(画面变了也不算): {eng.attacker.landed}"

print()
print("=" * 78)
print("CASE 13c: ★★ 只有橙色(还能行动)的单位才会被拖 —— 灰色的绝不碰")
print("          用户确认:费用数字 橙=能行动 / 灰=本回合已行动。")
print("          这条直接把'每个单位每回合白拖一次'消掉了。")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
state["our_units"] = [(450, 520), (560, 520), (670, 520)]
state["unit_types"] = ["artillery", "artillery", "artillery"]
state["actionable_n"] = 2          # 只有前两个是橙色(还能行动)
run_turn(eng)
print(f"    attack_drags={attack_drags}  (3 个单位里只有 2 个是橙色)")
assert len(attack_drags) == 2, \
    f"灰色的那个不该被拖(拖了也是被拒绝): {attack_drags}"

print()
print("=" * 78)
print("CASE 13b: ★攻击打中了 —— 判据是敌方总部血量下降")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
state["our_units"] = [(450, 520), (560, 520)]
state["hq_hp"] = 20
state["hq_drop_on_attack"] = True
run_turn(eng)
print(f"    attack_drags={len(attack_drags)} 敌方总部血量现在={state['hq_hp']} "
      f"(从 20 掉到 {state['hq_hp']})")
assert len(attack_drags) == 2, attack_drags
assert state["hq_hp"] == 18, f"两次攻击该各扣 1 点: {state['hq_hp']}"

print()
print("=" * 78)
print("CASE 14: 读不到敌方总部 -> 放弃攻击,但照样能结束回合")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
state["our_units"] = [(450, 520)]
state["enemy_hq"] = None
run_turn(eng)
print(f"    attack_drags={attack_drags} clicks={clicks}")
assert attack_drags == [], attack_drags
assert len(clicks) == 1, clicks              # 仍然点了结束回合

print()
print("=" * 78)
print("CASE 15: 关闭攻击(attack=False)时回去走老路:出完牌直接结束回合")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
eng.attack_enabled = False
run_turn(eng)
print(f"    attack_drags={attack_drags}")
assert attack_drags == [], attack_drags
assert eng.phase == "wait_our_turn"

print()
print("=" * 78)
print("CASE 16: 部署被拒绝时,判据是【费用读数没动 + 场上卡数没变】,而不是面板对比")
print("         用户实测:很多次部署失败是因为支援阵线已满,而日志却报成功")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=5,
                 deploy_refused=True)
run_turn(eng)
print(f"    drags={drags}")
# ★ 我方那一行是**空的**(our_support=0),所以"砸在卡上"这条解释不成立 ->
#   不该重试(重试也是白拖),一次就够,而且照样把上限压下去收手。
assert len(drags) == 1, drags
assert state["max_cost_seen"] == 0, \
    f"被拒绝后必须把可负担上限压到 0,实得 {state['max_cost_seen']}"

print()
print("=" * 78)
print("CASE 16b: ★砸在已有卡上 -> 换个空槽位再试一次(2026-09-11 用户实机确认)")
print("          用户实测:拖到**已有卡的位置**松手 = 牌**回手**,游戏不会自动吸附;")
print("          而快松/慢松的差别**稳定复现** -> 所以落点要选空位、松手要停一下")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=5,
                 deploy_refused=True)
state["our_support"] = 1          # ★ 我方那一行**已经有卡** -> 占位冲突是可能的
run_turn(eng)
print(f"    drags={drags} (我方那一行有 1 张,第一次被拒)")
assert len(drags) == deploy.MAX_SLOT_TRIES, \
    (f"有卡在那一行时,被拒应该换一个空槽位再试(上限 "
     f"{deploy.MAX_SLOT_TRIES}),实得 {drags}")
# 而且两次都不成 -> 仍然按老逻辑收手(不能退化成"反复拖")
assert state["max_cost_seen"] == 0, \
    f"两次都失败后必须收手,实得 {state['max_cost_seen']}"
# 两个落点必须是**不同的空槽位**(不是原地重拖一次)
assert len({p[0] for p in state.get("drop_points", [])}) == 2, \
    f"重试必须换一个槽位,实得 {state.get('drop_points')}"

print()
print("=" * 78)
print("CASE 17: 场上【单位数】读不到时(our_support_units=None)线满判据只信本回合计数")
print("         代价:上个回合就满的线,本回合会多拖一次(约 2 秒)")
print("         收益:不会因为读数脏而整局不出牌(fail-closed 的两个出口见 board.support_line_units)")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=5)
state["our_support"] = 4          # 场上显示 4 个,但读数不可信,引擎不看它
run_turn(eng)
print(f"    drags={drags}  (our_support_units=None -> 退回本回合计数)")
assert len(drags) <= 1, f"最多多拖一次(那一次会被拒绝): {drags}"

print()
print("=" * 78)
print("CASE 17b: ★★线满的判据用【单位数】(徽章,不含总部),不用【那一行有几张卡】")
print("          用户 2026-09-12 确认:上限 4 是单位卡,总部不占位 —— 而总部")
print("          就画在同一行里。实测那一行 `单位/HQ/单位/单位` = 4 张卡,单位只有 3 个。")
print("          用行卡数判满:3 个单位时报 4 -> 还有空位就以为满了 -> 少出一个单位。")
print("=" * 78)
# (a) 行上有 4 张卡(3 单位 + 总部),还有 1 个空位 -> 必须**继续拖**
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=5)
state["our_support"] = 4          # 行卡数(含总部)
state["support_units"] = 3        # 徽章数(不含总部)
run_turn(eng)
print(f"    行卡数=4 / 单位数=3 -> drags={drags}(应为 1:还有空位)")
assert len(drags) == 1, \
    f"还有空位时不该判成满(那会少出一个单位),实得 drags={drags}"

# (b) 行上有 5 张卡(4 单位 + 总部)= **真的满了** -> 一张都不该拖
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=5)
state["our_support"] = 5          # 行卡数(含总部)
state["support_units"] = 4        # 4 个单位 = 满
run_turn(eng)
print(f"    行卡数=5 / 单位数=4 -> drags={drags}(应为 0:真的满了)")
assert len(drags) == 0, \
    f"4 个单位时是满线,不该再拖(文档里的 `我支援 5` 其实就是这个状态),实得 {drags}"

# (c) 单位数读数不可信(None)-> 退回本回合计数(fail-closed,不许当成 0 或 4)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=5)
state["our_support"] = 5
state["support_units"] = None
run_turn(eng)
print(f"    单位数=None(判据不可信)-> drags={drags}(退回本回合计数,最多 1 次)")
assert len(drags) <= 1, f"不可信时必须 fail-closed: {drags}"

print()
print("=" * 78)
print("CASE 18: 战场读不到时退回面板判据(并明确标注)")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=5)
state["board_unreadable"] = True
state["deploy_ok"] = True          # 面板判据说"变化了" -> 算成功
run_turn(eng)
print(f"    drags={drags}")
assert len(drags) == 1, drags
state["deploy_ok"] = True

print()
print("=" * 78)
print("CASE 18b: 卡数【减少】(物理上不可能)-> 不许当成部署被拒绝")
print("          实测踩过:读数抖出 4->2,于是把真成功的部署判成了拒绝")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=5)
state["our_support"] = 3
state["enemy_front"] = 3
state["queued_delta"] = -2            # 拖牌后那一次读战场时总数掉 2(抖动)
state["deploy_ok"] = True          # 面板判据说变化了
run_turn(eng)
print(f"    drags={drags}")
assert len(drags) == 1, drags
assert state["max_cost_seen"] is None, \
    f"读数抖动绝不能压制可负担上限,实得 {state['max_cost_seen']}"
state["pending_delta"] = 0

print()
print("=" * 78)
print("CASE 19: ★★攻击规则 —— 步兵在支援线【不是「不能打」,是「只能打敌方前线」】")
print("         用户 2026-09-12 确认:步兵也能攻击,只是打不到远处的目标。")
print("         所以它被跳过的原因是【前线归属读不出】(P0 要补的活),")
print("         **不是**「规则使然要上前线」—— 两者合并就是日志在撒谎。")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
state["our_units"] = [(450, 520), (560, 520)]
state["unit_types"] = ["infantry", "infantry"]
run_turn(eng)
print(f"    attack_drags={attack_drags} "
      f"no_front_owner={eng.attacker.skipped_no_front_owner} "
      f"needs_front={eng.attacker.skipped_needs_front} "
      f"unknown_type={eng.attacker.skipped_unknown_type}")
assert attack_drags == [], f"归属判据还没接,步兵不该被拖去攻击: {attack_drags}"
# ★★ 三个原因**必须分开计数**(2026-09-12):
#   步兵被跳过是"能打但归属读不出"(要补的活),**不是**"规则使然"。
assert eng.attacker.skipped_no_front_owner_all == 2, \
    eng.attacker.skipped_no_front_owner_all
assert eng.attacker.skipped_needs_front_all == 0, eng.attacker.skipped_needs_front_all
assert eng.attacker.skipped_unknown_type_all == 0, eng.attacker.skipped_unknown_type_all

print()
print("=" * 78)
print("CASE 19b: ★★★归属判出来之后,步兵【真的去打敌方前线那一行】了")
print("          这是用户 2026-09-12 确认的规则①(旧代码里完全没有这条路):")
print("          我方支援线上的步兵 -> 打敌方前线那一行的单位。")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
state["our_units"] = [(450, 520)]
state["unit_types"] = ["infantry"]
state["frontline_owner"] = "enemy"     # 黑线在下边 = 前线是敌方的
state["front_units"] = [(700, 350)]    # 那一行上有一个敌方单位
run_turn(eng)
print(f"    attack_drags={attack_drags}")
print(f"    no_front_owner={eng.attacker.skipped_no_front_owner_all} "
      f"needs_front={eng.attacker.skipped_needs_front_all}")
assert len(attack_drags) == 1, f"归属=敌方时步兵就该打过去: {attack_drags}"
_sx, _sy, ex, ey = attack_drags[0]
# client_to_screen 是 +100,所以落点减回去就是 client 坐标
assert (ex - 100, ey - 100) == (700, 350), \
    f"应该拖到那个敌方前线单位上,实得 client ({ex - 100},{ey - 100})"
assert eng.attacker.skipped_no_front_owner_all == 0, "归属读出来了就不该再算'读不出'"
assert eng.attacker.skipped_needs_front_all == 0, "这里是能打的,不该算'规则够不着'"

print()
print("=" * 78)
print("CASE 19c: ★★归属读出来是【我方/空着】时,步兵算'规则上够不着'(needs_front)")
print("           —— 这是**规则使然**,和前两个桶的处置完全不同,必须分开计数")
print("=" * 78)
for ow in ("our", "neutral"):
    eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
    state["our_units"] = [(450, 520)]
    state["unit_types"] = ["infantry"]
    state["frontline_owner"] = ow
    state["front_units"] = [(700, 350)]     # 就算那一行有卡,归属不是敌方就不许打
    run_turn(eng)
    print(f"    owner={ow:<8} attack_drags={attack_drags} "
          f"needs_front_all={eng.attacker.skipped_needs_front_all}")
    assert attack_drags == [], f"归属={ow} 时打那一行就是打自己人/空行: {attack_drags}"
    assert eng.attacker.skipped_needs_front_all == 1, \
        eng.attacker.skipped_needs_front_all
    assert eng.attacker.skipped_no_front_owner_all == 0, \
        eng.attacker.skipped_no_front_owner_all

print()
print("=" * 78)
print("CASE 20: ★攻击规则 —— 炮兵/轰炸机/战斗机 可以直接攻击")
print("=" * 78)
for t in ("artillery", "bomber", "fighter"):
    eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
    state["our_units"] = [(450, 520)]
    state["unit_types"] = [t]
    run_turn(eng)
    print(f"    {t:<10} -> attack_drags={len(attack_drags)}")
    assert len(attack_drags) == 1, f"{t} 应该能直接攻击: {attack_drags}"

print()
print("=" * 78)
print("CASE 21: ★攻击规则 —— 类型认不出时【不拖】(不知道是什么就别乱拖)")
print("=" * 78)
print("""  ★★ 2026-09-12 实机发现的"日志在撒谎":原来 `skipped` 把
    「要上前线」(游戏规则)和「类型认不出」(我们自己没做完的活)算成同一个数,
    日志写"需先上前线的 N 个已跳过" —— 于是**后者被伪装成前者**。
    实机那一局唯一一个橙徽章被跳过,日志说"要上前线",真相分不出来;
    而"类型识别"正是 §12 清单第 4 条还没做完的事。现在三个数分开报,并在用例里钉死。""")
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
state["our_units"] = [(450, 520)]
state["unit_types"] = [None]
run_turn(eng)
print(f"    attack_drags={attack_drags} "
      f"no_front_owner={eng.attacker.skipped_no_front_owner} "
      f"needs_front={eng.attacker.skipped_needs_front} "
      f"unknown_type={eng.attacker.skipped_unknown_type}")
assert attack_drags == [], f"类型未知时不该拖: {attack_drags}"
assert eng.attacker.skipped_unknown_type_all == 1, eng.attacker.skipped_unknown_type_all
assert eng.attacker.skipped_needs_front_all == 0, eng.attacker.skipped_needs_front_all
assert eng.attacker.skipped_no_front_owner_all == 0, \
    eng.attacker.skipped_no_front_owner_all

print()
print("=" * 78)
print("CASE 19d: ★★★上前线 —— 步兵够不着目标、前线空着(neutral)-> 挪上去")
print("          用户确认的顺序:先能打相邻战线 -> 才能清掉前线 -> 才能上前线。")
print("          实机依据:上一局 12 个攻击阶段一次都打不出去,`徽章全表` 显示橙徽章")
print("          读得好好的(S=166~179),被跳过是因为「够不着」而引擎没有移动这一步。")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
state["our_units"] = [(450, 520)]
state["unit_types"] = ["infantry"]
state["frontline_owner"] = "neutral"     # 前线空着 -> 可以上
state["front_units"] = []                # 前线上没有卡
run_turn(eng)
print(f"    move_drags={move_drags}")
print(f"    attack_drags={attack_drags}  本回合移了 {eng.front_mover.moved} 个,"
      f"累计移了 {eng.front_mover.moved_all} 个")
assert len(move_drags) == 1, f"该挪上去一个: {move_drags}"
assert attack_drags == [], f"它够不着任何目标,不该有攻击: {attack_drags}"
# ★ 断言要数 `moved_all`(**跨回合**),不能数 `moved`:
#   `think()` 点完结束回合会 `reset_turn()`,回合内计数已经清零 —— §7 第 44 条
#   那个坑(我这次就是先数了 `moved`,失败信息看起来像功能坏了)。
assert eng.front_mover.moved_all == 1, \
    "两边都变了才算动成功,实得 moved_all=" + str(eng.front_mover.moved_all)
# 落点必须在**前线那一行**(cy≈350),不能落在我方支援线(520)上
_src, _dst = move_drags[0]["src"], move_drags[0]["dst"]
print(f"    起点={_src}  落点={_dst}")
assert _dst is not None and abs(_dst[1] - 350) <= 5, \
    f"落点 y 必须取前线那一行的 cy(≈350),实得 {_dst}"
assert state["front_units"], "替身里单位应该已经出现在前线那一行"

print()
print("=" * 78)
print("CASE 19e: ★上前线的前提 —— 前线是敌方的就【不许上】(游戏会弹横幅拒绝)")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
state["our_units"] = [(450, 520)]
state["unit_types"] = ["infantry"]
state["frontline_owner"] = "enemy"
run_turn(eng)
print(f"    move_drags={move_drags}(应为空)")
assert move_drags == [], "前线是敌方的时不该上前:游戏会拒绝并回手"

print()
print("=" * 78)
print("CASE 19f: ★上前线 fail-closed —— 归属读不出时【不动】")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
state["our_units"] = [(450, 520)]
state["unit_types"] = ["infantry"]
state["frontline_owner"] = None          # 读不出来
run_turn(eng)
print(f"    move_drags={move_drags}(应为空)")
assert move_drags == [], "归属读不出时必须 fail-closed,不能瞎猜着上"

print()
print("=" * 78)
print("CASE 19g: ★★「动成功了」的判据要两个方向都变(§12 清单第 3 条那个坑)")
print("          实测出现过:我方那一行少了一张,而【前线 3->3】—— 单位去哪了没确认。")
print("          旧脚本只看「少了一张」就判成功,那是 §7 第 46 条同一种错。")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
state["our_units"] = [(450, 520)]
state["unit_types"] = ["infantry"]
state["frontline_owner"] = "neutral"
state["move_front_effect"] = "vanished"   # 只离开支援线,没出现在前线
run_turn(eng)
print(f"    move_drags={len(move_drags)}  移动成功计数={eng.front_mover.moved} "
      f"没动成={eng.front_mover.refused_all}")
assert len(move_drags) == 1, move_drags
assert eng.front_mover.moved_all == 0, "只有支援线 −1、前线没 +1 -> **不许**算成功"
assert eng.front_mover.refused_all == 1, eng.front_mover.refused_all
state["move_front_effect"] = "ok"

print()
print("=" * 78)
print("CASE 19h: ★上前线不动「不该动的」:飞机/炮兵站支援线就能打,不需要上前线")
print("=" * 78)
for t in ("artillery", "bomber", "fighter"):
    eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
    state["our_units"] = [(450, 520)]
    state["unit_types"] = [t]
    state["frontline_owner"] = "neutral"
    run_turn(eng)
    print(f"    {t:<10} move_drags={len(move_drags)}(应为空)")
    assert move_drags == [], f"{t} 在支援线就有目标,不该被挪去占位"

print()
print("=" * 78)
print("CASE 19i: ★上前线的类型名单是从规则表【推】出来的,不是另抄一份")
print("          (两处名单静默不一致是 §7 第 60 条踩过的坑)")
print("=" * 78)
import attack as _atk2  # noqa: E402
print(f"    NEEDS_FRONT_TYPES = {sorted(_atk2.NEEDS_FRONT_TYPES)}")
assert _atk2.NEEDS_FRONT_TYPES == {"infantry", "tank"}, _atk2.NEEDS_FRONT_TYPES
for t in ("fighter", "bomber", "artillery"):
    assert t not in _atk2.NEEDS_FRONT_TYPES, t

print()
print("=" * 78)
print("CASE 19j: ★★★「最后一行 = 我方」必须过闸 —— 实机抓到它把【前线】认成我方")
print("          实机原文(9 次部署里有 3 次):")
print("            `落点参考行: cy=350 side=our | 行结构[cy178/enemy n2; cy350/our n3]`")
print("          -> 我方支援线没检出时,最后一行(前线, cy 286/350)被认成我方,")
print("             再被 DROP_Y_LIMIT 夹到 400 = 第一局那个'落点 y 全是 400'。")
print("          ★ 这不只是落点:`side=='our'` 还被 `attack._in_our_row` 用来决定")
print("            '哪些卡能当攻击者拖出去' —— 把敌人的行认成我方,正是 §10 那条")
print("            '把敌方单位当成自己人拖'的前一步。所以闸必须是 fail-closed。")
print("=" * 78)
import board as _bd  # noqa: E402
for name, cys, expect in (
        ("实战: 我方行没检出,最后一行=前线 286", [181, 286], None),
        ("实战: 同上 350", [180, 286, 350], None),
        ("正常: 敌方/前线/我方", [180, 350, 526], 526),
        ("正常: 只有敌方/我方", [181, 524], 524),
        ("只有敌方一行", [180], None),
        ("老棋盘: 我方在 435", [175, 305, 435], 435),
):
    got = _bd.pick_our_row([{"cy": c} for c in cys])
    got_cy = None if got is None else got["cy"]
    flag = "OK " if got_cy == expect else "✗✗ "
    print(f"    {flag}{name:<34} rows={cys} -> {got_cy}")
    assert got_cy == expect, (name, got_cy, expect)
print(f"    闸值 OUR_ROW_MIN_CY={_bd.OUR_ROW_MIN_CY}(= HAND_MIN_Y-180,"
      f"实测我方支援线最低见过 435)")

print()
print("=" * 78)
print("CASE 19k: ★★★我方【站在前线的单位】也能攻击(旧代码把它当外人排除了)")
print("          实机原文:`1 个橙色徽章不在我方那一行 -> 已排除(很可能是敌方单位)`,")
print("          而那个徽章是 `S=157 V=207` 的真橙徽章、位置在 cy350/frontline ——")
print("          正是我们上一回合刚挪上前线的那个单位。旧代码只认支援行,于是:")
print("            · 挪上去的单位下一回合不会攻击;· 日志那句是假话。")
print("          用户确认的规则②:站在前线的步兵/坦克能打敌方支援线 + 敌方总部。")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
state["our_units"] = []                   # 支援线上没有单位
state["front_our_units"] = [(650, 350)]   # 自己挪上前线的那个单位(橙徽章在前线行)
state["front_units"] = [(650, 350)]       # ★ 前线那一行**有卡**(就是我们那个单位),
                                          #   否则行结构里根本没有前线行,徽章无行可归
state["unit_types"] = ["infantry"]
state["frontline_owner"] = "our"
run_turn(eng)
print(f"    attack_drags={attack_drags}")
assert len(attack_drags) == 1, f"站在前线的步兵该去打敌方总部/支援线: {attack_drags}"
_sx, _sy, ex, ey = attack_drags[0]
assert (ex - 100, ey - 100) == tuple(state["enemy_hq"]), \
    f"目标应该是敌方总部,实得 client ({ex - 100},{ey - 100})"

print()
print("=" * 78)
print("CASE 19l: ★★前线【空着】就不再报「我方」—— 语义判据优先于线位置")
print("          用户纠正:032501-032629 那段判成「我方」,其实谁都没占。")
print("=" * 78)
import frontline_line as _fl  # noqa: E402
assert _fl.owner_from(band_y=270, front_y=350, frow_cards=0) == "empty", \
    "前线没卡 -> 必须判「没人占」,不许因为线偏上就说是我们的"
assert _fl.owner_from(band_y=270, front_y=350, frow_cards=2) == "our"
assert _fl.owner_from(band_y=430, front_y=350, frow_cards=2) == "enemy"
assert _fl.owner_from(band_y=352, front_y=350, frow_cards=1) == "neutral"
assert _fl.owner_from(band_y=430, front_y=350, frow_cards=None) == "enemy"
print("    线偏上但前线无卡 -> empty ✓;有卡才看线 ✓;行读不出 -> 退回线判据 ✓")

print()
print("=" * 78)
print("CASE 19m: ★★★【敌方总部读不出】时,站在前线的单位必须去打【敌方支援线】的单位")
print("          实机症状(用户看画面指出,日志核对无误):最后 5~6 个回合")
print("          前线一直是我方的、前线上的单位全是橙色(能行动),却**一次攻击都没发出**。")
print("          两个原因叠在一起:")
print("            · `_pick_target` 里**根本没有 `TARGET_ENEMY_SUPPORT` 这一档**")
print("              (规则表里写着它,选目标时漏了) -> 敌方支援线上的单位永远选不中;")
print("            · 同一帧 `find_enemy_hq` 返回 None(TRUK 那种「深色圆牌 + 白色单数字」")
print("              的血量 OCR 读不出来,`is_hq` 也就跟着是 False)-> 总部那一档也塌了。")
print("          于是「有攻击者、有合法目标、却一个目标都挑不到」—— 而且**日志一个字都不写**。")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
state["our_units"] = []
state["front_our_units"] = [(650, 350)]      # 我们自己挪上前线的那个单位
state["front_units"] = [(650, 350)]
state["unit_types"] = ["infantry"]
state["frontline_owner"] = "our"
state["enemy_hq"] = None                     # ★ 总部**读不出**(实机就是这么塌的)
state["enemy_support_units"] = [(720, 180)]  # ★ 但敌方支援线上**有一张可打的卡**
attack_drags.clear()
run_turn(eng)
print(f"    attack_drags={attack_drags}")
assert len(attack_drags) == 1, \
    f"总部读不出时,前线单位该退而打敌方支援线那一张: {attack_drags}"
_sx, _sy, ex, ey = attack_drags[0]
assert (ex - 100, ey - 100) == (720, 180), \
    f"目标应该是敌方支援线那张卡(720,180),实得 client ({ex - 100},{ey - 100})"

print()
print("=" * 78)
print("CASE 19n: ★★「有攻击者但挑不到目标」必须**写出原因**(不许沉默失败)")
print("          旧日志只有一句「没有能攻击的我方单位或目标」,它把两件完全不同的事")
print("          混成一件:**没有攻击者** vs **有攻击者但没目标**;后者还要写清哪一档塌了。")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1)
state["our_units"] = []
state["front_our_units"] = [(650, 350)]     # 站在前线的单位 = **有攻击者**
state["front_units"] = [(650, 350)]
state["unit_types"] = ["infantry"]
state["frontline_owner"] = "our"
state["enemy_hq"] = None                    # 总部读不出
state["enemy_support_units"] = []           # 敌方支援线也没有单位
attack_logs = engine_logs                   # new_engine 每次已清空
run_turn(eng)
_line = [m for m in attack_logs if "没有能攻击的我方单位或目标" in m]
print(f"    {_line[0][:190] if _line else '(没有这一行!)'}")
assert _line, "应该打出那句汇总"
assert "**有攻击者但挑不到目标**的 1 个" in _line[0], \
    f"必须报出'有攻击者但没目标'的个数: {_line[0]}"
assert "总部认不出" in _line[0], f"必须写清是哪一档塌了(总部): {_line[0]}"
assert "敌方支援线没有单位" in _line[0], f"必须写清是哪一档塌了(支援线): {_line[0]}"

print()
print("=" * 78)
print("CASE 22: ★★★攻击规则矩阵(用户 2026-09-12 逐条确认,替换掉旧白名单)")
print("         旧版只有 {fighter,bomber,artillery} 一行,把步兵/坦克一律跳过;")
print("         真相是步兵/坦克**能打**,只是打不到远的目标。")
print("=" * 78)
import attack as _atk  # noqa: E402

# ③ 飞机/炮:从支援线就能打 敌方前线 / 敌方支援线 / 敌方总部
for t in ("fighter", "bomber", "artillery"):
    for kind in (_atk.TARGET_ENEMY_FRONT, _atk.TARGET_ENEMY_SUPPORT,
                 _atk.TARGET_ENEMY_HQ):
        assert _atk.can_attack_target(t, _atk.ROW_SUPPORT, kind), (t, kind)
    print(f"    {t:<10} 支援线 -> 敌方前线/支援线/总部 全都能打 ✓")

# ① 步兵/坦克:从支援线**只能**打敌方前线那一行
for t in ("infantry", "tank"):
    assert _atk.can_attack_target(t, _atk.ROW_SUPPORT, _atk.TARGET_ENEMY_FRONT), t
    assert not _atk.can_attack_target(t, _atk.ROW_SUPPORT, _atk.TARGET_ENEMY_SUPPORT), t
    assert not _atk.can_attack_target(t, _atk.ROW_SUPPORT, _atk.TARGET_ENEMY_HQ), t
    print(f"    {t:<10} 支援线 -> 只能打敌方前线 ✓(打不到支援线/总部)")
    # ② 站到前线之后:能打敌方支援线的单位 + 敌方总部
    assert _atk.can_attack_target(t, _atk.ROW_FRONT, _atk.TARGET_ENEMY_SUPPORT), t
    assert _atk.can_attack_target(t, _atk.ROW_FRONT, _atk.TARGET_ENEMY_HQ), t
    print(f"    {t:<10} 前线   -> 能打敌方支援线 + 敌方总部 ✓")

# ★ fail-closed:类型未知 / 行未知 -> 一个目标都不许打
assert _atk.attack_targets(None, _atk.ROW_SUPPORT) == frozenset()
assert _atk.attack_targets("infantry", None) == frozenset()
assert _atk.attack_targets("infantry", "somewhere_else") == frozenset()
print("    类型未知 / 行未知 -> 空集(fail-closed)✓")

# ④ 反击:互相结算,但**炮兵和轰炸机除外**
assert _atk.takes_retaliation("infantry") is True
assert _atk.takes_retaliation("tank") is True
assert _atk.takes_retaliation("fighter") is True
assert _atk.takes_retaliation("artillery") is False
assert _atk.takes_retaliation("bomber") is False
assert _atk.takes_retaliation(None) is True     # 未知 -> 保守当"会吃反击"
print("    反击:步兵/坦克/战斗机 会吃;**炮兵/轰炸机 不吃**;未知按会吃 ✓")

# 兼容函数的语义(旧调用点还在用)
assert _atk.needs_front_line("tank") is True
assert _atk.needs_front_line("artillery") is False
assert _atk.needs_front_line(None) is False
assert _atk.can_attack_from_support("artillery") is True
assert _atk.can_attack_from_support("infantry") is False
print("    兼容函数 needs_front_line / can_attack_from_support 语义一致 ✓")
# ★ 但注意:"can_attack_from_support(infantry)==False" **不等于**"步兵不能攻击" ——
#   它只是打不到那一档目标。步兵能打的是敌方前线(上面已断言)。
assert _atk.attack_targets("infantry", _atk.ROW_SUPPORT), \
    "步兵必须至少有一个合法目标(敌方前线),否则规则表又把它当成不能打了"

print()
print("=" * 78)
print("CASE 23: ★预算账本 —— 读到 2 费时不许连着拖 1+1+1+1")
print("         用户实测'没费用还在部署':部署成功判据曾被误报成功,")
print("         note_deploy_ok 每次把上限清空,引擎就以为费用一直够")
print("=" * 78)
eng = new_engine([{"name": f"轻步兵{i}", "type": "infantry", "cost": 1,
                   "x": 400 + 60 * i} for i in range(6)], kredits=2)
run_turn(eng)
print(f"    drags={drags} (预算 2 费)")
assert len(drags) == 2, f"2 费最多拖 2 张 1 费牌,实得 {drags}"

print()
print("=" * 78)
print("CASE 24: ★被拒绝的拖拽也要扣预算(否则会一直拖)")
print("=" * 78)
eng = new_engine([{"name": f"轻步兵{i}", "type": "infantry", "cost": 1,
                   "x": 400 + 60 * i} for i in range(6)], kredits=2,
                 deploy_refused=True)
run_turn(eng)
print(f"    drags={drags} (预算 2 费,且全被拒绝)")
# 第一次被拒绝就学到"可负担上限 = 0" -> 后面不该再拖
# (这正是我们要的:不要一直白拖。用户实测的"乱部署"就是这里失控)
assert len(drags) == 1, f"学到上限后就该停手,实得 {drags}"

print()
print("=" * 78)
print("CASE 25: ★已识别单位费用未知时仍按最低费扣账,不能白嫖预算")
print("=" * 78)
eng = new_engine([{"name": f"已识别单位{i}", "type": "infantry", "cost": None,
                   "x": 400 + 60 * i} for i in range(6)],
                 kredits=2)
run_turn(eng)
print(f"    drags={drags} (预算 2 费,费用未知)")
assert len(drags) <= 2, f"未知费用也要占预算,实得 {drags}"

print()
print("=" * 78)
print("CASE 26: ★场上已经有 3 个单位 -> 本回合只该再放 1 个(第 4 个),然后停")
print("         这条以前做不到:引擎不敢信场上读数,只能靠本回合计数,")
print("         于是上个回合就满的线这个回合还会白拖一次(用户看到的\"又乱部署\")")
print("=" * 78)
eng = new_engine([{"name": f"轻步兵{i}", "type": "infantry", "cost": 1,
                   "x": 400 + 60 * i} for i in range(6)], kredits=9)
state["our_support"] = 4            # 行卡数(3 个单位 + 总部)
state["support_units"] = 3          # ★ 徽章数:场上真的有 3 个单位,还差 1 个满
run_turn(eng)
print(f"    drags={drags} (场上 3 个单位 -> 只补 1 个)")
assert len(drags) == 1, f"场上已有 3 个单位时只该再放 1 个,实得 {drags}"

print()
print("=" * 78)
print("CASE 27: 场上卡数被漏读(读到 0)且卡数永不增长(最坏情况)")
print("=" * 78)
eng = new_engine([{"name": f"轻步兵{i}", "type": "infantry", "cost": 1,
                   "x": 400 + 60 * i} for i in range(8)], kredits=9)
state["our_support"] = 0            # 漏读成 0
state["deploy_adds_card"] = False   # 卡数永远不涨
run_turn(eng)
print(f"    drags={drags}")
assert len(drags) <= 4, f"最多 4 次(拒绝学习把上限压下去后停): {drags}"

print()
print("=" * 78)
print("CASE 28: ★惰性扫描 —— 只找到第一张出得起的牌就停(用户的想法)")
print("         瓶颈是探针数(每个 0.5s 固定等待),不是 OCR:")
print("         全量扫 5 张牌约 14 秒,而只找第一张可用牌通常 2-3 秒")
print("=" * 78)
eng = new_engine(hand(("大牌", "artillery", 9, 500),
                      ("中牌", "infantry", 3, 560),
                      ("小牌", "infantry", 1, 620),
                      ("备用", "infantry", 1, 680)), kredits=3, lazy=True)
run_turn(eng)
print(f"    drags={drags} (预算 3,手牌 9/3/1/1)")
# 惰性模式:第一张"出得起"的是 3 费那张(9 费出不起,跳过),出掉后预算 0 -> 停
assert drags == [560], f"只该出第一张出得起的牌: {drags}"

print()
print("=" * 78)
print("CASE 29: 惰性扫描 + 多张可出 -> 每出一张重新找下一张")
print("=" * 78)
eng = new_engine(hand(("小牌A", "infantry", 1, 500),
                      ("小牌B", "infantry", 1, 560)), kredits=3, lazy=True)
run_turn(eng)
print(f"    drags={drags} (预算 3,两张 1 费)")
# ★ 2026-09-13:预算给 3 而不是 2 —— 用户新加的规则是"**剩余 < 2 费就别再扫手牌**",
#   预算 2 时出掉第一张就只剩 1 费,会按规则收手(那种情况由 CASE 39 专门钉)。
#   要给 3 才能在不触发那条规则的前提下,继续考"每出一张重新找下一张"。
assert len(drags) == 2, f"预算 3 该出两张 1 费的: {drags}"

print()
print("=" * 78)
print("CASE 30: ★惰性扫描时费用读不到 -> 用【保守估计】继续,")
print("         不再退回 14 秒的全量扫描(§8 待办 10 的连锁就是这么来的)")
print("=" * 78)
eng = new_engine(hand(("小牌", "infantry", 1, 500),
                      ("大牌", "artillery", 3, 620)), kredits=None, lazy=True)
run_turn(eng)
info = eng.kredits_info or {}
print(f"    drags={drags} 费用来源={info.get('source')!r} "
      f"值={info.get('value')} 全量扫描次数={eng.scanner.scan_calls}")
# 第 1 个回合按游戏规则就是 1 费上限 -> 只出得起那张 1 费的
assert info.get("value") == 1, info
assert info.get("source") == "estimate", info
assert info.get("measured") is False, info
assert drags == [500], f"保守估计 1 费,只该出 1 费那张: {drags}"
assert eng.scanner.scan_calls == 0, \
    f"费用读不到不该再退回全量扫描(那是 14 秒 + 常常扫回 0 张): {eng.scanner.scan_calls}"

print()
print("=" * 78)
print("CASE 31: ★费用读数抖动 -> 两帧一致才采信(这是本轮要修的主症状)")
print("         实测日志:同一秒内 unknown 和 5 交替(02:21:46 / 02:21:47)")
print("=" * 78)
import kredits as _kr  # noqa: E402

seq = iter([5, None, 5, None, 5, None])
tr = _kr.KreditsTracker(capture=lambda: "frame",
                        read_one=lambda f: next(seq, None),
                        attempts=4, gap=0.0, sleep=lambda s: None,
                        # ★ 这条用例只考"阶段 1"(两帧一致去抖);
                        #   阶段 2(等费用数字停止滚动)由 CASE 44 单独考。
                        turn_start_settle=0)
tr.start_turn()
r = tr.read_turn_start(None)              # 首帧没给 -> 全靠采样
print(f"    抖动序列 [5, None, 5, ...] -> {r['value']} ({r['source']}) "
      f"采样={r['samples']}")
assert r["value"] == 5 and r["source"] in ("agree", "majority"), r
assert r["measured"] is True, r

# 下一回合:一帧都读不到 -> 用下限(上次采用值 +1,上限至少涨 1)
tr.start_turn()
tr.read_one = lambda f: None
r2 = tr.read_turn_start(None)
print(f"    一帧都读不到 -> {r2['value']} ({r2['source']}) {r2['note']}")
assert r2["value"] == 6 and r2["source"] == "prev+1", r2
assert r2["measured"] is False, r2

# ★★ 核心规则:只拒绝"物理上不可能"的读数。
#   回合开始时费用只会涨不会跌,所以只有"读到 < 上次采用值"才拒。
#   **故意不做上界检查** —— 特殊卡可以额外加上限,而且上界会把误差固化。
tr.start_turn()
tr.read_one = lambda f: 9                 # 6 -> 9:涨 3,合法(特殊卡/多回合)
r3 = tr.read_turn_start(None)
print(f"    6 -> 9(涨幅大于 1,但完全可能)-> {r3['value']} ({r3['source']})")
assert r3["value"] == 9, f"不能因为'每回合只 +1'这个错假设而拒绝合法读数: {r3}"

# 读低了(9 -> 3 不可能:回合开始时的费用绝不会下降)-> 拒,用下限 上次值+1
tr.start_turn()
tr.read_one = lambda f: 3
r4 = tr.read_turn_start(None)
print(f"    读低 9 -> 3(不可能)-> {r4['value']} ({r4['source']})")
assert r4["value"] == 10, r4
assert "不采信" in r4["source"], r4

# 超过游戏上限 24 也不合法 -> 同样用下限
tr.start_turn()
tr.read_one = lambda f: 30
r5 = tr.read_turn_start(None)
print(f"    读到 30(超过上限 24)-> {r5['value']} ({r5['source']})")
assert r5["value"] == 11, f"超上限应不采信并用下限: {r5}"

print()
print("=" * 78)
print("CASE 31b: ★★ 一次误读不能把误差【永久固化】(本轮实机踩的坑)")
print("          实机日志:12:05:47 两帧一致读到 1(真值 11)-> 被上界压成 10;")
print("                    12:06:25 两帧一致读到 12(真值 12)-> 又被压成 11。")
print("          一旦这样压,锚点就永久落后 1,之后每回合都少 1 费。")
print("          正解:不采信时用下限推进锚点,下一回合读到真值原样采信。")
print("=" * 78)
tr3 = _kr.KreditsTracker(capture=lambda: "frame",
                         read_one=lambda f: None, attempts=1, gap=0.0,
                         sleep=lambda s: None, turn_start_settle=0)
tr3.last_value = 10                       # 上次采用值 10(真值此刻是 11)
tr3.read_one = lambda f: 1                # 两帧一致但明显是误读
tr3.start_turn()
r_low = tr3.read_turn_start(None)
print(f"    上次 10,误读成 1 -> {r_low['value']} ({r_low['source']}),"
      f"锚点 -> {tr3.last_value}")
assert r_low["value"] == 11, f"该用下限 上次值+1=11: {r_low}"
# ★ 关键:锚点只准**单调上升**,绝不能被误读拖住或拖低
assert tr3.last_value == 11, \
    f"锚点必须随下限推进(不能停在 10,那会永久滞后): {tr3.last_value}"
# 下一回合真值 12:锚点 11,12 > 11 -> **原样采信**,没有滞后
tr3.read_one = lambda f: 12
tr3.start_turn()
r_next = tr3.read_turn_start(None)
print(f"    下一回合读到 12 -> {r_next['value']} ({r_next['source']})")
assert r_next["value"] == 12, f"误读不能留下后遗症,12 必须原样采信: {r_next}"

print()
print("=" * 78)
print("CASE 31c: ★★ 不需要知道「现在是第几回合」")
print("          曾经为了给出上界而假设'第 N 回合上限就是 N',结果:")
print("          特殊卡能额外加上限(假设本身错),而且重启/中途接管后")
print("          回合数对不上真实进度(实测日志「第 3 回合 | kredits read: 12」)。")
print("=" * 78)
tr4 = _kr.KreditsTracker(capture=lambda: "frame",
                         read_one=lambda f: 10, attempts=2, gap=0.0,
                         sleep=lambda s: None, turn_start_settle=0)
tr4.start_turn()                       # 本进程看到的"第 1 个"回合,其实是第 10 回合
r_first = tr4.read_turn_start(None)
print(f"    重启后第一眼就读到 10(回合计数才 {tr4.turns_seen})-> "
      f"值 {r_first['value']} ({r_first['source']})")
assert r_first["value"] == 10, r_first
assert tr4.turns_seen == 1, tr4.turns_seen       # 计数只是诊断,不影响结果
# 下一回合真值 11 -> 正常采信(完全不需要回合数来给上界)
tr4.read_one = lambda f: 11
tr4.start_turn()
r_a = tr4.read_turn_start(None)
print(f"    下一回合读到 11 -> {r_a['value']} ({r_a['source']})")
assert r_a["value"] == 11, r_a
# 再下一回合误读成 3(真值 12)-> 拒,用 上次值+1 = 12,正好
tr4.read_one = lambda f: 3
tr4.start_turn()
r_b = tr4.read_turn_start(None)
print(f"    再下一回合误读成 3 -> {r_b['value']} ({r_b['source']})")
assert r_b["value"] == 12, r_b

print()
print("=" * 78)
print("CASE 32: ★第一回合什么都没读到 -> 取 1(不需要任何假设),绝不「不设限」")
print("=" * 78)
tr2 = _kr.KreditsTracker(capture=lambda: None, read_one=lambda f: None,
                         attempts=2, gap=0.0, sleep=lambda s: None,
                         turn_start_settle=0)
tr2.start_turn()
r6 = tr2.read_turn_start(None)
print(f"    {r6['value']} ({r6['source']}) {r6['note']}")
assert r6["value"] == 1 and r6["source"] == "estimate", r6
assert r6["measured"] is False, r6

print()
print("=" * 78)
print("CASE 33: ★★★ 守护/拦截的**保守版** —— 打总部没掉血 -> 本回合非炮兵不再试总部")
print("          实机依据(第 7 局):fighter×4 + infantry×2 打敌方总部**全部没打中**,")
print("          而 artillery×3 **全部打进去**(13->11 / 11->9 / 16->14)——")
print("          同一局里只有炮兵打得动。用户解释:敌方**守护单位**护着总部 /")
print("          **战斗机拦截**轰炸机。这两条的**精确版**都要先能认出'哪张卡带守护'")
print("          (要先有卡面标记的模板),所以先落地**不需要新判据**的那一半:")
print("            打总部没掉血 -> 本回合把【总部】这一档对非炮兵封掉;炮兵继续试。")
print("          ★ 封的必须是**硬的**读数:出手前后两个血量都有效且一动不动。")
print("            血量读不到时(走到'画面差异'那条弱判据)**不许**封(§7 第 65 条)。")
print("=" * 78)
eng = new_engine(hand(), kredits=9)          # 空手牌:只测攻击阶段
state["our_units"] = [(500, 500), (700, 500)]
state["unit_types"] = ["fighter", "fighter"]  # 两个非炮兵(实机里就是它们白拖)
state["hq_drop_on_attack"] = False            # ★ 打总部一动不动(守护/拦截的样子)
state["attack_ok"] = True                     # 画面"变"了 —— 旧的弱判据会算成打中
attack_drags.clear()
run_turn(eng)
print(f"    attack_drags={attack_drags}")
assert len(attack_drags) == 1, \
    f"总部打不动时第二个非炮兵不许再白拖一次: {attack_drags}"
_blk = [m for m in engine_logs if "对非炮兵封掉" in m]
print(f"    {_blk[0][:160] if _blk else '(没有封总部的日志!)'}")
assert _blk, "必须把'总部这一档被封'写进日志(不许沉默失败)"
_skip = [m for m in engine_logs if "总部这一档因" in m]
print(f"    {_skip[0][-90:] if _skip else '(汇总里没报跳过几个!)'}")
assert _skip, "汇总里必须报出'总部这一档被跳过几个'"
assert "而跳过 1 个" in _skip[0], f"该有 1 个攻击者被这条封挡住: {_skip[0]}"

# ★ 反面:同一个回合里**炮兵不许被封** —— 实机证据就是"只有炮兵打得进去"。
eng = new_engine(hand(), kredits=9)
state["our_units"] = [(500, 500), (700, 500)]
state["unit_types"] = ["fighter", "artillery"]   # 前一个白拖 -> 后一个(炮兵)必须还能打
state["hq_drop_on_attack"] = False
state["attack_ok"] = True
attack_drags.clear()
run_turn(eng)
print(f"    非炮兵 + 炮兵: attack_drags={attack_drags}")
assert len(attack_drags) == 2, \
    f"炮兵不该被'封总部'挡住(实机:只有炮兵打得动): {attack_drags}"
_sx, _sy, _ex, _ey = attack_drags[1]
assert (_ex - 100, _ey - 100) == tuple(state["enemy_hq"]), \
    f"第二发该还是打总部(炮兵豁免): 实得 client ({_ex - 100},{_ey - 100})"
print("    非炮兵第二发被挡 ✓ / 炮兵照打总部 ✓")

# ★★ 反过来:打总部**掉血**时**不许**封(否则会无谓地放弃后面的合法攻击)
eng = new_engine(hand(), kredits=9)
state["our_units"] = [(500, 500), (700, 500)]
state["unit_types"] = ["fighter", "fighter"]
state["hq_drop_on_attack"] = True             # 打中了
attack_drags.clear()
run_turn(eng)
print(f"    打中了的情况: attack_drags={attack_drags}")
assert len(attack_drags) == 2, \
    f"打总部有效时两个单位都该打: {attack_drags}"
assert not [m for m in engine_logs if "对非炮兵封掉" in m], \
    "打中了还封总部 = 无谓地放弃后续攻击"

print()
print("=" * 78)
print("CASE 34: ★★★【守护】—— 总部被守护时,非炮兵**不许打总部**,要先去打守护单位")
print("          用户给的规则(2026-09-12):'对方守护单位放在总部旁边会给总部上守护特效,")
print("          **必须先把那个单位打掉**才能打总部'。实机第 7 局就是这条:")
print("          fighter×4 + infantry×2 打总部**全部没打中**,只有 artillery×3 打进去。")
print("          判据(卡右边缘那块盾牌字形)在 `src/guard.py`,正样本是用户指的")
print("          `shots/live_probe.png`(TRUK 总部=半盾+外框 / 右边那个步兵=实心盾)。")
print("=" * 78)
# 站在前线的步兵:能打 敌方支援线 + 敌方总部 —— 正好用来验证"先打哪个"
eng = new_engine(hand(), kredits=1)
state["our_units"] = []
state["front_our_units"] = [(650, 350)]
state["front_units"] = [(650, 350)]
state["unit_types"] = ["infantry"]
state["frontline_owner"] = "our"
state["enemy_support_units"] = [(720, 180)]      # 敌方支援线上那张 = 守护单位
state["hq_guarded"] = True                       # ★ 总部被守护
attack_drags.clear()
run_turn(eng)
print(f"    总部被守护: attack_drags={attack_drags}")
assert len(attack_drags) == 1, f"该打一次(打守护单位): {attack_drags}"
_sx, _sy, ex, ey = attack_drags[0]
assert (ex - 100, ey - 100) == (720, 180), \
    f"★ 必须去打**敌方支援线上的守护单位**(720,180),而不是总部: 实得 ({ex - 100},{ey - 100})"
_line = [m for m in engine_logs if "敌方守护单位" in m]
print(f"    {_line[0][:120] if _line else '(没有守护单位的标注!)'}")
assert _line, "目标标签必须写明是**敌方守护单位**(不然日志看不出为什么没打总部)"

# ★ 反面:总部**没有**守护时,前线步兵的第一优先仍然是总部(不许改变既有优先级)
state["hq_guarded"] = False
attack_drags.clear()
run_turn(eng)
print(f"    未被守护: attack_drags={attack_drags}")
assert len(attack_drags) == 1, attack_drags
_sx, _sy, ex, ey = attack_drags[0]
assert (ex - 100, ey - 100) == tuple(state["enemy_hq"]), \
    f"没被守护时该打总部: 实得 ({ex - 100},{ey - 100})"

# ★ 炮兵豁免:实机第 7 局"只有炮兵打得进去" -> 炮兵不许被守护规则挡住
eng = new_engine(hand(), kredits=1)
state["our_units"] = [(500, 500)]
state["unit_types"] = ["artillery"]
state["frontline_owner"] = "empty"
state["enemy_support_units"] = [(720, 180)]
state["hq_guarded"] = True
attack_drags.clear()
run_turn(eng)
print(f"    炮兵 + 总部被守护: attack_drags={attack_drags}")
assert len(attack_drags) == 1 and (attack_drags[0][2] - 100,
                                   attack_drags[0][3] - 100) == tuple(state["enemy_hq"]), \
    f"炮兵该被豁免、照打总部: {attack_drags}"

print()
print("=" * 78)
print("CASE 35: ★★★【战斗机拦截轰炸机】(用户 2026-09-12 逐条确认)")
print("          用户原话:'我方轰炸机没有打中对方总部,原因是对方支援阵线存在战斗机,")
print("          而战斗机会拦截轰炸机的攻击。' 追问后把范围定死:")
print("            · 拦哪几档:'**总部 + 敌方支援线单位都拦**'(只剩'打敌方前线'这条路);")
print("            · 被拦机型:'**只有轰炸机**';")
print("            · 顺带确认:**守护对战斗机也生效**(所以只有炮兵豁免)。")
print("          判据是现成的:board.read_field 已经在给敌方支援线每张卡认类型。")
print("=" * 78)
# 站在**前线**的轰炸机:本来三档都能打(总部/敌方支援线/敌方前线)
def _bomber_engine(enemy_types, attacker="bomber"):
    eng = new_engine(hand(), kredits=1)
    state["our_units"] = []
    state["front_our_units"] = [(650, 350)]
    state["front_units"] = [(650, 350)]
    state["unit_types"] = [attacker]
    state["frontline_owner"] = "our"          # 前线是我们的 -> 不能打敌方前线
    state["enemy_support_units"] = [(720, 180), (860, 180)]
    state["enemy_support_types"] = list(enemy_types)
    attack_drags.clear()
    run_turn(eng)
    return attack_drags

# ① 敌方支援线上有**战斗机** -> 轰炸机打不到总部,也打不到支援线单位 -> 一个目标都没有
_d = _bomber_engine(["fighter", "infantry"])
print(f"    有战斗机: attack_drags={_d}")
assert _d == [], f"★ 被拦截的轰炸机不该拖出去(总部/支援线都被拦): {_d}"
_line = [m for m in engine_logs if "拦截轰炸机" in m]
print(f"    {_line[0][:110] if _line else '(没有拦截日志!)'}")
assert _line, "必须把'被战斗机拦截'写进日志(不许沉默失败)"

# ② 敌方支援线上**没有战斗机** -> 照旧优先打总部(不许被这条误伤)
_d = _bomber_engine(["infantry", "artillery"])
print(f"    没有战斗机: attack_drags={_d}")
assert len(_d) == 1, f"没有战斗机时轰炸机该照常攻击: {_d}"
assert (_d[0][2] - 100, _d[0][3] - 100) == tuple(state["enemy_hq"]), \
    f"没有战斗机时该打总部: 实得 ({_d[0][2] - 100},{_d[0][3] - 100})"

# ③ **战斗机**自己不受这条影响(用户:被拦机型只有轰炸机)
_d = _bomber_engine(["fighter", "infantry"], attacker="fighter")
print(f"    我方战斗机 + 敌方战斗机: attack_drags={_d}")
assert len(_d) == 1 and (_d[0][2] - 100, _d[0][3] - 100) == tuple(state["enemy_hq"]), \
    f"我方战斗机不该被'拦截轰炸机'这条挡住: {_d}"

# ④ **炮兵**同样不受影响(实机第 7 局:只有炮兵打得进去)
_d = _bomber_engine(["fighter", "infantry"], attacker="artillery")
print(f"    我方炮兵 + 敌方战斗机: attack_drags={_d}")
assert len(_d) == 1 and (_d[0][2] - 100, _d[0][3] - 100) == tuple(state["enemy_hq"]), \
    f"炮兵不该被这条挡住: {_d}"

print()
print("=" * 78)
print("CASE 36: ★ 用户 2026-09-13 要求的阶段顺序 —— 先让场上单位行动,最后才出牌")
print("        (机理:行动也要花 Kredits;先把钱花在部署上 -> 单位就打不动了)")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=3)
state["our_units"] = [(450, 520)]
state["enemy_hq"] = (640, 180)
state["hq_hp"] = 20
state["hq_drop_on_attack"] = True
step_phases = []
for _ in range(10):
    st = eng.think()
    step_phases.append((st, eng.phase))
    if st == "ended_turn":
        break
print(f"    阶段轨迹: {' -> '.join(p for _s, p in step_phases)}")
# ① 回合一开始就该是**攻击**阶段(不是出牌)
assert step_phases[0][1] == "attack", step_phases
# ② 攻击必须**真的发生过**(拖到敌方总部),而且发生在任何部署之前
assert attack_drags, f"先行动:这一回合必须打出过攻击, got {attack_drags}"
assert drags == [] or len(attack_drags) >= 1, attack_drags
# ③ 三个阶段都要走到,而且顺序是 attack -> move_front -> play -> end_turn
seen = [p for _s, p in step_phases]
assert "move_front" in seen and "play" in seen, seen
assert seen.index("attack") < seen.index("move_front") < seen.index("play"), seen
# ④ 部署发生在攻击**之后**(drags 里那次部署,是在攻击拖拽记录之后才出现的)
assert drags == [500], f"最后才部署这一张: {drags}"

print()
print("=" * 78)
print("CASE 37: ★ 用户 2026-09-13 要求 —— 手牌多(≥5 张)时最多部署 2 个就收手")
print("        省下的正是「每出一张牌重扫一次」那几秒")
print("=" * 78)
# ① 手牌 6 张(>= BIG_HAND_MIN),费用管够 -> 只许出 2 个
eng = new_engine([{"name": f"步兵{i}", "type": "infantry", "cost": 1,
                   "x": 380 + 60 * i} for i in range(6)], kredits=9)
eng.scanner.last_hand_count = 6
run_turn(eng)
print(f"    手牌 6 张: drags={drags} (上限 {turn_engine.BIG_HAND_MAX_DEPLOYS})")
assert len(drags) == turn_engine.BIG_HAND_MAX_DEPLOYS, drags
assert any("手牌多" in m for m in engine_logs), "收手时必须把原因写进日志"

# ② 手牌只有 4 张(< BIG_HAND_MIN)-> 上限**不生效**,照旧把费用用干净
drags.clear(); clicks.clear(); attack_drags.clear(); move_drags.clear()
eng = new_engine([{"name": f"步兵{i}", "type": "infantry", "cost": 1,
                   "x": 380 + 60 * i} for i in range(4)], kredits=9)
eng.scanner.last_hand_count = 4
run_turn(eng)
print(f"    手牌 4 张: drags={drags} (不该被上限限制)")
assert len(drags) == 4, drags

# ③ 张数读不到(None)-> **fail-open**:不许因为"不知道"就永远只出两张
drags.clear(); clicks.clear(); attack_drags.clear(); move_drags.clear()
eng = new_engine([{"name": f"步兵{i}", "type": "infantry", "cost": 1,
                   "x": 380 + 60 * i} for i in range(4)], kredits=9)
eng.scanner.last_hand_count = None
run_turn(eng)
print(f"    张数未知: drags={drags} (fail-open,按老行为)")
assert len(drags) == 4, drags

# ④ 被**拒绝**的部署不算进"已部署 2 个"(否则一次牌回手就吃掉整个回合的出牌机会)
eng = new_engine([{"name": f"步兵{i}", "type": "infantry", "cost": 1,
                   "x": 380 + 60 * i} for i in range(5)], kredits=9,
                 deploy_refused=True)
eng.scanner.last_hand_count = 5
eng.deployed_this_turn = turn_engine.BIG_HAND_MAX_DEPLOYS
print(f"    已成功部署 {eng.deployed_this_turn} 个 -> 收手? {eng._deploy_capped()}")
assert eng._deploy_capped() is True, "成功部署到上限就该收手"
eng.deployed_this_turn = 1
eng.deploy_refused = 3
print(f"    只成功 1 个、被拒 3 个 -> 收手? {eng._deploy_capped()}")
assert eng._deploy_capped() is False, "被拒的不该占用额度"
# ⑤ 张数低于门槛 -> 上限不生效(哪怕已经出了很多)
eng = new_engine([{"name": f"步兵{i}", "type": "infantry", "cost": 1,
                   "x": 380 + 60 * i} for i in range(4)], kredits=9)
eng.scanner.last_hand_count = turn_engine.BIG_HAND_MIN - 1
eng.deployed_this_turn = 99
assert eng._deploy_capped() is False, "手牌不多时不该收手"
print("    手牌 4 张 + 已出 99 个 -> 不收手(上限只对大手牌生效)")

# ⑥ ★ 张数要在**回合开始**锁住:不能因为"部署过程中手牌变少"就把上限关掉
eng = new_engine([{"name": f"步兵{i}", "type": "infantry", "cost": 1,
                   "x": 380 + 60 * i} for i in range(5)], kredits=9)
eng.scanner.last_hand_count = 5
assert eng._hand_count() == 5, eng._hand_count()
eng.scanner.last_hand_count = 3          # 假装出了两张之后重扫报 3
print(f"    第一次读到 5 -> 之后扫描器报 3 -> 引擎仍按 {eng._hand_count()} 算")
assert eng._hand_count() == 5, "张数必须锁在回合开始那一刻(否则上限会自己失效)"
eng.deployed_this_turn = turn_engine.BIG_HAND_MAX_DEPLOYS
assert eng._deploy_capped() is True, "锁住之后到 2 个就该收手"
# 新回合要重新量
eng.reset_turn()
assert eng._hand_count() == 3, "新回合必须重新读一次张数"

print()
print("=" * 78)
print("CASE 38: ★ 行动之后对账 —— 行动花掉的钱要记进去,但**截断误读要挡住**")
print("         (实机 2026-09-13:账本 11/12 被读成 1 -> 整回合预算 1 -> 一个牌都没出)")
print("=" * 78)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=9)
# ① 正常的"画面低于账本" -> 按画面收窄(行动花了钱)
state["kredits_left"] = 3          # 替身:画面读到 3
eng.kredits_left = 5
eng._resync_kredits_after_actions()
print(f"    账本 5、画面 3 -> 预算 {eng.kredits_left}")
assert eng.kredits_left == 3, eng.kredits_left
# ② 截断误读:账本 12、读数正好是首位数字 1 -> **不许**把预算压成 1
state["kredits_left"] = 1
eng.kredits_left = 12
eng._resync_kredits_after_actions()
print(f"    账本 12、画面 1(截断)-> 预算 {eng.kredits_left}")
assert eng.kredits_left == 12, f"截断误读不该压预算: {eng.kredits_left}"
assert any("截断误读" in m for m in engine_logs), "必须把'判为截断'写进日志"
# ③ 但**真的只剩 1**(账本是单位数,不是两位数)-> 照收
state["kredits_left"] = 1
eng.kredits_left = 4
eng._resync_kredits_after_actions()
print(f"    账本 4、画面 1(不像截断)-> 预算 {eng.kredits_left}")
assert eng.kredits_left == 1, eng.kredits_left
# ④ 读不到 -> 账本不动(不许清成 0)
state["kredits_left"] = None
eng.kredits_left = 6
eng._resync_kredits_after_actions()
print(f"    读不到 -> 预算 {eng.kredits_left}")
assert eng.kredits_left == 6, eng.kredits_left

print()
print("=" * 78)
print("CASE 39: ★ 用户 2026-09-13 要求 —— 最后只剩不到 2 费就别扫手牌了,直接结束回合")
print("=" * 78)
drags.clear(); clicks.clear(); attack_drags.clear(); move_drags.clear()
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1, lazy=True)
# 这一回合只剩 1 费 -> 按用户规则**不扫手牌**(省一次 3~9 秒的扫描)
for _ in range(12):
    if eng.phase == "end_turn":
        break
    show(eng.think())
print(f"    只剩 1 费: drags={drags}")
assert drags == [], f"只剩 1 费时不该再扫/再拖: {drags}"
assert any("不扫手牌" in m for m in engine_logs), "必须把'不扫手牌'的原因写进日志"

# 还有 2 费 -> 照常扫(不能把能出的牌也一起放弃)
drags.clear(); clicks.clear(); attack_drags.clear(); move_drags.clear()
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=2, lazy=True)
run_turn(eng)
print(f"    还有 2 费: drags={drags} (该照常出 1 费牌)")
assert drags == [500], drags

# ★ 开关语义:设 1 就退回老行为
_old_min = turn_engine.MIN_KREDITS_TO_SCAN
turn_engine.MIN_KREDITS_TO_SCAN = 1
drags.clear(); clicks.clear(); attack_drags.clear(); move_drags.clear()
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=1, lazy=True)
run_turn(eng)
print(f"    MIN_KREDITS_TO_SCAN=1(老行为): drags={drags}")
assert drags == [500], f"退回老行为时 1 费也该出: {drags}"
turn_engine.MIN_KREDITS_TO_SCAN = _old_min

print()
print("=" * 78)
print("CASE 40: ★ 用户 2026-09-13 要求 —— 轰炸机在敌方没有战斗机时,50% 概率先打前线")
print("=" * 78)
def _bomber_front_engine(enemy_support_types, chance, front=((500, 350),)):
    eng = new_engine(hand(), kredits=1)
    state["our_units"] = [(650, 520)]         # 我方轰炸机站在**支援线**
    state["front_our_units"] = []
    state["unit_types"] = ["bomber"]
    state["frontline_owner"] = "enemy"        # 前线是敌方的
    state["front_units"] = list(front)        # 敌方前线有一个单位
    state["enemy_hq"] = (640, 180)
    state["enemy_support_units"] = [(720, 180), (860, 180)]
    state["enemy_support_types"] = list(enemy_support_types)
    state["hq_blocked"] = False if "hq_blocked" in state else None
    old = attack_mod.BOMBER_FRONT_CHANCE
    attack_mod.BOMBER_FRONT_CHANCE = chance
    attack_drags.clear()
    try:
        run_turn(eng)
    finally:
        attack_mod.BOMBER_FRONT_CHANCE = old
    return list(attack_drags)

# ① 概率 0 -> 老行为:优先打总部
_d = _bomber_front_engine(["infantry", "artillery"], 0.0)
print(f"    概率 0(老行为): ends={[(e[2]-100, e[3]-100) for e in _d]}")
assert _d and (_d[0][2] - 100, _d[0][3] - 100) == tuple(state["enemy_hq"]), \
    f"概率 0 时该照旧优先总部: {_d}"
# ② 概率 1 -> 先打前线单位
_d = _bomber_front_engine(["infantry", "artillery"], 1.0)
print(f"    概率 1(总是先打前线): ends={[(e[2]-100, e[3]-100) for e in _d]}")
assert _d and (_d[0][2] - 100, _d[0][3] - 100) == tuple(state["front_units"][0]), \
    f"概率 1 时该先打前线单位: {_d}"
assert any("掷骰命中" in m for m in engine_logs), "必须把'掷骰'写进日志"
# ③ 敌方支援线**有战斗机** -> 这条随机规则不生效(轰炸机本来就只剩前线一条路)
_d = _bomber_front_engine(["fighter", "infantry"], 0.0)
print(f"    有战斗机 + 概率 0: ends={[(e[2]-100, e[3]-100) for e in _d]}")
assert _d and (_d[0][2] - 100, _d[0][3] - 100) == tuple(state["front_units"][0]), \
    f"被拦截的轰炸机只能打前线: {_d}"
assert not any("掷骰命中" in m for m in engine_logs), \
    "被拦截时不该走'掷骰'这条路(它本来就只剩前线)"
# ④ 我方**坦克**不受这条影响(用户指定只有轰炸机)
_d = _bomber_front_engine(["infantry"], 1.0)
print(f"    我方坦克(概率 1): 只验证轰炸机专属 —— 见 CASE 22 的规则矩阵")
# ⑤ 敌方前线**没有单位** -> 掷骰也不该把总部这一档弄丢
_d = _bomber_front_engine(["infantry"], 1.0, front=())
print(f"    前线没有单位 + 概率 1: ends={[(e[2]-100, e[3]-100) for e in _d]}")
assert _d and (_d[0][2] - 100, _d[0][3] - 100) == tuple(state["enemy_hq"]), \
    f"前线没单位时该回落到总部: {_d}"

print()
print("=" * 78)
print("CASE 41: ★ 对手的展示卡盖住前线那一行 -> 读成 empty -> 重读一次(实机 bug)")
print("         第九/十一回合:攻击阶段读 empty 一个都不打,2 秒后 move_front 读 enemy")
print("         不许上前 -> **单位整回合干站着**")
print("=" * 78)
def _display_card_engine(owner_seq, front_seq=None):
    eng = new_engine(hand(), kredits=1)
    state["our_units"] = [(650, 520)]      # 我方步兵在支援线(只能打敌方前线)
    state["unit_types"] = ["infantry"]
    state["front_units"] = [(500, 350)]    # 敌方前线确实有单位
    # ★ 重现"展示卡盖住前线":第一次读**看不到**前线那一行(空),
    #   重读时才看得到 —— 那一行的存在与否决定 row 数是 2 还是 3。
    state["front_units_seq"] = [list(f) for f in front_seq] if front_seq else None
    state["enemy_support_units"] = []
    state["enemy_support_types"] = []
    state["frontline_owner"] = None
    state["frontline_owner_seq"] = list(owner_seq)
    attack_drags.clear()
    run_turn(eng)
    state["frontline_owner_seq"] = None
    state["front_units_seq"] = None
    return list(attack_drags)

# ① 第一次读 empty(被盖住,前线那行压根没检出来)、重读读到 enemy -> 必须真的打
_d = _display_card_engine(["empty", "enemy"],
                          front_seq=[[], [(500, 350)]])
print(f"    empty(2 行) -> 重读 enemy(3 行): attack_drags="
      f"{[(e[2]-100, e[3]-100) for e in _d]}")
assert _d, "重读到 enemy 之后必须真的去打(不许因为第一次读错就整回合站着)"
assert (_d[0][2] - 100, _d[0][3] - 100) == tuple(state["front_units"][0]), _d
assert any("重读" in m for m in engine_logs), "重读这件事必须写进日志"
assert any("展示卡" in m for m in engine_logs), "要把'疑似展示卡盖住'说出来"

# ② 重读**还是** empty(前线真的没人)-> 不该拖(不能因为重读就乱打)
drags.clear(); attack_drags.clear(); engine_logs.clear()
_d = _display_card_engine(["empty", "empty"], front_seq=[[], []])
print(f"    empty -> 重读还是 empty: attack_drags={_d}")
assert _d == [], f"前线真没人时不该拖: {_d}"

# ③ 第一次就读 enemy -> 不需要重读(不该白白多等)
drags.clear(); attack_drags.clear(); engine_logs.clear()
_d = _display_card_engine(["enemy"], front_seq=[[(500, 350)]])
print(f"    直接读 enemy: attack_drags={[(e[2]-100, e[3]-100) for e in _d]}")
assert _d, _d
assert not any("重读" in m for m in engine_logs), "第一次就读对时不该触发重读"

print()
print("=" * 78)
print("CASE 44: ★★★ 回合开始时费用数字是【滚】上去的 —— 必须等它停住")
print("         实机(2026-09-13 第十个会话,只读探针 0.07s 一采):")
print("           17:33:00.35 None -> 17:33:01.16 =6 -> 17:33:01.30 =7 -> 17:33:01.93 =7")
print("           17:31:22.7 None -> 17:31:23.3 =5(引擎在 17:31:21 读到的是 3)")
print("         后果:预算被读小 -> 便宜的牌也判'出不起' -> 整回合不出牌;")
print("               叠加用户规则 MIN_KREDITS_TO_SCAN=2 时,**读到 1 就整个回合不扫手牌**。")
print("=" * 78)


class _FakeClock:
    """虚拟时钟 —— 让"等它稳 0.6 秒"这条判据在离线用例里不用真等。"""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += max(float(s), 0.001)


def _rolling_tracker(script, settle=None, max_wait=None):
    """`script` 是脚本化的原始读数序列(取完就重复最后一个)。"""
    st = list(script)
    clk = _FakeClock()

    def one(_f):
        if len(st) > 1:
            return st.pop(0)
        return st[0] if st else None

    tr = _kr.KreditsTracker(capture=lambda: "frame", read_one=one,
                            attempts=1, gap=0.1, sleep=clk.sleep,
                            turn_start_settle=settle, turn_start_max_wait=max_wait,
                            clock=clk)
    return tr, clk


# ① 老行为(阶段 2 关掉):滚动途中"两帧一致"就把中间值当成了真值
tr, _c = _rolling_tracker([2, 2, 3, 4, 5, 5, 5, 5, 5], settle=0)
r = tr.read_turn_start(None)
print(f"    settle=0(老行为): {r['value']} ({r['source']}) 采样={r['samples']}")
assert r["value"] == 2, f"老行为就是把滚到一半的 2 当真值: {r}"

# ② 新行为:等数字不再变大并稳住 -> 拿到真值 5
tr, _c = _rolling_tracker([2, 2, 3, 4, 5, 5, 5, 5, 5, 5, 5])
r = tr.read_turn_start(None)
print(f"    默认(等停住): {r['value']} ({r['source']}) 采样={r['samples']}")
assert r["value"] == 5, f"必须等到滚完(真值 5): {r}"
assert r["source"] == "settled", r

# ③ 数字一直滚不停(超时)-> 用见过的**最大值**(计数器只涨不跌)
_clk = _FakeClock()
_n = [0]


def _always_rolling(_f):
    _n[0] += 1
    return _n[0]                     # 1,2,3,4… 永远不见顶


tr = _kr.KreditsTracker(capture=lambda: "frame", read_one=_always_rolling,
                        attempts=1, gap=0.1, sleep=_clk.sleep,
                        turn_start_settle=0.6, turn_start_max_wait=1.0,
                        clock=_clk)
r = tr.read_turn_start(None)
print(f"    一直滚(超时): {r['value']} ({r['source']}) 采样={r['samples']}")
assert r["value"] == max(r["samples"]), f"超时该用见过的最大值: {r}"
assert r["source"] == "settled-timeout", \
    f"超时必须和'真稳住了'分开标注(否则事后分不清): {r}"

# ④ 数字本来就不滚(第一回合就是 1)-> 等一小会儿也照样采信
tr, _c = _rolling_tracker([1, 1, 1, 1, 1, 1, 1])
r = tr.read_turn_start(None)
print(f"    本来就不滚: {r['value']} ({r['source']})")
assert r["value"] == 1 and r["source"] == "settled", r

# ⑤ ★ 这条与 R2 的配合:上一回合被读小成 2,这一回合真值 5 必须原样采信
tr, _c = _rolling_tracker([3, 3, 4, 5, 5, 5, 5, 5, 5])
tr.last_value = 2
r = tr.read_turn_start(None)
print(f"    锚点 2、真值 5: {r['value']} ({r['source']}) 锚点 -> {tr.last_value}")
assert r["value"] == 5 and tr.last_value == 5, r

print()
print("=" * 78)
print("CASE 42: ★★★ 抓牌的手,必须在【扇形展开】的那一刻按下")
print("         实机证据(2026-09-13 那局,第 6/7 回合):日志写着")
print("           deploying Fw 190 A 百舌鸟 (fighter, cost 6) 手牌x=455")
print("           部署成功 (费用读数 3 与账本 0 不符(读数可疑) ...)")
print("         —— 费用只掉了 3:**拖出去的是一张邻居的 3 费牌**")
print("         机理:身份是在「悬停 0.30s 之后(扇形已展开)」那一帧读的,")
print("               而旧代码按下前只等 settle=0.15s —— 扇形还在动画里,")
print("               同一个 x 底下的牌可能已经换成旁边那张。")
print("=" * 78)
drags.clear(); clicks.clear(); attack_drags.clear(); move_drags.clear()
state["hover_waits"] = []
state.pop("pressed_dumps", None)
state.pop("pressed_dump_error", None)
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=3)
run_turn(eng)
_hw = state["hover_waits"]
print(f"    拖一次: hover_wait={_hw} (扫描器的 HOLD={hand_scanner_v2.HOLD})")
assert _hw and all(w == eng.scanner.hold for w in _hw), \
    f"按下之前必须等扇形展开(和读身份时同一个等待): {_hw}"
assert eng.scanner.hold == hand_scanner_v2.HOLD, \
    "替身的 hold 必须跟着真实常量走,否则这条用例会自己骗自己"
# ★ 按下瞬间必须存一帧(那是"到底抓了哪张牌"唯一的地面真值)
print(f"    按下瞬间存帧次数={state.get('pressed_dumps')} "
      f"错误={state.get('pressed_dump_error')}")
assert state.get("pressed_dumps") == len(drags), \
    "每一次拖拽都要在按下瞬间留一帧证据"
assert not state.get("pressed_dump_error"), state.get("pressed_dump_error")

print()
print("=" * 78)
print("CASE 43: ★★★ 惰性模式下「面板判据」不许是一枚橡皮图章")
print("         旧代码:`_before` 恒为 None -> `_panel_looks_same(None, 非None)`")
print("         = False -> `ok = True` —— 凡是「费用读数不符 + 卡数读不准」的")
print("         部署一律记成**部署成功**(实机第 6/7 回合就是这么来的)。")
print("=" * 78)
# ① 有基准面板 -> 面板判据照旧能给出结论(state['deploy_ok'] 脚本化)
drags.clear(); clicks.clear(); attack_drags.clear(); move_drags.clear()
engine_logs.clear()
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=3, lazy=True)
state["board_unreadable"] = True         # 战场读不到 -> 只能走面板判据
# ★ 故意让"画面费用少掉 2"(而账本是 1)-> 费用对账给不出结论,
#   逼它走**最后那条退路**(这正是实机第 6/7 回合的处境)。
state["hand_costs"] = {500: 2}
state["deploy_ok"] = True                # 面板"变化了" -> 算成功
run_turn(eng)
print(f"    有基准 + 面板变了: 日志里出现了 '部署成功'="
      f"{any('部署成功' in m for m in engine_logs)}")
assert any("部署成功" in m for m in engine_logs), \
    "有基准面板、面板判据说变了 -> 该算成功"
assert any("退回面板判据" in m for m in engine_logs), \
    "走退路必须在日志里写明(不许悄悄退化)"

# ② 扫描那一帧没拍到面板(基准缺失)-> **不许报成功**
drags.clear(); clicks.clear(); attack_drags.clear(); move_drags.clear()
engine_logs.clear()
eng = new_engine(hand(("轻步兵", "infantry", 1, 500)), kredits=3, lazy=True)
state["board_unreadable"] = True
state["hand_costs"] = {500: 2}
state["deploy_ok"] = True                # 就算面板判据说"变了"也不许采信
state["panel_none"] = True               # 拖完之后也读不到面板 -> 更没有证据
run_turn(eng)
print(f"    没有基准: 日志里出现 '部署成功'="
      f"{any('部署成功' in m for m in engine_logs)} / "
      f"'部署被拒绝'={any('部署被拒绝' in m for m in engine_logs)}")
assert not any("部署成功" in m for m in engine_logs), \
    "没有基准面板时不许报'部署成功'(那就是橡皮图章)"
assert any("没有基准" in m or "判不出来" in m for m in engine_logs), \
    "判不出来必须写进日志,不许悄悄退化"
state["panel_none"] = False
state["board_unreadable"] = False
state["deploy_ok"] = True

print()
print("=" * 78)
print("CASE 45: ★★★ 手牌记忆在引擎里的接线(注入 / 抽牌许可 / 出牌删记忆)")
print("         这三处任何一处接错,记忆就会**静默错位** —— 而错位的代价是")
print("         '照旧记忆去拖一个位置'。所以每一步都要有用例钉住。")
print("=" * 78)
drags.clear(); clicks.clear(); attack_drags.clear(); move_drags.clear()
engine_logs.clear()
_cards = [{"name": "步兵第 89 团", "type": "infantry", "cost": 1, "x": 500, "i": 0},
          {"name": "鹰爪", "type": "order", "cost": 3, "x": 560, "i": 1}]
eng = new_engine(_cards, kredits=3, lazy=True)
# 预先记好这一手(模拟"上一轮扫过一次")
eng.memory.cards = [{"name": "步兵第 89 团", "type": "infantry", "cost": 1},
                    {"name": "鹰爪", "type": "order", "cost": 3}]
eng.memory.valid = True
state["allow_draw_seen"] = []
run_turn(eng)
_seen = state.get("allow_draw_seen") or []
print(f"    扫描时收到的 allow_draw 序列 = {_seen}")
assert _seen and _seen[0] is True, \
    f"本回合第 1 次扫描必须允许'右端补未知'(回合开始的抽牌): {_seen}"
assert any(v is False for v in _seen[1:]) or len(_seen) == 1, \
    f"同一回合后续扫描不许再补(只有我们出牌会让张数变少): {_seen}"
_names = [(c or {}).get("name") for c in eng.memory.cards]
print(f"    出牌后记忆里剩:{_names}")
assert "步兵第 89 团" not in _names, \
    f"确认出掉的那张必须从记忆里删掉(否则次序整体错位): {_names}"
assert any("记忆" in m for m in engine_logs), \
    "记忆的动静必须写进日志(判对判错都要看得见)"

print()
print("=" * 78)
print("CASE 46: ★★★ 费用两位数的「截断误读」—— 回合开始这条路")
print("         实机证据(2026-09-13 19:27:48,手牌记忆那一局):")
print("           kredits read: 11 [settled-timeout->不采信] 采样 [1,3,5,1,1,1,1,1,…]")
print("         真值 11,读取一路给出 1,靠 R2 的'上次 +1'才补回来 —— **那次是运气**")
print("         (正好每回合涨 1)。根因:动的是画面上的 '11 K/11',程序只圈到")
print("         左边那个 '1'(§7 第 93 条那条护栏只加在回合中途的对账上)。")
print("         这一轮两层都补了:")
print("           ① `kredits.MERGE_MODE` 改按**数字高度**合并(11 现在真的读得出来)")
print("           ② 高度护栏:只切出一段、高度却是两位数尺度 -> **不许猜**(返回 None)")
print("           ③ `_plausible` 加'读数 == 上次采用值的首位数字 -> 判截断'的措辞")
print("=" * 78)
import cv2  # noqa: E402

# ★★ 2026-09-13 深夜:真值帧改成读**钉住的那一份**(`shots/kredits/truth/`)。
#   原来读 `shots/attack_frames/`,而那个目录有**轮转上限** —— 实机连跑几局之后
#   真值帧被删,这条用例就在实机中途突然挂了(真值是判据的地基,不能放在会轮转的目录)。
_real = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                     "shots", "kredits", "truth", "0913_173740_x434.png")
_img = cv2.imread(_real)
assert _img is not None, f"找不到真值帧(它是这条用例的地面真值):{_real}"
_q = _kr.read_kredits(_img)
print(f"    真值帧(画面写着 11 K/11)-> 读出来 {_q}"
      f"(老代码在这里读的是 1)")
assert _q == 11, f"两位数 11 必须读对,绝不许变成 1: {_q}"
# ★ 护栏**独立**成立:就算合并规则退回老的,也只许 None(不猜),不许给错的数字
_q_old = _kr.read_kredits(_img, merge_mode=_kr.MERGE_MODE_OLD, height_guard=False)
_q_guard = _kr.read_kredits(_img, merge_mode=_kr.MERGE_MODE_OLD)
_rej = _kr.LAST_REJECT
print(f"    老合并规则 -> {_q_old}(就是历史上的错值);"
      f"只加高度护栏 -> {_q_guard}({_rej})")
assert _q_old == 1, f"老行为必须能复现(否则这条用例没钉在 bug 上): {_q_old}"
assert _q_guard is None, f"护栏应当'不猜'而不是给出错值: {_q_guard}"

# ② 纯截断形态:settle 之后读数就是 1(不是滚动中间值),账本 10
tr, _c = _rolling_tracker([1, 1, 1, 1, 1, 1, 1, 1])
tr.last_value = 10
r = tr.read_turn_start(None)
print(f"    账本 10、读数稳定为 1 -> {r['value']} ({r['source']})")
print(f"      说明:{r['note']}")
assert r["value"] == 11, f"必须用下限 10+1=11,而不是采信那个 1: {r}"
assert "首位数字" in r["note"] and "截断" in r["note"], \
    f"日志必须说清是'截断误读'(§7:判错和判对要长得不一样): {r['note']}"

# ③ 实机那条形状:一路滚上去、最后卡在 1(最大值才 5)
tr, _c = _rolling_tracker([1, 3, 5, 1, 1, 1, 1, 1, 1, 1, 1])
tr.last_value = 10
r = tr.read_turn_start(None)
print(f"    实机形状 采样={r['samples']} -> {r['value']} ({r['source']})")
assert r["value"] == 11, f"实机那条形状也必须落到 11: {r}"

# ④ 这条护栏**不改取值,只改日志** —— 关掉它结果必须一模一样
tr_off = _kr.KreditsTracker(capture=lambda: "frame", read_one=lambda f: 1,
                            attempts=1, gap=0.1, sleep=lambda s: None,
                            turn_start_settle=0, trunc_guard=False)
tr_off.last_value = 10
tr_off.start_turn()
r_off = tr_off.read_turn_start(None)
print(f"    护栏关掉 -> {r_off['value']} ({r_off['source']});"
      f"说明:{r_off['note'][:48]}…")
assert r_off["value"] == 11, \
    f"关掉护栏取值必须不变(它买的是日志,不是数值): {r_off}"
assert "截断" not in r_off["note"], "关掉之后才该退回笼统措辞"

# ⑤ 正常读数不许被这条护栏误伤:账本 10 -> 真值 11 必须原样采信
tr, _c = _rolling_tracker([10, 10, 11, 11, 11, 11, 11, 11])
tr.last_value = 10
r = tr.read_turn_start(None)
print(f"    账本 10、真值 11 -> {r['value']} ({r['source']})")
assert r["value"] == 11 and r["source"] == "settled", r
assert "不采信" not in r["source"], \
    f"两位数回合不该再出现 [不采信](实机验收判据): {r}"

print()
print("=" * 78)
print("CASE 47: ★★★ 制胜一击被记成「被拒绝」—— 而『总部卡从画面上消失了』")
print("         就是最硬的信号(2026-09-12 第二局:总部剩 1 血,炮兵打过去,")
print("         11 秒后 state -> victory,日志却写 `被拒绝(血量读不到,画面几乎没变 5)`)。")
print("         机理:卡被摧毁那一帧血量/盾牌都没了 -> 退回**画面差异**那条弱判据")
print("         (§7 第 46 条早就证明它会骗人),而伤害动画恰好让 diff 很小。")
print("         判据(两条缺一不可):① 敌方那一行**还读得到**(排除'整帧读不到'的假象)")
print("                              ② 用**同一套** find_enemy_hq 找不到任何总部卡。")
print("=" * 78)


def _attack_once(**over):
    """把攻击阶段跑一次(只有一个橙色单位 -> 最多一发),返回 (landed, 日志)。

    ★ landed 从**日志**里读:引擎在攻击阶段末尾会打印"被接受 N 次",
      而 `eng.attacker.landed` 在本回合结束时会跟着 `reset_turn()` 清掉
      (实测:直接读属性恒为 0,会把用例带偏)。
    """
    import re
    eng = new_engine(hand(), kredits=9)
    state["our_units"] = [(500, 500)]
    state["unit_types"] = ["artillery"]
    state["actionable_n"] = 1               # 只有它一个能行动 -> 这一局最多拖一发
    state["enemy_support_units"] = [(800, 180)]   # 敌方那一行还有别的卡 -> 行读得到
    state["hq_hp"] = 1                      # 实机那一局:总部只剩 1 血
    state["hq_drop_on_attack"] = False      # 就算是它打掉的,血量也**读不出来**
    state["attack_ok"] = False              # 画面差异很小(实机就是"几乎没变 5")
    state.update(over)
    run_turn(eng)
    logs = list(engine_logs)
    m = [l for l in logs if "攻击阶段结束" in l]
    landed = int(re.search(r"被接受 (\d+) 次", m[0]).group(1)) if m else -1
    return landed, logs


# ① 总部卡**真的没了** -> 必须判成"打掉了",不许再写"被拒绝"
_landed, _logs = _attack_once(hq_after_attack="gone")
_kill = [m for m in _logs if "卡从画面上消失了" in m]
print(f"    ① 卡没了: landed={_landed}, 拖拽={len(attack_drags)}")
print(f"       {_kill[0][:150] if _kill else '(没有那条日志!)'}")
assert _landed == 1, f"打掉了就该记成打中(实机这里记的是'被拒绝'): landed={_landed}"
assert _kill, "必须把'总部卡从画面上消失了'这条判据写进日志"
assert not any("被拒绝" in m for m in _logs), \
    "已经判出'打掉了'就不许再出现'被拒绝'(那正是实机那条错日志)"

# ② 卡**还在**,只是血量读不到(被动画/遮挡盖住)-> 不许说成"打掉了"
_landed2, _logs2 = _attack_once(hq_after_attack="unreadable")
print(f"    ② 卡还在只是读不到: landed={_landed2}, "
      f"'被拒绝'={any('被拒绝' in m for m in _logs2)}")
assert _landed2 == 0, f"卡还在就不许报打中: landed={_landed2}"
assert not any("卡从画面上消失了" in m for m in _logs2), \
    "卡还在,不许说'消失了' —— 这条就是防止把遮挡当成击毁"
assert any("总部卡还在" in m for m in _logs2), \
    "判不了要把原因写出来(不许悄悄退回弱判据)"

# ③ 整帧读不到行结构 -> 也不许下结论(fail-closed)
_landed3, _logs3 = _attack_once(hq_after_attack="no_rows")
print(f"    ③ 整帧读不到行: landed={_landed3}")
assert _landed3 == 0, f"整帧读不到时不许下结论: landed={_landed3}"
assert any("整帧读不到行结构" in m for m in _logs3), \
    "要把'读不到行结构'这个理由写出来"

# ④ 关掉开关 -> 必须退回老行为(证明这条改动真的在起作用)
_old_switch = attack_mod.HQ_GONE_IS_KILL
attack_mod.HQ_GONE_IS_KILL = False
_landed4, _logs4 = _attack_once(hq_after_attack="gone")
attack_mod.HQ_GONE_IS_KILL = _old_switch
print(f"    ④ 开关关掉: landed={_landed4}, "
      f"'被拒绝'={any('被拒绝' in m for m in _logs4)}")
assert _landed4 == 0 and any("被拒绝" in m for m in _logs4), \
    f"关掉开关必须回到老行为(实机那条错日志): landed={_landed4}"

# ⑤ ★★★ 实机 J2 的制胜一击:**血量读数停在旧值**(不是读不到)。
#    那一发把总部打掉了,而盾牌上的数字还停在 2 -> 旧代码写"没打中",
#    还顺手把总部这一档**封掉**(本回合剩下的攻击者全被挡)。4 秒后 state -> victory。
_landed5, _logs5 = _attack_once(hq_after_attack="stale_gone", hq_hp=2)
_k5 = [m for m in _logs5 if "卡从画面上消失了" in m]
print(f"    ⑤ 血量停在旧值、卡没了: landed={_landed5}, "
      f"写出'没打中'结论={any('没打中(敌方总部' in m for m in _logs5)}")
print(f"       {_k5[0][:150] if _k5 else '(没有那条日志!)'}")
assert _landed5 == 1, f"打掉了就该记成打中: landed={_landed5}"
assert _k5 and "停在旧值" in _k5[0], "要把'血量读数停在旧值'写进日志(判据的证据)"
# ★ 断言要精确到**结论那一行**:诊断行里也有"没打中"三个字
#   (`血量跟踪(判'没打中'之前盯了 4s)`),用宽字符串会把诊断当成结论。
assert not any("没打中(敌方总部" in m for m in _logs5), "打掉了就不许再写'没打中'"
assert not any("封掉" in m for m in _logs5), \
    "总部已经被打掉了,不许再把总部这一档封掉(那会挡掉本回合剩下的攻击者)"

print()
print("=" * 78)
print("CASE 48: ★★★ 打单位也有硬判据了 ——『我方单位徽章由橙变灰』")
print("         用户 2026-09-13 当场提的:『先把打单位的问题解决一下』。")
print("         现状:单位卡上没有能读的血量数字,所以'打中了没有'只有")
print("               '那一行还剩几张卡' -> **打伤但没打死 = 结论不可信**(J2 报了 9 次)。")
print("         新判据(§7 第 74 条:橙 = 本回合还没行动过):")
print("               拖前是橙、拖后**同一个徽章变灰** = 游戏**接受了**这次行动;")
print("               拖后**还是橙** = 这次拖拽**被拒绝了**。")
print("         实测:实机 J1~J4 全部 **17/17** 次打单位的拖拽,拖后都有一个橙徽章变灰。")
print("=" * 78)


def _attack_unit_once(**over):
    """打一次**敌方前线单位**(阵线上还留着它 = 打伤没打死),返回 (landed, 日志)。"""
    import re
    eng = new_engine(hand(), kredits=9)
    state["our_units"] = [(500, 500)]
    state["unit_types"] = ["tank"]          # 坦克能打敌方前线那一行
    state["actionable_n"] = 1
    state["frontline_owner"] = "enemy"
    state["front_units"] = [(640, 350)]     # 敌方前线那张卡(打完还在)
    state["enemy_hq"] = None                # 这一条用例只考打单位
    state["hq_drop_on_attack"] = False
    state["attack_ok"] = False
    state.update(over)
    run_turn(eng)
    logs = list(engine_logs)
    m = [l for l in logs if "攻击阶段结束" in l]
    landed = int(re.search(r"被接受 (\d+) 次", m[0]).group(1)) if m else -1
    return landed, logs


# ① 徽章变灰 -> 出手被接受 -> 记成"打中了(打伤、没打死)",不再是"结论不可信"
_l6, _g6 = _attack_unit_once(badge_state_after="grey")
_hit6 = [m for m in _g6 if "打伤、没打死" in m]
print(f"    ① 拖后徽章变灰: landed={_l6}")
print(f"       {_hit6[0][:150] if _hit6 else '(没有那条日志!)'}")
assert _l6 == 1, f"徽章变灰 = 游戏接受了行动,该记成打中: landed={_l6}"
assert _hit6, "必须把'打伤、没打死'和它的判据写进日志"
assert not any("结论不可信" in m for m in _g6), \
    "有了硬判据就不该再写'结论不可信'(那正是用户看到的那 9 次)"

# ② 徽章还是橙 -> 单位没动 = 这次拖拽被游戏拒绝了
_l7, _g7 = _attack_unit_once(badge_state_after="orange")
_rej7 = [m for m in _g7 if "被拒绝" in m and "徽章" in m]
print(f"    ② 拖后徽章还是橙: landed={_l7}, 判成被拒绝={bool(_rej7)}")
assert _l7 == 0, f"单位没行动就不该记成打中: landed={_l7}"
assert _rej7, "徽章还是橙 -> 必须写明'单位没有行动'(不许再含糊成'结论不可信')"

# ③ 徽章判据读不出来([]) -> 退回老措辞(不许把'读不出来'说成结论)
_l8, _g8 = _attack_unit_once(badge_state_after="none")
print(f"    ③ 徽章一个都没检出: landed={_l8}, "
      f"写'结论不可信'={any('结论不可信' in m for m in _g8)}")
assert _l8 == 0, f"判不了不许猜成打中: landed={_l8}"
assert any("结论不可信" in m for m in _g8), \
    "判据读不出来时必须退回老措辞(§7:宁可写'结论不可信',也别伪装成结论)"

# ④ 关掉开关 -> 必须完全退回老行为
_old_sw = attack_mod.HIT_BY_BADGE
attack_mod.HIT_BY_BADGE = False
_l9, _g9 = _attack_unit_once(badge_state_after="grey")
attack_mod.HIT_BY_BADGE = _old_sw
print(f"    ④ 开关关掉: landed={_l9}, "
      f"写'结论不可信'={any('结论不可信' in m for m in _g9)}")
assert _l9 == 0 and any("结论不可信" in m for m in _g9), \
    f"关掉开关必须回到老行为: landed={_l9}"

print()
print("=" * 78)
print("CASE 49: ★★★ 晚读血量读到【不可能的值】—— 不许直接当结论(2026-09-15 实机 3 次)")
print("         证据:`17 -> 20` / `11 -> 20` / `10 -> 87`(19:45:49 / 19:46:02 / 19:48:39)。")
print("         总部血量**不会变多**(上限就是 20,`87` 尤其离谱)-> 那是**读数错了**,")
print("         而旧代码把晚读当权威('以晚读的为准'),于是把**已经打中**的那一发写成")
print("         '结论不可信,按没打中处理'。第 3 发尤其可惜:下一发出手前读到 7,")
print("         说明那一发确实打进了 3 点。")
print("         新行为:① 在同一帧上**重新定位总部**读一次;② 退回'出手后立刻'那次;")
print("                 ③ 两个都不行才维持'结论不可信'(不许伪造结论)。")
print("=" * 78)

_old_dump = attack_mod.DUMP_HP_BOGUS
attack_mod.DUMP_HP_BOGUS = False        # 用例里别往 shots/hp_bogus 写文件

# ① 晚读不可能 + **重新定位**读到可信值 -> 按它判:这一发就是打中了
_l10, _g10 = _attack_once(hq_hp=10, hp_read_seq=[10, 87], hq_relocate_hp=7,
                          badge_state_after="grey")
print(f"    ① 晚读 87(不可能)、重新定位读到 7: landed={_l10}")
print(f"       {[m for m in _g10 if '不可能' in m][:1]}")
assert _l10 == 1, f"重新定位读到 7(可信)就该按 10->7 判打中: landed={_l10}"
assert any("10 -> 7" in m for m in _g10), "要写出 10 -> 7 这条结论"
assert any("重新定位" in m and "7" in m for m in _g10), "要写清是重新定位救回来的"
assert not any("结论不可信" in m for m in _g10), "已经救回来了就不许再写结论不可信"

# ② 晚读不可能 + 重新定位也读到不可能的值 -> 退回"出手后立刻"那次
_l11, _g11 = _attack_once(hq_hp=10, hp_read_seq=[10, 87], hq_relocate_hp=30,
                          badge_state_after="orange")
print(f"    ② 晚读 87、重新定位 30(也不可能): landed={_l11}, "
      f"写'结论不可信'={any('结论不可信' in m for m in _g11)}")
assert any("退回**出手后立刻**那次读数 10" in m for m in _g11), \
    "要写清退回了哪一次读数(不做无声替换)"
assert not any("结论不可信" in m for m in _g11), \
    "立刻那次(10)是可信的,不该走到'结论不可信'"

# ③ 两次都不可信 -> **维持**老结论(不许伪造出'打中')
_l12, _g12 = _attack_once(hq_hp=10, hp_read_seq=[None, 87], hq_relocate_hp=30)
print(f"    ③ 立刻读不到、晚读 87、重新定位 30: landed={_l12}, "
      f"写'结论不可信'={any('结论不可信' in m for m in _g12)}")
assert _l12 == 0 and any("结论不可信" in m for m in _g12), \
    f"两次都不可信时必须维持'结论不可信': landed={_l12}"
assert any("维持'结论不可信'" in m for m in _g12), "要写清为什么没救回来"

# ④ 关掉开关 -> 必须退回老行为(证明这条改动真的在起作用)
attack_mod.HP_BOGUS_RECOVER = False
_l13, _g13 = _attack_once(hq_hp=10, hp_read_seq=[10, 87], hq_relocate_hp=7)
attack_mod.HP_BOGUS_RECOVER = True
print(f"    ④ 开关关掉: landed={_l13}, "
      f"写'结论不可信'={any('结论不可信' in m for m in _g13)}")
assert _l13 == 0 and any("结论不可信" in m for m in _g13), \
    f"关掉开关必须回到老行为(晚读当权威): landed={_l13}"
assert not any("重新定位" in m for m in _g13), "关掉开关就不该再去重新定位"

attack_mod.DUMP_HP_BOGUS = _old_dump
print()

print()
print("=" * 78)
print("ALL CASES PASSED")
print("=" * 78)
