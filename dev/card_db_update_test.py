"""Current DB, permissions, conditional fees and old learned identities. No input."""
from pathlib import Path
import copy
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'dev')]
import card_match as cm
import orders
import update_card_db as updater
import hand_cost_filter as hcf
import hand_scanner_v2 as hs
import orange_first_test as orange_tests


class CardUpdate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=json.loads((ROOT/'card_db/kards_data.json').read_text(encoding='utf8'))
        cls.cards={r['cardId']:r for r in cls.db['cards']}
        cls.patch=json.loads(updater.PATCH.read_text(encoding='utf8'))
        cm.load_db()

    def test_reviewed_changes_and_all_names(self):
        self.assertEqual(len(self.cards),1646)
        self.assertEqual(len(cm._NAME_SET),1588)
        for name in cm._NAME_SET:
            self.assertEqual(cm.match_name(name),name)
        for row in self.patch['cards']:
            for key,value in row['fields'].items():
                self.assertEqual(updater.get_field(self.cards[row['cardId']]['json'],key),value['after'])
        for name,cid in [('第 30 步兵团','30_infantry_regiment'),('旧金山属团','30th_regiment'),
                         ('搜索第七联队','7th_recon'),('豹式坦克 A 型 防磁装甲型','panther_a_zimmerit'),('泥泞季','rasputitsa')]:
            self.assertEqual(cm.card_by_name(cm.match_name(name))['cardId'],cid)
        for cid in ('102nd_rifles','14_panzergrenadier','7th_brigade'):
            self.assertEqual(cm.card_by_name(self.cards[cid]['json']['title']['zh-Hans'])['cardId'],cid)

    def test_patches_are_idempotent_and_reject_unreviewed_changes(self):
        repeated=updater.build(self.db,self.patch)
        self.assertEqual(self.db,repeated)
        changed=copy.deepcopy(self.db)
        next(r for r in changed['cards'] if r['cardId']=='tupolev_tu2')['json']['kredits']=9
        with self.assertRaisesRegex(ValueError,'Unreviewed upstream'):
            updater.build(changed,self.patch)

    def test_rules_match_current_data_without_new_permissions(self):
        rules=json.loads((ROOT/'config/order_plays.json').read_text(encoding='utf8'))['cards']
        for cid,rule in rules.items():
            card=self.cards[cid]['json']
            self.assertEqual(rule['name'],card['title']['zh-Hans'])
            self.assertEqual(rule['cost'],card['kredits'])
            self.assertEqual(rule['text'],card.get('text',{}).get('zh-Hans',''))
        for name in ('为了帝国','诏令','虚妄之梦'):
            self.assertTrue(orders.is_direct(name))
        self.assertTrue(orders.is_three_order('苇原之魂'))
        self.assertFalse(orders.playable('order','暂避锋芒'))
        self.assertIn('友方德国',rules['tactical_retreat']['note'])
        self.assertFalse(orders.playable('order','巡洋舰侦察机'))
        self.assertTrue(orders.is_direct('特攻'))
        for cid in ('rasputitsa','corps_command','forward_base','ferocious_assault'):
            self.assertFalse(orders.playable('order',rules[cid]['name']))

    def test_renamed_legacy_hashes_do_not_reuse_a_different_card_name(self):
        with tempfile.TemporaryDirectory() as temp:
            hashes=cm.CardHashDB(str(Path(temp)/'hashes.json'))
            bits=np.zeros((16,16),dtype=bool)
            old=dict(hash=cm.hash_to_hex(bits),name='第 30 步兵团',type='infantry')
            hashes.entries=[old]
            self.assertEqual(hashes.lookup(bits),(None,None,None))
            self.assertEqual(hashes.entries,[old])  # old evidence is preserved
            self.assertTrue(hashes.learn(bits,'第 30 步兵团','infantry'))
            self.assertEqual(hashes.entries[-1]['cardId'],'30_infantry_regiment')
            self.assertEqual(hashes.lookup(bits)[0],'第 30 步兵团')
            hashes.entries=[dict(old,cardId='30th_regiment')]
            self.assertIsNone(hashes.lookup(bits)[0])

    def test_conditional_fee_two_is_allowed_but_old_three_and_zero_are_not(self):
        # Replay known orange geometry; only the identity reader is scripted.
        factory=orange_tests.OrangeFirst()
        for cost,expected in ((2,True),(5,True),(3,False),(1,False),(0,False)):
            scanner=factory.scanner([dict(name='突发交战',type='order',cost=5)])
            fan=dict(x=500,y=630,w=12,h=18,probe_x=528)
            large=dict(x=420,y=300,w=20,h=32,probe_x=452)
            with patch.object(hcf,'candidates',side_effect=[[fan],[large]]), \
                 patch.object(hcf,'read_candidate_cost',return_value=cost),patch.object(hs.time,'sleep'):
                result=scanner.scan_orange(5,first_only=True)
            self.assertEqual(bool(result),expected,cost)
            if result:self.assertEqual(result[0]['cost'],cost)


if __name__=='__main__':
    unittest.main(verbosity=2)
