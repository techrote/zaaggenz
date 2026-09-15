from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'app'))

from zaaggenz_contracts.legacy import freeze_legacy, thaw_legacy
from zaaggenz_project import Project, ProjectError, ArtifactCache, cache_key, load_project, save_project, recipe_diff
from uptempo_harmony.synth import PRESETS, synthesize_one


def recipe(**changes):
    p=PRESETS['locked_bloom'].to_dict();p.update(changes);return freeze_legacy(p)

class ProjectTests(unittest.TestCase):
    def test_roundtrip_identity_and_render(self):
        p=Project(recipe())
        before,_=synthesize_one(thaw_legacy(p.head_recipe)['synth'])
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'song.zaag.json';save_project(p,f);q=load_project(f)
        self.assertEqual(q.head,p.head);self.assertEqual(q.sha256,p.sha256);self.assertEqual(q.head_recipe.sha256,p.head_recipe.sha256)
        after,_=synthesize_one(thaw_legacy(q.head_recipe)['synth']);np.testing.assert_array_equal(before,after)
    def test_relevant_change_new_revision(self):
        p=Project(recipe());a=p.head;b=p.commit(recipe(drive_db=20));self.assertNotEqual(a,b);self.assertEqual(p.revision_count,2)
        self.assertIn('/source/params/drive_db',[x['path'] for x in recipe_diff(recipe(),recipe(drive_db=20))])
    def test_noop_commit_deduplicates(self):
        p=Project(recipe());a=p.head;self.assertEqual(a,p.commit(recipe()));self.assertEqual(p.revision_count,1)
    def test_audition_does_not_commit(self):
        p=Project(recipe());before=p.to_document();a=p.audition(recipe(f0_hz=50));self.assertEqual(a.base_revision_id,p.head);self.assertEqual(before,p.to_document())
        self.assertNotEqual(a.recipe_sha256,p.head_recipe.sha256)
    def test_bad_project_version(self):
        p=Project(recipe());d=p.to_document();d['format_version']='9.0.0'
        with self.assertRaises(ProjectError):Project.from_document(d)
    def test_hash_tamper(self):
        p=Project(recipe());d=p.to_document();d['revisions'][0]['recipe_sha256']='0'*64
        with self.assertRaises(ProjectError):Project.from_document(d)
    def test_revision_cycle(self):
        p=Project(recipe());d=p.to_document();d['revisions'][0]['parent']=d['head']
        with self.assertRaises(ProjectError):Project.from_document(d)
    def test_unknown_top_level(self):
        d=Project(recipe()).to_document();d['cwd']='C:/private'
        with self.assertRaises(ProjectError):Project.from_document(d)
    def test_save_has_no_local_path(self):
        p=Project(recipe());text=json.dumps(p.to_document());self.assertNotIn(str(Path.cwd()),text)

