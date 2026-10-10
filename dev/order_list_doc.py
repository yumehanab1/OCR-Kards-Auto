"""Generate the current playable and unavailable PC order-card lists.

Read-only inputs: config/order_plays.json and src/orders.py. No game window or
mouse access. Run from the repository root with: python dev/order_list_doc.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import order_choice  # noqa: E402
import orders  # noqa: E402

PLAN = ROOT / "config/order_plays.json"
PLAYABLE_DOC = ROOT / "docs/generated/指令卡清单.md"
UNAVAILABLE_DOC = ROOT / "docs/generated/打不出去的指令卡.md"

PLAYABLE = {
    "direct": ("直接打出", "拖到战场可用区域。"),
    "target": ("指定目标", "须有可识别的合法目标。"),
    "choice": ("已标边的双牌抉择", "按规则选左或右；只校准 1280×720。"),
    "three": ("单步三选一", "标题核对后随机选一张；只校准 1280×720。"),
}
UNAVAILABLE = {
    "blacklist": ("规则表黑名单", "明确禁止自动打出。"),
    "hand_choice": ("选择手牌", "目标码 5 默认归黑名单；缺少可靠的手牌目标选择。"),
    "unmarked_choice": ("未标选边的抉择", "没有可靠的左/右规则，默认归黑名单。"),
    "counter": ("反制卡", "尚无对手动作的响应时机判据。"),
    "follow": ("两步指令", "打出后还须再选一次目标，后续动作未实现。"),
    "ignored": ("明确不处理", "规则备注要求忽略。"),
    "no_text": ("资料不全", "卡库缺少中文描述，无法确认操作。"),
}
TARGET_TEXT = {
    "1": "敌方单位", "2": "敌方单位或总部", "3": "敌方总部",
    "4": "我方单位", "6": "单位（优先敌方）",
}
ROW_TEXT = {
    "a": "敌方前线", "b": "我方前线",
    "c": "敌方支援线", "d": "我方支援线",
}


def cell(value: object) -> str:
    return str(value if value is not None else "").replace("|", "／").replace("\n", " ")


def sort_key(name: str) -> tuple[int, str]:
    cost = orders.rec_of(name).get("cost")
    return (cost if isinstance(cost, int) else 99, name)


def target_rule(name: str) -> str:
    spec = orders.target_spec(name)
    kind = str(spec.get("kind") or "")
    if kind not in TARGET_TEXT:
        raise ValueError(f"已放行目标码没有文档说明：{name} kind={kind}")
    rows = str(spec.get("rows") or "")
    if any(row not in ROW_TEXT for row in rows):
        raise ValueError(f"目标行码没有文档说明：{name} rows={rows}")
    return TARGET_TEXT[kind] + ("；" + "、".join(ROW_TEXT[row] for row in rows) if rows else "")


def category(name: str, note: str) -> tuple[str, bool]:
    rec = orders.rec_of(name)
    if orders.playable("order", name):
        if orders.is_direct(name):
            return "direct", True
        if orders.is_target(name):
            return "target", True
        if orders.is_choice(name):
            return "choice", True
        if orders.is_three_order(name):
            return "three", True
        raise ValueError(f"已放行但未知出牌路径：{name}")

    if orders.is_blacklisted(name):
        if rec["mode"] == orders.MODE_BLACKLIST:
            return "blacklist", False
        if orders.is_kind5(name):
            return "hand_choice", False
        if orders.is_choice_card(name) and not orders.choice_spec(name):
            return "unmarked_choice", False
        raise ValueError(f"黑名单来源不明：{name}")
    if rec["mode"] == orders.MODE_TARGET and rec.get("follow"):
        return "follow", False
    if rec["mode"] == orders.MODE_UNSUPPORTED:
        if note.startswith("反制卡"):
            return "counter", False
        if "不用管" in note:
            return "ignored", False
        if "没有中文描述" in note:
            return "no_text", False
    raise ValueError(f"未放行原因不明：{name} ({rec['mode']}, {note})")


def inventory() -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, str], int]:
    required = (orders.PLAY_ORDERS, orders.PLAY_TARGETS, orders.PLAY_CHOICES,
                orders.PLAY_THREE_ORDERS, orders.KIND5_AS_BLACKLIST,
                order_choice.ENABLE_SELECTION_STAGE)
    if not all(required):
        raise ValueError("当前开关并非默认全开；不能生成默认规则清单")

    cards = json.loads(PLAN.read_text(encoding="utf-8"))["cards"]
    notes: dict[str, str] = {}
    for card in cards.values():
        name = (card.get("name") or "").strip()
        if name:
            notes.setdefault(name, card.get("note") or "")
    orders.load()
    if not orders._CARDS or set(notes) != set(orders._CARDS):
        raise ValueError("规则表未载入，或按卡名折叠的结果与原始数据不一致")

    playable: dict[str, list[str]] = defaultdict(list)
    unavailable: dict[str, list[str]] = defaultdict(list)
    for name in notes:
        group, allowed = category(name, notes[name])
        (playable if allowed else unavailable)[group].append(name)
    for group in (playable, unavailable):
        for names in group.values():
            names.sort(key=sort_key)
    if sum(map(len, playable.values())) + sum(map(len, unavailable.values())) != len(notes):
        raise AssertionError("分类数量不等于卡名总数")
    return playable, unavailable, notes, len(cards)


def header(title: str, n_cards: int, n_names: int) -> list[str]:
    version = json.loads((ROOT / "config/app_version.json").read_text(encoding="utf-8"))["version"]
    return [
        f"# {title}", "",
        f"> KARDS AUTO {version}，PC 自动出牌规则。由 `dev/order_list_doc.py` 从 "
        f"`src/orders.py` 和 `config/order_plays.json` 生成；{n_cards} 条记录，"
        f"按卡名折叠为 {n_names} 个。不要手改这两份清单。", "",
        "生成命令：`python dev/order_list_doc.py`（在仓库根目录运行）。", "",
    ]


def generate_unavailable(playable: dict[str, list[str]],
                         unavailable: dict[str, list[str]],
                         notes: dict[str, str], n_cards: int) -> str:
    total = sum(map(len, unavailable.values()))
    n_names = total + sum(map(len, playable.values()))
    lines = header("目前不能自动打出的指令卡", n_cards, n_names)
    lines += [
        f"当前默认设置下，**{total} 个卡名**不允许自动打出。这里的“不能用”指"
        "程序不会主动出这张牌，不代表游戏内无法手动使用。", "",
        "| 原因 | 卡名数 |", "|---|---:|",
    ]
    for key, (label, _) in UNAVAILABLE.items():
        lines.append(f"| {label} | {len(unavailable[key])} |")
    lines += [f"| **合计** | **{total}** |", "",
              f"其余 **{n_names - total} 个卡名**按规则放行，见"
              "[可用指令清单](指令卡清单.md)。放行仍要求当局费用充足、画面识别成功，"
              "需要目标的牌还须找到合法目标。", ""]

    for key, (label, reason) in UNAVAILABLE.items():
        names = unavailable[key]
        if not names:
            continue
        lines += [f"## {label}（{len(names)}）", "", reason, "",
                  "| 卡名 | 费用 | 规则备注 |", "|---|---:|---|"]
        for name in names:
            rec = orders.rec_of(name)
            lines.append(f"| {cell(name)} | {cell(rec.get('cost'))} | {cell(notes[name])} |")
        lines.append("")

    lines += [
        "“势不可挡”同时带有后续步骤，已按“选择手牌”计入，不重复统计。"
        "开启/关闭 `PLAY_ORDERS`、`PLAY_TARGETS`、`PLAY_CHOICES`、"
        "`PLAY_THREE_ORDERS`、`KIND5_AS_BLACKLIST` 或"
        " `ENABLE_SELECTION_STAGE` 会改变放行范围；"
        "本清单反映源码默认值。", "",
    ]
    return "\n".join(lines)


def generate_playable(playable: dict[str, list[str]],
                      unavailable: dict[str, list[str]], n_cards: int) -> str:
    n_playable = sum(map(len, playable.values()))
    n_names = n_playable + sum(map(len, unavailable.values()))
    lines = header("当前可自动打出的指令卡", n_cards, n_names)
    lines += [f"默认规则放行 **{n_playable} 个卡名**；另有"
              f" **{n_names - n_playable} 个**暂不打，见"
              "[不能自动打出的指令卡](打不出去的指令卡.md)。", "",
              "| 出牌方式 | 卡名数 |", "|---|---:|"]
    for key, (label, _) in PLAYABLE.items():
        lines.append(f"| {label} | {len(playable[key])} |")
    lines += [f"| **合计** | **{n_playable}** |", "",
              "本表只表示规则允许；某局仍可能因费用、目标、识别或窗口条件而跳过。", ""]
    for key, (label, explanation) in PLAYABLE.items():
        names = playable[key]
        lines += [f"## {label}（{len(names)}）", "", explanation, ""]
        if key == "target":
            lines += ["| 卡名 | 费用 | 目标规则 |", "|---|---:|---|"]
        elif key == "choice":
            lines += ["| 卡名 | 费用 | 选边 |", "|---|---:|---|"]
        else:
            lines += ["| 卡名 | 费用 |", "|---|---:|"]
        for name in names:
            row = f"| {cell(name)} | {cell(orders.rec_of(name).get('cost'))} |"
            if key == "target":
                row += f" {cell(target_rule(name))} |"
            elif key == "choice":
                side = {"1": "左", "3": "右"}[orders.choice_spec(name)["rows"]]
                row += f" {side} |"
            lines.append(row)
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    playable, unavailable, notes, n_cards = inventory()
    PLAYABLE_DOC.write_text(generate_playable(playable, unavailable, n_cards), encoding="utf-8")
    UNAVAILABLE_DOC.write_text(
        generate_unavailable(playable, unavailable, notes, n_cards), encoding="utf-8")
    print(f"{len(orders._CARDS)} 个卡名：放行 {sum(map(len, playable.values()))}，"
          f"暂不打 {sum(map(len, unavailable.values()))}")
    for key, (label, _) in UNAVAILABLE.items():
        print(f"  {label}: {len(unavailable[key])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
