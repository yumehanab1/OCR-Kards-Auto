"""手游战斗决策。只使用已确认的观察；一次选择可跨行动 hooks 重验证。

本模块没有截图或输入能力。轰炸机仅在选中它时取一次随机数；重验证必须
传回原来的 bomber_roll，不允许因 hook 顺序或新帧重新抽选目标类别。
"""
from __future__ import annotations

import random

GROUND = frozenset(("infantry", "tank"))
RANGED = frozenset(("artillery", "fighter", "bomber"))
TYPES = GROUND | RANGED


def _empty(kind, reason):
    return {"kind": kind, "reason": reason}


def _nearest(cards, actor):
    return min(cards, key=lambda c: abs(c["cx"] - actor["card"]["cx"]))


def _plan(kind, actor, target, category, owner, reason, roll=None):
    return {"kind": kind, "unit": actor, "target": target,
            "actor_type": actor["type"], "target_category": category,
            "front_owner": owner, "bomber_roll": roll, "reason": reason}


def _actor_options(obs, actor):
    """返回固定动作或轰炸机两类目标；不消耗随机数。"""
    owner, typ, row = obs["owner"], actor.get("type", "unknown"), actor.get("row")
    if typ not in TYPES:
        return _empty("pending", "单位类型待确认，不推断远程能力或移动权限")
    if row not in ("support", "front"):
        return _empty("pending", "攻击者所在行待确认")
    fronts, hq = obs.get("enemy_front", []), obs.get("hq")
    if typ in GROUND and row == "support":
        if owner == "enemy":
            if not fronts:
                return _empty("pending", "敌占前线但目标卡未确认，等待新帧")
            legal_fronts = [c for c in fronts if not c.get("protected", False) and
                            c.get("guard_state") != "unknown"]
            if not legal_fronts:
                return _empty("pending", "敌方前线均被守护或守护状态待确认")
            return _plan("attack_unit", actor, _nearest(legal_fronts, actor), "enemy_front", owner,
                         "地面支援单位先清除敌方前线")
        return _plan("movefront", actor, None, "frontline", owner, "地面支援单位上前线")
    if typ in GROUND and owner != "our":
        return _empty("pending", "地面前线单位与前线归属不一致")
    if not hq or hq.get("hp") is None:
        return _empty("pending", "敌方总部位置或血量待确认")
    if typ == "artillery":
        return _plan("attack_hq", actor, hq, "hq", owner, "火炮忽略守护，只攻击总部")
    if typ == "bomber":
        if owner == "enemy" and not fronts:
            return _empty("pending", "敌占前线但轰炸机目标集合未确认")
        if fronts:
            return _plan("bomber_choice", actor, {"hq": hq, "enemy_front": _nearest(fronts, actor)},
                         "bomber_choice", owner, "轰炸机在总部与敌前线之间各半选择")
        return _plan("attack_hq", actor, hq, "hq", owner, "轰炸机无敌前线时只攻击总部")
    guard = obs.get("guard", {})
    status = guard.get("status", "unknown")
    if status == "clear":
        return _plan("attack_hq", actor, hq, "hq", owner, "总部无守护，优先攻击总部")
    if status == "guarded":
        guards = guard.get("hq_guards", guard.get("guards", []))
        # 解除总部保护只选择敌支援守护；前线守护不保护另一行的总部。
        guards = [c for c in guards if c.get("row") in ("enemy_support", "support") and
                  not c.get("protected", False) and
                  c.get("guard_state") != "unknown"]
        if guards:
            target = _nearest(guards, actor)
            return _plan("attack_unit", actor, target, "guard", owner, "先解除总部守护")
        return _empty("pending", "总部有守护但相邻守护未确认或该守护也被保护")
    return _empty("pending", "总部守护状态待确认")


def choose(obs, *, rng=None, bomber_roll=None, allow=None):
    """一次决策。allow(plan)仅限制失败重试；不会令轰炸机改选另一类别。"""
    if obs.get("owner") not in ("our", "enemy", "empty"):
        return _empty("pending", "前线归属待确认")
    pending, actions, moves = [], [], []
    for actor in obs.get("units", []):
        option = _actor_options(obs, actor)
        if option["kind"] == "pending":
            pending.append(option["reason"])
        elif option["kind"] == "movefront":
            moves.append(option)
        else:
            actions.append(option)
    roll = bomber_roll
    denied = False
    for plan in actions + moves:
        if plan["kind"] == "bomber_choice":
            if roll is None:
                roll = (rng or random.random)()
            if not 0.0 <= roll < 1.0:
                raise ValueError("bomber_roll must be in [0, 1)")
            category = "hq" if roll < 0.5 else "enemy_front"
            plan = dict(plan, kind="attack_hq" if category == "hq" else "attack_unit",
                        target=plan["target"][category], target_category=category,
                        bomber_roll=roll)
        if allow is None or allow(plan):
            return plan
        denied = True
    if pending:
        return dict(_empty("pending", pending[0]), bomber_roll=roll)
    return dict(_empty("none", "当前局面行动失败重试已到上限" if denied else "没有合法行动"),
                bomber_roll=roll)


def revalidate(obs, plan, *, actor_match, target_tolerance=26):
    """只核验原决定，绝不另选单位、目标类别或重新掷骰。"""
    if plan.get("kind") in ("pending", "none"):
        return plan
    if obs.get("owner") != plan.get("front_owner"):
        return _empty("pending", "输入前前线归属变化，原决策作废")
    actors = actor_match(obs.get("units", []), plan["unit"])
    if len(actors) != 1 or actors[0].get("type") != plan.get("actor_type"):
        return _empty("pending", "原攻击者不再是同类型的唯一橙色候选")
    if (_actor_options(obs, actors[0]).get("kind") == "bomber_choice" and
            plan.get("bomber_roll") is None):
        return _empty("pending", "轰炸机目标集合变化，原决策作废")
    current = choose(dict(obs, units=actors), bomber_roll=plan.get("bomber_roll"),
                     rng=lambda: (_ for _ in ()).throw(AssertionError("revalidation rerolled")))
    if (current.get("kind"), current.get("target_category")) != (plan["kind"], plan["target_category"]):
        return _empty("pending", "目标类别或守护状态变化，原决策作废")
    old, new = plan.get("target"), current.get("target")
    if old is not None and (new is None or abs(new["cx"] - old["cx"]) > target_tolerance or
                            abs(new["cy"] - old["cy"]) > target_tolerance):
        return _empty("pending", "原目标位置变化，原决策作废")
    return current