class CacheTests(unittest.TestCase):
    def asset(self,payload):
        return {'kind':'AudioAssetRef','version':'1.0.0','content_sha256':hashlib.sha256(payload).hexdigest(),
        'identity_domain':'encoded-file-bytes-v1','sample_rate_hz':48000,'channels':1,'channel_layout':'mono','frame_count':1,
        'level_domain':'post_master','sample_policy':'unclamped_float'}
    def pcm_asset(self,payload,frame_count,channels=1):
        return {'kind':'AudioAssetRef','version':'1.0.0','content_sha256':hashlib.sha256(payload).hexdigest(),
        'identity_domain':'pcm-f32le-interleaved-v1','sample_rate_hz':48000,'channels':channels,
        'channel_layout':'mono' if channels==1 else 'stereo-lr','frame_count':frame_count,
        'level_domain':'post_master','sample_policy':'unclamped_float'}
    def test_key_changes_with_recipe_engine_product(self):
        r='1'*64;e='2'*64
        self.assertEqual(cache_key(r,e,'synth'),cache_key(r,e,'synth'))
        self.assertNotEqual(cache_key(r,e,'synth'),cache_key('3'*64,e,'synth'))
        self.assertNotEqual(cache_key(r,e,'synth'),cache_key(r,'4'*64,'synth'))
        self.assertNotEqual(cache_key(r,e,'synth'),cache_key(r,e,'bass'))
    def test_key_rejects_nonhex_digest(self):
        with self.assertRaises(ProjectError):cache_key('g'*64,'2'*64,'synth')
    def test_bounded_eviction_and_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,max_bytes=6);k1='1'*64;k2='2'*64
            c.put(k1,b'abcd',self.asset(b'abcd'));c.put(k2,b'efgh',self.asset(b'efgh'))
            self.assertLessEqual(c.bytes_used,6);self.assertIsNone(c.get(k1));self.assertEqual(c.get(k2),b'efgh')
            (Path(td)/(k2+'.bin')).write_bytes(b'BAD!')
            with self.assertRaises(ProjectError):c.get(k2)
    def test_asset_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,100);a=self.asset(b'a')
            with self.assertRaises(ProjectError):c.put('a'*64,b'b',a)
    def test_pcm_asset_identity_and_shape(self):
        mono=np.asarray([0.25,-0.5],dtype='<f4').tobytes()
        stereo=np.asarray([[0.25,-0.25],[0.5,-0.5]],dtype='<f4').tobytes()
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,100)
            c.put('a'*64,mono,self.pcm_asset(mono,2,1))
            c.put('b'*64,stereo,self.pcm_asset(stereo,2,2))
            self.assertEqual(c.get('a'*64),mono)
            self.assertEqual(c.get('b'*64),stereo)
    def test_pcm_asset_hash_mismatch_fails(self):
        good=np.asarray([0.25],dtype='<f4').tobytes();bad=np.asarray([0.5],dtype='<f4').tobytes()
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,100);a=self.pcm_asset(good,1,1)
            with self.assertRaises(ProjectError):c.put('a'*64,bad,a)
            self.assertIsNone(c.get('a'*64))
    def test_pcm_asset_length_mismatch_fails_before_publication(self):
        pcm=np.asarray([0.25],dtype='<f4').tobytes()
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,100);a=self.pcm_asset(pcm,2,1)
            with self.assertRaises(ProjectError):c.put('a'*64,pcm,a)
            self.assertFalse((Path(td)/('a'*64+'.bin')).exists())
            self.assertNotIn('a'*64,c.index['entries'])
    def test_pcm_reopen_rejects_false_declared_identity(self):
        pcm=np.asarray([0.25,-0.5],dtype='<f4').tobytes();key='a'*64
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,100);c.put(key,pcm,self.pcm_asset(pcm,2,1))
            index_path=Path(td,'index.json');d=json.loads(index_path.read_text(encoding='utf-8'))
            d['entries'][key]['asset']['content_sha256']='0'*64
            index_path.write_text(json.dumps(d),encoding='utf-8')
            reopened=ArtifactCache(td,100)
            with self.assertRaises(ProjectError):reopened.get(key)
    def test_pcm_index_shape_mismatch_fails_on_load(self):
        pcm=np.asarray([0.25,-0.5],dtype='<f4').tobytes();key='a'*64
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,100);c.put(key,pcm,self.pcm_asset(pcm,2,1))
            index_path=Path(td,'index.json');d=json.loads(index_path.read_text(encoding='utf-8'))
            d['entries'][key]['asset']['frame_count']=1
            index_path.write_text(json.dumps(d),encoding='utf-8')
            with self.assertRaises(ProjectError):ArtifactCache(td,100)
    def test_put_owns_defensive_asset_copy(self):
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,100);a=self.asset(b'a');c.put('a'*64,b'a',a);a['frame_count']=999
            self.assertEqual(c.index['entries']['a'*64]['asset']['frame_count'],1)
            self.assertEqual(ArtifactCache(td,100).index['entries']['a'*64]['asset']['frame_count'],1)
    def test_corrupt_index_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td,'index.json').write_text('{"version":"1.0.0","clock":-1,"entries":{}}',encoding='utf-8')
            with self.assertRaises(ProjectError):ArtifactCache(td,100)
    def test_slot_persists_asset_identity_not_locator(self):
        p=Project(recipe());payload=b'wav';a=self.asset(payload);k=cache_key(p.head_recipe.sha256,'e'*64,'synth')
        p.bind_slot('SYN',revision_id=p.head,product='synth',cache_key=k,asset=a)
        q=Project.from_document(p.to_document());self.assertEqual(q.slot('SYN')['asset']['content_sha256'],a['content_sha256'])

if __name__=='__main__':unittest.main(verbosity=2)
