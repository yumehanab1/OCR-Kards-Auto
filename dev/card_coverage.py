"""Generate a per-cardId PC capability inventory; never operates the game.

Default prints statistics. --write updates docs/generated/card_coverage.{json,md}.
--check compares generated files, read-only. Permissions come from orders.py;
no description heuristic grants permission or claims per-card in-game evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'dev')]
import order_list_doc
import orders
import weather_cards

DB = ROOT / 'card_db/kards_data.json'
PLAN = ROOT / 'config/order_plays.json'
JSON_OUT = ROOT / 'docs/generated/card_coverage.json'
DOC_OUT = ROOT / 'docs/generated/card_coverage.md'
UNITS = frozenset(('infantry', 'tank', 'fighter', 'bomber', 'artillery'))
CANDIDATES = {
    'conquest': '无需手动目标的抽牌候选；需确认当前友方类型数、抽牌收益及手牌容量，尚未放行。',
    'usaaf': '无需手动目标的抽牌候选；需卡组中美国飞机的可抽信息及手牌容量，尚未放行。',
}
LIMITATIONS = {
    'tactical_retreat': '需当前友方德国单位及不大于4费的限定目标验证。',
    'tank_wedge': '需当前友方德国坦克及邻接单位信息。',
    'ferocious_assault': '需步兵目标、当前属性及指挥点槽关联收益。',
    'forward_base': '需最左手牌身份/费用及后续单位目标。',
    'repel_the_attack': '需最右手牌位置和提前结束回合风险判断。',
    'the_rock_of_gibraltar': '需连续开发选牌流程及策略验证。',
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_inventory() -> dict:
    # Also enforces default runtime switches and validates the name index.
    playable, unavailable, _, _ = order_list_doc.inventory()
    db = json.loads(DB.read_text(encoding='utf-8'))
    plan = json.loads(PLAN.read_text(encoding='utf-8'))['cards']
    source = db['cards']
    ids = [c['cardId'] for c in source]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate cardId in DB')
    names = defaultdict(list)
    for card in source:
        names[card['json']['title']['zh-Hans']].append(card['cardId'])
    rows = []
    for card in sorted(source, key=lambda c: c['cardId']):
        j = card['json']
        cid, ctype = card['cardId'], j['type']
        name = j['title']['zh-Hans']
        rule = plan.get(cid, {})
        note = rule.get('note', '')
        eligible = bool(orders.playable(ctype, name))
        gaps = []
        if ctype in UNITS:
            route, policy = 'unit_deploy', 'eligible'
            rationale = '通用单位部署路径；费用、槽位、身份等仍由当前帧检查。'
        elif ctype == 'countermeasure':
            route, policy = 'counter_unimplemented', 'disabled'
            rationale = '反制没有自动响应时机路径。'
        elif name in weather_cards.names():
            route, policy = 'weather_variant_required', 'conditional'
            rationale = '纯名称不放行；须当前描述解析独立天气版本并再次复核。'
        else:
            category, allowed = order_list_doc.category(name, note)
            if allowed != eligible:
                raise ValueError(f'Runtime permission mismatch: {cid}')
            route = category
            policy = 'eligible' if eligible else ('disabled' if orders.is_blacklisted(name) else 'unreviewed')
            rationale = (note or '采用既有规则')
        if route in ('target', 'hand_choice', 'follow', 'unreviewed'):
            gaps.append('limited_target_or_effect_information_not_audited')
        if route in ('hand_choice', 'follow', 'unmarked_choice', 'counter_unimplemented'):
            gaps.append('gesture_or_timing_not_implemented')
        if len(names[name]) > 1:
            gaps.append('name_does_not_uniquely_identify_cardId')
        if not j.get('text', {}).get('zh-Hans'):
            gaps.append('no_zh_description_may_be_vanilla_unit')
        if cid in CANDIDATES:
            rationale = CANDIDATES[cid]
        if cid in LIMITATIONS:
            rationale += ' ' + LIMITATIONS[cid]
        rows.append({
            'cardId': cid, 'name': name, 'name_en': j['title'].get('en-EN', ''),
            'type': ctype, 'base_cost': j.get('kredits'), 'faction': j.get('faction'),
            'base_attack': j.get('attack'), 'base_defense': j.get('defense'),
            'base_operation_cost': j.get('operationCost'),
            'text_zh': j.get('text', {}).get('zh-Hans', ''),
            'text_en': j.get('text', {}).get('en-EN', ''),
            'same_name_cardIds': names[name], 'rule_policy': policy,
            'runtime_name_eligible': eligible, 'execution_route': route,
            'rule': {k: rule.get(k, '') for k in ('mode', 'kind', 'rows', 'follow', 'src')},
            'rationale': rationale, 'review_candidate': cid in CANDIDATES,
            'information_gaps': gaps,
            'strategy_evaluation': 'not_indexed',
            'per_card_live_evidence': 'not_indexed',
        })
    routes = Counter(r['execution_route'] for r in rows)
    return {
        'schema': 1,
        'scope': 'PC静态能力盘点，不是当前局可行动授权、逐卡识别成功率或胜率统计。',
        'sources': {
            'card_db_sha256': sha(DB), 'order_plan_sha256': sha(PLAN),
            'orders_sha256': sha(ROOT / 'src/orders.py'),
            'weather_sha256': sha(ROOT / 'config/weather_variants.json'),
        },
        'summary': {
            'db_records': len(rows), 'unique_names': len(names),
            'duplicate_name_groups': sum(len(v) > 1 for v in names.values()),
            'types': dict(sorted(Counter(r['type'] for r in rows).items())),
            'execution_routes': dict(sorted(routes.items())),
            'rule_eligible_order_names_including_weather': sum(map(len, playable.values())),
            'unavailable_order_names_including_weather': sum(map(len, unavailable.values())),
            'weather_variants': len(weather_cards.records()),
            'newly_enabled_cards': 0,
        },
        'cards': rows,
    }


def cell(value) -> str:
    return str(value if value is not None else '').replace('|', '／').replace('\n', ' ')


def render(data: dict) -> str:
    s = data['summary']
    lines = ['# PC 全卡能力覆盖清单', '',
             '> 由 `python dev/card_coverage.py --write` 生成；`--check` 只读核对。不要手改。', '',
             f"卡库 **{s['db_records']} 条**，**{s['unique_names']} 个名称**，"
             f"**{s['duplicate_name_groups']} 组重名**。每个 cardId 单列，详见 [JSON](card_coverage.json)。", '',
             f"既有规则放行 **{s['rule_eligible_order_names_including_weather']} 个指令规则名**"
             f"（含 {s['weather_variants']} 个天气效果版本），本轮新增放行 **0**。", '',
             '## 如何阅读', '',
             '- `eligible` 仅指默认规则可选；当前费用、橙色、身份、合法目标、前台与动作后验仍须通过。',
             '- `conditional` 的天气纯名称不可出，必须解析效果版本；不要把天气家族与版本重复当成全卡数量。',
             '- `disabled` 表示现行规则禁用；`unreviewed` 表示规则尚未核定，不等同仅缺拖拽实现。',
             '- 基础费用/攻防/阵营来自 `json`，不是当前战场状态；不得用基础属性假算斩杀或交换。',
             '- `strategy_evaluation`、`per_card_live_evidence` 均为 `not_indexed`：尚无逐卡可追溯索引，'
             '不表示历史实机从未用过。既有场次证据仍见 PC 报告，不能用规则放行替代。',
             '- 单位通用部署路径也不能证明其所有部署效果、选目标、关键词和特殊机制已适配。', '',
             '## 当前执行路径', '', '| 路径 | 记录数 |', '|---|---:|']
    lines += [f'| {key} | {n} |' for key, n in s['execution_routes'].items()]
    lines += ['', '## 本轮明确的待办', '',
              '- 征服、美国陆军航空队：中英文均未要求玩家指定目标，可复用 direct 手势；'
              '但空抽、手牌容量和收益条件未验证，维持不放行。',
              '- 暂避锋芒/装甲楔形阵：需当前单位身份、阵营、类型及费用限制，不用基础卡库字段猜当前合法性。',
              '- 二步/手牌选择/限定目标/提前结束回合指令继续逐张审查；不批量改为 direct。',
              '- 现行固定优先级没有完整攻防交换评估；当前属性、关键词和持续效果采集是前置缺口。', '',
              '## 逐卡索引', '', '| cardId | 卡名 | 类型 | 基础费 | 规则 | 路径 | 说明 |', '|---|---|---|---:|---|---|---|']
    for r in data['cards']:
        lines.append('| ' + ' | '.join(cell(r[k]) for k in (
            'cardId', 'name', 'type', 'base_cost', 'rule_policy', 'execution_route', 'rationale')) + ' |')
    return '\n'.join(lines) + '\n'


def outputs(data: dict) -> dict[Path, str]:
    return {JSON_OUT: json.dumps(data, ensure_ascii=False, indent=2) + '\n', DOC_OUT: render(data)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--write', action='store_true')
    mode.add_argument('--check', action='store_true')
    args = ap.parse_args()
    data = build_inventory()
    if args.write:
        for path, text in outputs(data).items():
            path.write_text(text, encoding='utf-8')
    if args.check:
        for path, text in outputs(data).items():
            if not path.exists() or path.read_text(encoding='utf-8') != text:
                print(f'Outdated: {path.relative_to(ROOT)}')
                return 1
    print(json.dumps(data['summary'], ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
