import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'app'))

from zaaggenz_contracts.legacy import freeze_legacy
from zaaggenz_jobs.model import RenderArtifact
from zaaggenz_project import ArtifactCache, Project, ProjectError, cache_key
from uptempo_harmony.synth import PRESETS


def recipe():
    return freeze_legacy(PRESETS['locked_bloom'].to_dict())


def asset(payload,*,sample_rate=48000):
    return {'kind':'AudioAssetRef','version':'1.0.0','content_sha256':hashlib.sha256(payload).hexdigest(),
            'identity_domain':'encoded-file-bytes-v1','sample_rate_hz':sample_rate,'channels':1,
            'channel_layout':'mono','frame_count':1,'level_domain':'post_master','sample_policy':'unclamped_float'}


def artifact(project,payload=b'audio',*,recipe_sha=None,revision_id=None,product='synth',key=None,asset_value=None):
    return RenderArtifact(revision_id or project.head,recipe_sha or project.head_recipe.sha256,product,
                          key or cache_key(project.head_recipe.sha256,'e'*64,product),payload,
                          asset_value or asset(payload),{})


class SlotBindingIssue121Tests(unittest.TestCase):
    def test_raw_binding_and_load_reject_non_cache_usable_keys(self):
        p=Project(recipe());a=asset(b'audio')
        for bad in ('g'*64,'A'*64,'a'*63,'a'*65,64):
            with self.subTest(key=bad):
                with self.assertRaises(ProjectError):
                    p.bind_slot('SYN',revision_id=p.head,product='synth',cache_key=bad,asset=a)
        good='a'*64
        p.bind_slot('SYN',revision_id=p.head,product='synth',cache_key=good,asset=a)
        self.assertEqual(Project.from_document(p.to_document()).slot('SYN')['cache_key'],good)
        for bad in ('g'*64,'A'*64):
            d=p.to_document();d['render_slots']['SYN']['cache_key']=bad
            with self.subTest(load_key=bad):
                with self.assertRaises(ProjectError):Project.from_document(d)

    def test_artifact_binding_roundtrips_one_identity_record(self):
        p=Project(recipe());r=artifact(p);p.bind_artifact_slot('SYN',r)
        expected={'revision_id':r.revision_id,'product':r.product,'cache_key':r.cache_key,'asset':r.asset}
        self.assertEqual(p.slot('SYN'),expected)
        self.assertEqual(Project.from_document(p.to_document()).slot('SYN'),expected)

    def test_artifact_binding_rejects_revision_recipe_and_product_mismatch_without_mutation(self):
        p=Project(recipe());before=p.to_document()
        bad=[artifact(p,recipe_sha='f'*64),artifact(p,revision_id='f'*64),artifact(p,product='preview',key='a'*64)]
        for r in bad:
            with self.subTest(product=r.product,revision=r.revision_id):
                with self.assertRaises(ProjectError):p.bind_artifact_slot('SYN',r)
                self.assertEqual(p.to_document(),before)
        with self.assertRaises(ProjectError):p.bind_artifact_slot('SYN',object())
        self.assertEqual(p.to_document(),before)

    def test_cache_backed_artifact_binding_verifies_bytes_and_asset_before_project_mutation(self):
        p=Project(recipe());r=artifact(p);before=p.to_document()
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,1024);c.put(r.cache_key,r.audio_bytes,r.asset)
            p.bind_artifact_slot('SYN',r,cache=c)
            self.assertEqual(p.verify_slot('SYN',c),r.audio_bytes)
        self.assertNotEqual(before,p.to_document())

        p2=Project(recipe());r2=artifact(p2);before2=p2.to_document()
        conflicting=asset(r2.audio_bytes,sample_rate=44100)
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,1024);c.put(r2.cache_key,r2.audio_bytes,conflicting)
            with self.assertRaises(ProjectError):p2.bind_artifact_slot('SYN',r2,cache=c)
            self.assertEqual(p2.to_document(),before2)

    def test_cache_absent_and_present_semantics_are_explicit(self):
        p=Project(recipe());r=artifact(p);p.bind_artifact_slot('SYN',r)
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,1024)
            with self.assertRaisesRegex(ProjectError,'absent'):
                p.verify_slot('SYN',c)
            c.put(r.cache_key,r.audio_bytes,r.asset)
            self.assertEqual(p.verify_slot('SYN',c),r.audio_bytes)
        self.assertEqual(Project.from_document(p.to_document()).slot('SYN')['cache_key'],r.cache_key)

    def test_structural_bind_with_cache_rejects_mismatched_asset(self):
        p=Project(recipe());payload=b'audio';key='b'*64;declared=asset(payload);different=asset(payload,sample_rate=44100)
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,1024);c.put(key,payload,different)
            with self.assertRaises(ProjectError):
                p.bind_slot('SYN',revision_id=p.head,product='synth',cache_key=key,asset=declared,cache=c)
            self.assertIsNone(p.slot('SYN'))

    def test_structural_bind_with_cache_requires_present_key_and_preserves_slot_on_failure(self):
        p=Project(recipe());payload=b'audio';a=asset(payload);good='c'*64
        p.bind_slot('SYN',revision_id=p.head,product='synth',cache_key=good,asset=a)
        before=p.slot('SYN')
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,1024)
            with self.assertRaisesRegex(ProjectError,'absent'):
                p.bind_slot('SYN',revision_id=p.head,product='synth',cache_key='d'*64,asset=a,cache=c)
        self.assertEqual(p.slot('SYN'),before)


if __name__=='__main__':unittest.main(verbosity=2)
