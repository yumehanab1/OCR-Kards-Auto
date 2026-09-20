"""
deploy.py - drag a hand card onto the battlefield to deploy it (M3).

Per user calibration: dragging any unit card to any point below the midline
(y > ~360) deploys it onto your support line. We drag to a spot below the
midline but above the hand fan and away from buttons.

The drag is performed with real mouse events (down -> stepped move -> up).
"""

from __future__ import annotations

import random

from actions import move_drag
from win import client_to_screen

# deployment target in client coords (midline is y=360; drop at ~y=430-500)
DEPLOY_Y_RANGE = (420, 500)
DEPLOY_X_RANGE = (380, 900)

# ---------------------------------------------------------------------------
# ★★ 落点:从"随机点"改成"空槽位"(2026-09-11 下午,用户实机确认后重做)
#
# 用户实测(小号测试对局)三件事:
#   ① 拖到**已有卡的位置**上松手 -> 牌**回手** —— 游戏**不会**自动吸附到邻近空位;
#   ② 快松 vs 停一秒再松,结果不同(**稳定复现**) -> 见 actions.move_drag 的 DWELL;
#   ③ 没有"点卡再点空位"的替代操作 -> 只能把拖拽修好。
#
# 所以落点必须是**空槽位**,而"空在哪"要**从画面现算**:
#   - 槽位 x:实测我方支援线相邻卡中心间距 **143px**(一局里读到 439/582/725),
#     所以拿"已占位的那些中心"往外推一个 pitch、或者取两张卡中间的空隙;
#   - 落点 y:**必须跟我方那一行走**(实测行带会随对局漂移:同一批帧里
#     我方支援线一行在 cy≈525,而老文档写的 360-440 早就对不上了)。
#     写死 y 的后果是"往上一行丢",那一行很可能是**前线**。
# ---------------------------------------------------------------------------
SLOT_PITCH = 143                       # 相邻槽位中心间距(实测)
# ★ 离任何已有卡中心不到 `pitch * 这个比例` 的位置,**不算空槽位**。
#   实测踩过:一开始用"两张卡的间隙中点"当候选,结果 582/727 两卡的中点 654
#   离两边各只有 72px,而卡宽约 132px —— 那个点其实**还压在这两张卡上**,
#   丢下去照样回手。空位必须离每一张卡都有"半个格子以上"的距离。
SLOT_SAFE_GAP_FRAC = 0.75
DEFAULT_SLOT_XS = (440, 583, 726, 869)  # 读不到行带/那一行没卡时的兜底(实测常见位置)
FALLBACK_DROP_Y = 500                  # 同上,兜底 y
DROP_X_LIMIT = (280, 990)              # 别丢到左右 HUD 上
DROP_Y_LIMIT = (400, 620)              # 别丢到手牌区
MAX_SLOT_TRIES = 2                     # 同一张牌最多试几个落点(别退化成"反复拖")

# ★★★ 2026-09-13(第十个会话):**按下之前先等扇形展开**(A/B 开关)。
#   判据一句话:**读身份用哪个扇形状态,按下就用哪个状态** ——
#   身份是在"悬停 `hand_scanner_v2.HOLD` 之后(扇形已展开)"那一帧认的,
#   而旧代码按下前只等 `actions.move_drag(settle=0.15)`,那一刻扇形还在展开动画里,
#   同一个 x 底下的牌可能已经换成**邻居**那张。
#   实机证据(2026-09-13 那局日志,第 6/7 回合):
#     `deploying Fw 190 A 百舌鸟 (fighter, cost 6) 手牌x=455`
#     `部署成功 (费用读数 3 与账本 0 不符(读数可疑);⚠️卡数异常 6->8 ...)`
#   —— 两次都只掉 3 费,与"抓错了牌(用户看到的是旁边的 38t)"吻合。
#   设 False 就退回老行为(0.15s),用于实机 A/B。
HOVER_BEFORE_PRESS = True


def random_drop_point():
    """
    老的随机落点。**默认已经不用了** —— 实测它正是"部署不生效"的原因之一
    (随机 x 迟早砸在已有的卡上,而砸上去就是回手)。留着是为了 A/B 对比。
    """
    x = random.randint(*DEPLOY_X_RANGE)
    y = random.randint(*DEPLOY_Y_RANGE)
    return x, y


def our_row(field):
    """我方支援线那一行(读不到返回 None)。"""
    rows = (field or {}).get("rows") or []
    our = [r for r in rows if r.get("side") == "our"]
    return our[-1] if our else None


