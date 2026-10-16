"""Generated source proof, byte-cache invalidation and fixed-before regressions."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import cv2
import numpy as np
from . import effects


class EffectCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='kards-effect-proof-')
        self.root=Path(self.directory.name);effects._SOURCE_SHAPES.clear()

    def tearDown(self):
        effects._SOURCE_SHAPES.clear();self.directory.cleanup()

    def pair(self,kind):
        before_box=[20,75,60,80];front_box=[20,5,60,80];target_box=[110,10,60,80]
        pattern=np.random.default_rng(301).integers(30,220,(80,60,3),dtype=np.uint8)
        def card(box,row,side):
            return dict(card_box_estimate=list(box),card_edges_verified=True,row=row,side=side,type='infantry')
        rows=[]
        for index,elapsed in enumerate((1000,2000,2500,3000),1):
            frame=np.full((160,240,3),20,np.uint8);frame[0,0]=index
            cards=[]
            if kind=='move_front':
                box=before_box if index==1 else front_box
                x,y,w,h=box;frame[y:y+h,x:x+w]=pattern
                cards=[card(box,'our_support' if index==1 else 'front','our')]
            elif kind=='attack_unit':
                x,y,w,h=target_box;frame[y:y+h,x:x+w]=pattern
                frame[y+round(.78*h):y+round(.98*h),x+round(.70*w):x+round(.98*w)]=80 if index==1 else 120
                cards=[card(target_box,'front','enemy')]
            path=self.root/(kind+'-'+str(index)+'.png');raw=cv2.imencode('.png',frame)[1].tobytes();path.write_bytes(raw)
            rows.append(dict(source=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),shape=list(frame.shape),frame_id=index,elapsed_ms=elapsed),
                page=dict(state='battle' if index==1 else 'opponent_turn'),
                scene=dict(cards=cards,frontline=dict(owner='empty' if index==1 else 'our'),support_observed=0 if index==1 else 1),
                support_probe=dict(coverage_candidate=True,hq_box=[100,100,40,50],unknown_rectangles=[],unaccounted_edge_fraction=0.)))
        return dict(context=kind,reply=dict(accepted=True,completed=True),dispatch_elapsed_ms=1200,
            request=dict(frame_id=1,**{'from':[50,115],'to':[140,50] if kind=='attack_unit' else [50,45]}),observations=rows)

    def test_all_four_detectors_keep_three_frames_and_one_second(self):
        for kind in ('deploy','move_front','attack_unit','end_turn'):
            with self.subTest(kind=kind):
                pair=self.pair(kind)
                self.assertTrue(effects.sequence_postcondition(pair)['confirmed'])
                short=copy.deepcopy(pair);short['observations']=short['observations'][:3]
                self.assertFalse(effects.sequence_postcondition(short)['confirmed'])
                close=copy.deepcopy(pair);close['observations'][-1]['source']['elapsed_ms']=2999
                self.assertFalse(effects.sequence_postcondition(close)['confirmed'])
                for field in ('accepted','completed'):
                    bad=copy.deepcopy(pair);bad['reply'][field]=False
                    self.assertFalse(effects.sequence_postcondition(bad)['confirmed'])

    def test_artwork_detectors_share_one_hash_read_and_decode_per_source(self):
        for kind in ('move_front','attack_unit'):
            with self.subTest(kind=kind):
                pair=self.pair(kind);effects._SOURCE_SHAPES.clear()
                with mock.patch.object(Path,'read_bytes',autospec=True,side_effect=Path.read_bytes) as reads, \
                        mock.patch.object(effects,'_decode',wraps=effects._decode) as decodes, \
                        mock.patch.object(effects.hashlib,'sha256',wraps=hashlib.sha256) as hashes:
                    self.assertTrue(effects.sequence_postcondition(pair)['confirmed'])
                self.assertEqual(4,reads.call_count);self.assertEqual(4,hashes.call_count);self.assertEqual(4,decodes.call_count)

    def test_growing_deploy_history_rehashes_old_sources_without_redecoding_geometry(self):
        pair=self.pair('deploy')
        with mock.patch.object(Path,'read_bytes',autospec=True,side_effect=Path.read_bytes) as reads, \
                mock.patch.object(effects,'_decode',wraps=effects._decode) as decodes:
            for count in (2,3,4):
                current=dict(pair,observations=pair['observations'][:count])
                self.assertEqual(count==4,effects.sequence_postcondition(current)['confirmed'])
        self.assertEqual(9,reads.call_count);self.assertEqual(4,decodes.call_count)
        json.dumps(pair) # Caches must never leak arrays/bytes into saved evidence.

    def test_same_path_length_and_mtime_mutation_still_fails_original_hash(self):
        pair=self.pair('deploy');self.assertTrue(effects.sequence_postcondition(pair)['confirmed'])
        path=Path(pair['observations'][0]['source']['path']);before=path.stat();raw=bytearray(path.read_bytes());raw[-1]^=1
        path.write_bytes(raw);os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        with mock.patch.object(effects,'_decode',wraps=effects._decode) as decodes:
            result=effects.sequence_postcondition(pair)
        self.assertFalse(result['confirmed']);self.assertEqual('source_hash_mismatch',result['reason']);self.assertEqual(0,decodes.call_count)

    def test_source_alias_gets_its_own_hash_and_cannot_reuse_changed_bytes(self):
        pair=self.pair('deploy');self.assertTrue(effects.sequence_postcondition(pair)['confirmed'])
        alias=self.root/'alias.png';alias.write_bytes(Path(pair['observations'][0]['source']['path']).read_bytes())
        pair['observations'][0]['source']['path']=str(alias)
        self.assertTrue(effects.sequence_postcondition(pair)['confirmed'])
        raw=bytearray(alias.read_bytes());raw[-1]^=1;alias.write_bytes(raw)
        self.assertEqual('source_hash_mismatch',effects.sequence_postcondition(pair)['reason'])

    def test_wrong_source_path_alias_cannot_borrow_another_frames_hash(self):
        pair=self.pair('deploy');self.assertTrue(effects.sequence_postcondition(pair)['confirmed'])
        pair['observations'][1]['source']['path']=pair['observations'][0]['source']['path']
        self.assertEqual('source_hash_mismatch',effects.sequence_postcondition(pair)['reason'])

    def test_new_hash_at_same_path_is_decoded_and_new_shape_is_not_reused(self):
        pair=self.pair('deploy');self.assertTrue(effects.sequence_postcondition(pair)['confirmed'])
        source=pair['observations'][0]['source'];path=Path(source['path'])
        raw=cv2.imencode('.png',np.full((160,240,3),90,np.uint8))[1].tobytes();path.write_bytes(raw)
        source['sha256']=hashlib.sha256(raw).hexdigest()
        with mock.patch.object(effects,'_decode',wraps=effects._decode) as decodes:
            self.assertTrue(effects.sequence_postcondition(pair)['confirmed'])
        self.assertEqual(1,decodes.call_count)
        raw=cv2.imencode('.png',np.full((161,240,3),90,np.uint8))[1].tobytes();path.write_bytes(raw)
        source['sha256']=hashlib.sha256(raw).hexdigest()
        self.assertEqual('source_geometry_mismatch',effects.sequence_postcondition(pair)['reason'])

    def test_cached_actual_shape_cannot_be_overwritten_by_forged_metadata(self):
        pair=self.pair('deploy');self.assertTrue(effects.sequence_postcondition(pair)['confirmed'])
        for row in pair['observations']:row['source']['shape']=[160,241,3]
        with mock.patch.object(effects,'_decode',wraps=effects._decode) as decodes:
            result=effects.sequence_postcondition(pair)
        self.assertEqual('source_geometry_mismatch',result['reason']);self.assertEqual(0,decodes.call_count)

    def test_source_request_and_time_checks_still_run_on_shape_memo_hits(self):
        pair=self.pair('deploy');self.assertTrue(effects.sequence_postcondition(pair)['confirmed'])
        for change,reason in (('request','before_source_not_request_frame'),('time','source_time_not_increasing'),('dispatch','after_source_precedes_dispatch')):
            with self.subTest(change=change):
                bad=copy.deepcopy(pair)
                if change=='request':bad['request']['frame_id']=9
                elif change=='time':bad['observations'][2]['source']['elapsed_ms']=2000
                else:bad['observations'][1]['source']['elapsed_ms']=1100
                self.assertEqual(reason,effects.sequence_postcondition(bad)['reason'])

    def test_shape_memo_and_call_reader_memory_are_bounded(self):
        for number in range(effects._MAX_SOURCE_SHAPES+2):effects._remember_shape(str(number),(1,1,3))
        self.assertEqual(effects._MAX_SOURCE_SHAPES,len(effects._SOURCE_SHAPES));self.assertNotIn('0',effects._SOURCE_SHAPES)
        pair=self.pair('deploy')
        with mock.patch.object(effects,'_MAX_READER_BYTES',1024):
            reader=effects._SourceReader()
            self.assertIsNone(effects.validate_sources(pair,reader))
            self.assertLessEqual(reader.raw_bytes+reader.frame_bytes,1024)
            self.assertTrue(effects.sequence_postcondition(pair)['confirmed'])

    def test_fixed_before_missing_or_duplicate_actor_target_is_uncovered(self):
        for kind,reason in (('move_front','before_move_actor_not_unique'),('attack_unit','before_attack_target_not_unique')):
            for duplicate in (False,True):
                with self.subTest(kind=kind,duplicate=duplicate):
                    pair=self.pair(kind);cards=pair['observations'][0]['scene']['cards']
                    pair['observations'][0]['scene']['cards']=cards*2 if duplicate else []
                    result=effects.sequence_postcondition(pair)
                    self.assertEqual('uncovered',result['status']);self.assertEqual(reason,result['reason']);self.assertFalse(result['confirmed'])

    def test_fixed_before_support_coverage_count_or_full_row_is_uncovered(self):
        for change,reason in (('coverage','before_support_coverage_unconfirmed'),('count','before_support_count_unconfirmed'),('full','before_support_row_already_full')):
            with self.subTest(change=change):
                pair=self.pair('deploy');before=pair['observations'][0]
                if change=='coverage':before['support_probe']['coverage_candidate']=False
                elif change=='count':before['scene'].pop('support_observed')
                else:before['scene']['support_observed']=4
                result=effects.sequence_postcondition(pair)
                self.assertEqual('uncovered',result['status']);self.assertEqual(reason,result['reason']);self.assertFalse(result['confirmed'])

    def test_fixed_before_shortcut_does_not_override_invalid_source_or_receipt(self):
        pair=self.pair('deploy');pair['observations'][0]['support_probe']={}
        pair['observations'][1]['source']['sha256']='wrong'
        result=effects.sequence_postcondition(pair)
        self.assertEqual('unconfirmed',result['status']);self.assertEqual('source_hash_mismatch',result['reason'])
        pair['reply']['completed']=False
        self.assertEqual('no_completed_deploy_receipt',effects.sequence_postcondition(pair)['reason'])


def run():
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(EffectCacheTests);output=io.StringIO()
    result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
    return dict(passed=result.wasSuccessful(),tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                details=output.getvalue(),scope='generated_source_cache_and_sequence_proof',device_inputs=0,captures=0)


if __name__=='__main__':
    result=run();print(json.dumps(result,ensure_ascii=True));raise SystemExit(0 if result['passed'] else 1)
