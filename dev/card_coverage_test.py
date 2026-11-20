"""Per-card coverage integrity; in-memory only, no game or generated-file writes."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'dev')]
import card_coverage as coverage
import order_plan
import orders


class CoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = coverage.build_inventory()
        cls.rows = {r['cardId']: r for r in cls.data['cards']}
        cls.db = json.loads(coverage.DB.read_text(encoding='utf-8'))['cards']

    def test_all_card_ids_appear_once_and_runtime_matches(self):
        self.assertEqual(len(self.rows), 1646)
        self.assertEqual(set(self.rows), {c['cardId'] for c in self.db})
        for card in self.db:
            row, j = self.rows[card['cardId']], card['json']
            self.assertEqual(row['runtime_name_eligible'], orders.playable(j['type'], row['name']))
            for field, key in (('faction', 'faction'), ('base_attack', 'attack'), ('base_defense', 'defense')):
                self.assertEqual(row[field], j.get(key))

    def test_coverage_is_not_a_live_support_or_strategy_claim(self):
        for row in self.rows.values():
            self.assertEqual(row['per_card_live_evidence'], 'not_indexed')
            self.assertEqual(row['strategy_evaluation'], 'not_indexed')
        self.assertEqual(self.data['summary']['newly_enabled_cards'], 0)
        self.assertEqual(self.data['summary']['rule_eligible_order_names_including_weather'], 529)
        self.assertEqual(self.data['summary']['weather_variants'], 27)

    def test_draw_candidates_and_limited_targets_remain_disabled(self):
        for cid in ('conquest', 'usaaf'):
            row = self.rows[cid]
            self.assertTrue(row['review_candidate'])
            self.assertFalse(row['runtime_name_eligible'])
            self.assertTrue(row['text_zh'])
            self.assertTrue(row['text_en'])
        self.assertFalse(self.rows['tactical_retreat']['runtime_name_eligible'])
        self.assertIn('限定目标', self.rows['tactical_retreat']['rationale'])

    def test_weather_and_duplicate_identity_are_separate(self):
        weather = [r for r in self.rows.values() if r['execution_route'] == 'weather_variant_required']
        self.assertEqual(len(weather), 9)
        self.assertTrue(all(not r['runtime_name_eligible'] for r in weather))
        duplicates = [r for r in self.rows.values() if len(r['same_name_cardIds']) > 1]
        self.assertEqual(len(duplicates), 106)
        self.assertTrue(all('name_does_not_uniquely_identify_cardId' in r['information_gaps'] for r in duplicates))

    def test_order_generator_retains_exact_existing_permissions(self):
        built, _ = order_plan.build_plan()
        current = json.loads(coverage.PLAN.read_text(encoding='utf-8'))['cards']
        self.assertEqual(built, current)

    def test_outputs_are_deterministic_and_default_switches_required(self):
        self.assertEqual(coverage.outputs(self.data), coverage.outputs(coverage.build_inventory()))
        with patch.object(orders, 'PLAY_ORDERS', False):
            with self.assertRaises(ValueError):
                coverage.build_inventory()


if __name__ == '__main__':
    unittest.main(verbosity=2)