def slot_candidates(occupied, y, x_limit=DROP_X_LIMIT, debug=False):
    """
    在 **y 这一行** 上给出"最可能是空槽位"的 x 候选(按可靠性排序)。

    从 `deploy_candidates` 里抽出来的 —— "上前线"要用**同一套**槽位规则,
    只是行换成前线那一行。两处逻辑必须一致,否则一套修好了另一套还在踩同样的坑。

    occupied: 这一行**已占位**的卡中心 x 列表;空列表 = 这一行没卡。
    """
    occupied = sorted(int(x) for x in (occupied or []))
    raw = []
    for c in occupied:
        for k in (1, -1, 2, -2):
            x = c + SLOT_PITCH * k
            inside = 1 if (occupied and occupied[0] - SLOT_PITCH * 0.6 <= x
                           <= occupied[-1] + SLOT_PITCH * 0.6) else 0
            raw.append((x, abs(k), inside))
    for i, x in enumerate(DEFAULT_SLOT_XS):     # 兜底位置排最后
        raw.append((x, 3 + i, 0))

    safe_gap = SLOT_PITCH * SLOT_SAFE_GAP_FRAC
    scored = []
    for x, k, inside in raw:
        if not (x_limit[0] <= x <= x_limit[1]):
            continue          # ★ 越界的**直接丢**,不要夹取(夹取会把候选推到卡上)
        if occupied:
            d = min(abs(x - o) for o in occupied)
            if d < safe_gap:
                continue
        else:
            d = 10 ** 6       # 那一行没有卡 -> 放哪都行
        scored.append((int(x), int(y), k, inside, d))
    # 排序:先"贴着已有卡那一排"的,再格数小的,最后靠左的
    scored.sort(key=lambda t: (-t[3], t[2], t[0]))
    out, seen = [], []
    for x, yy, _k, _inside, _d in scored:
        if any(abs(x - s) <= 25 for s in seen):
            continue
        seen.append(x)
        out.append((x, yy))
    if debug:
        print(f"    槽位候选: y={y} 已占位x={occupied} -> {out[:4]}")
    return out


def deploy_candidates(field, debug=False):
    """
    给出一串落点 (x, y),按"最可能是空槽位"排序 —— 用于**部署**(我方支援线)。

    判据(全部从画面里读,不用写死的槽位表)见 `slot_candidates`;
    y 一律取**我方那一行的中心**(它随对局漂移);读不到行就退到兜底常数,
    并在日志里写明(不写明的兜底是这个项目最容易踩的坑)。
    """
    row = our_row(field)
    y = None
    occupied = []
    if row is not None:
        y = int(row.get("cy") or 0) or None
        occupied = sorted(int(u["cx"]) for u in (row.get("units") or []))
    if y is None:
        y = FALLBACK_DROP_Y
    y = max(DROP_Y_LIMIT[0], min(DROP_Y_LIMIT[1], y))
    return slot_candidates(occupied, y, debug=debug)


def fallback_drop():
    """
    算不出空槽位时的兜底落点(我方支援线上一个固定点)。

    ★ 2026-09-20(指令卡):**指令不占槽位** —— 支援线满 4 个单位时
      `deploy_candidates()` 会把所有候选都过滤掉、返回空列表,但指令照样能打,
      这时用它。单位**不要**用这个点(那里多半已经有卡,丢上去就是回手)。
    """
    return DEFAULT_SLOT_XS[0], FALLBACK_DROP_Y


def drag_deploy(hwnd: int, card_x: int, card_y: int = 700,
                drop=None, jitter: int = 6, hover_wait: float = None,
                on_pressed=None) -> bool:
    """
    Drag from a hand card at (card_x, card_y) to a drop point and release.
    card_y is the hand hover row (~700). Returns True if events sent.

    鼠标序列本身在 `actions.move_drag` —— 和攻击(attack.py)共用一套,
    保证两边的拖拽行为一致(拖拽时序/停顿的说明也在那里)。

    ★ `drop` 强烈建议显式给(用 `deploy_candidates()` 挑空槽位);
      不给就退化成老的随机点,那正是"砸在已有卡上 -> 回手"的来源。

    ★★★ `hover_wait`(2026-09-13 第十个会话):**按下之前先等扇形展开**。
      为什么必须给,见 `actions.move_drag` 那段说明 —— 一句话:
      **识别身份是在展开态做的,按下也必须在展开态**,否则同一个 x 底下
      可能已经换成邻居那张牌(实机证据:第 6/7 回合"百舌鸟"抓成了 3 费牌)。
      默认 `None` = 保持老行为(0.15s)只给单测/攻击那一路用;
      `turn_engine` 会传**扫描器的 `HOLD`**(0.30s,和读身份时同一个等待)。
    """
    sx0, sy0 = client_to_screen(hwnd, card_x + random.randint(-jitter, jitter), card_y)
    dx, dy = drop or random_drop_point()
    sx1, sy1 = client_to_screen(hwnd, dx, dy)
    kw = {}
    if hover_wait is not None and HOVER_BEFORE_PRESS:
        kw["settle"] = hover_wait
    if on_pressed is not None:
        kw["on_pressed"] = on_pressed
    return move_drag(sx0, sy0, sx1, sy1, **kw)


if __name__ == "__main__":
    import sys
    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from win import find_by_process, set_dpi_aware, set_window_client_size

    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("no kards window")
        raise SystemExit(1)
    hwnd = wins[0]["hwnd"]
    set_window_client_size(hwnd, 1280, 720, 100, 100)
    time.sleep(1)
    print("drag_deploy ready. run with args? (use as module)")
