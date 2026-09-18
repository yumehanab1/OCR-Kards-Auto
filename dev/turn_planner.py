"""
turn_planner.py - decide what to do on our turn (M3).

Input: scanned hand cards [{x, cost, type}] + available Kredits.
Output: ordered actions to execute.

Rules (v1, conservative - never do anything dumb):
  - Units (infantry/tank/fighter/bomber/artillery): deploy if cost <= kredits.
  - Orders / countermeasures: do NOT play in v1 (targeting too risky).
  - Never touch a card we already failed to play this turn.
"""

from __future__ import annotations

# card types we are willing to deploy (all unit types; artillery IS a unit)
DEPLOYABLE = {"infantry", "tank", "fighter", "bomber", "artillery"}
# types we never play in v1 (orders usually need targets; counters auto-trigger)
# ★ `countermeasure` 是**卡库里**的拼法,`counter` 是**类型图标模板**的拼法,
#   两个都要登记(实测 2026-09-11:`复仇` 查库给 countermeasure)。详见 turn_engine。
SKIP = {"order", "counter", "countermeasure"}


def plan_turn(cards: list[dict], kredits: int) -> list[dict]:
    """
    cards: from HandScanner.scan() -> [{x, cost, type}]
    kredits: current action points (read from screen)
    Returns list of action dicts sorted by decision order:
      {kind: 'deploy', x, cost, type} or {kind: 'end_turn'}
    """
    actions = []
    deployable = [c for c in cards if c.get("type") in DEPLOYABLE and c.get("cost") is not None]
    # deploy cheapest-to-most-expensive? For grinding we prefer playing as many
    # cheap units as possible; sort by cost ascending.
    deployable.sort(key=lambda c: c["cost"])
    remaining = kredits
    used = set()
    for c in deployable:
        if c["cost"] <= remaining:
            actions.append({"kind": "deploy", **c})
            remaining -= c["cost"]
            used.add(c["x"])
    # always end the turn after we stop playing
    actions.append({"kind": "end_turn"})
    return actions
