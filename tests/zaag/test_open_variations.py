from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import hashlib
import json
import tempfile
import unittest
import wave
import numpy as np
from zaaggenz_zaag import open_variations as ov, krach_retry_v3 as v3, krach_presets as presets
from zaaggenz_zaag.registry import product_preset_catalogue, registry_sha256
from zaaggenz_timeline.model import (default_document, apply_source_preset, compile_recipe,
    TimelineDocument, source_preset_id, memory_estimate)
from zaaggenz_melody import render_phrase
from zaaggenz_melody.render import _production_preset_source
from zaaggenz_melody.model import MelodicRenderSpec
from zaaggenz_contracts.legacy import legacy_object
from zaaggenz_contracts import Contract
from zaaggenz_project import Project

GOLDEN_48K = (
    '8f2f7a00b695913355b88b5a2a3777df2a262e84ad619a395c299d8350508d03',
    '505581fa7834132e125d2444d721580cc93ac590d33a42ffaac97042c5523d6b',
    '2cb5c5801e2ac8f2484f8331d3484f2526e0120c028d5da4e17b991b2d5c4d6d',
    'f6342660fb8d4ce3e9e7706eee4cb850f595c080070806cb3dc0a239e861303e')


def doc_for(fid):
    doc = apply_source_preset(default_document(12000),fid).to_dict()
    doc.update(end_beat='4/1',next_id=1,notes=[dict(id='n-0',beat='0/1',duration_beats='1/1',
        degree=0,detune_cents=0.,gain_db=-18.,muted=False,roll_density=0)])
    return TimelineDocument(doc)


class OpenVariationTests(unittest.TestCase):
    def test_zero_depth_reconstructs_approved_open_exactly(self):
        for sr in (12000,48000):
            expected,_=v3.render_source(v3.RECIPES[0],sr)
            for recipe in ov.VARIANTS:
                actual,_=ov.render_source(replace(recipe,depth=0.),sr)
                np.testing.assert_array_equal(actual,expected)

    def test_four_deterministic_distinct_finite_variations(self):
        for sr in (12000,48000):
            hashes=[]
            for recipe in ov.VARIANTS:
                a,info=ov.render_source(recipe,sr)
                b,again=ov.render_source(recipe,sr)
                np.testing.assert_array_equal(a,b)
                self.assertEqual(info,again)
                self.assertTrue(np.isfinite(a).all())
                self.assertEqual((a[0],a[-1]),(0.,0.))
                self.assertEqual(len(a),round(sr*60/190*.97))
                self.assertFalse(info['whole_mix_distortion'])
                self.assertFalse(info['formant_resonators'])
                hashes.append(info['source_pcm_sha256'])
            self.assertEqual(len(set(hashes)),4)

    def test_bounds_and_bpm_endpoints(self):
        r=ov.VARIANTS[0]
        for kwargs in ({'depth':True},{'depth':float('nan')},{'depth':-1.},{'depth':1.01},{'profile':'unknown'},{'id':presets.IDS[0]}):
            with self.assertRaises(ValueError):replace(r,**kwargs)
        for sr in (True,48000.,44100,0):
            with self.assertRaises(ValueError):ov.render_source(r,sr)
        for bpm in (True,float('inf'),59.,261.):
            with self.assertRaises(ValueError):ov.render_source(r,bpm=bpm)
        for bpm in (60.,260.):
            a,_=ov.render_source(r,12000,bpm=bpm)
            self.assertEqual(len(a),round(12000*60/bpm*.97))

    def test_tiers_and_candidate_exclusion(self):
        rows=product_preset_catalogue()['presets']
        self.assertEqual(len(rows),11)
        self.assertEqual([r['tier'] for r in rows if r['id'] in presets.IDS],list(presets.TIERS))
        self.assertTrue(set(v.id for v in ov.VARIANTS).isdisjoint(r['id'] for r in rows))
        self.assertEqual(product_preset_catalogue()['default'],'locked_bloom')

    def test_approved_source_settings_and_pcm_remain_exact(self):
        before=registry_sha256()
        for sr in (12000,48000):
            for fid,recipe in zip(presets.IDS,v3.RECIPES):
                expected,info=v3.render_source(recipe,sr)
                p=presets.parameters(fid,sr,190.)
                self.assertEqual(p,info['source_parameters'])
                np.testing.assert_array_equal(presets.render(fid,p),expected)
        self.assertEqual(registry_sha256(),before)
        # Pin the renderer source rather than cross-platform floating-point hashes.
        raw=Path(v3.__file__).read_bytes().replace(b'\r\n',b'\n')
        self.assertEqual(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
                         '26c627d018933139b4d5272f3e3cb3d7f03b5cf0')

    def test_parameter_identity_mismatch_is_rejected(self):
        p=presets.parameters(presets.IDS[0],12000,190.)
        for key,value in [('drive_db',15.),('beats',2),('noise_level',.01)]:
            with self.assertRaises(ValueError):presets.validate_binding(presets.IDS[0],{**p,key:value})
        with self.assertRaises(ValueError):presets.parameters('zaag.krach-v3-missing')
        with patch.object(v3,'RECIPES',(replace(v3.RECIPES[0],upper=.2),*v3.RECIPES[1:])):
            with self.assertRaises(ValueError):presets.recipe_for(presets.IDS[0])

    def test_all_tiers_select_save_reopen_and_render(self):
        for fid in presets.IDS:
            doc=doc_for(fid)
            reopened=TimelineDocument.from_json(json.dumps(doc.to_dict()))
            self.assertEqual(source_preset_id(reopened),fid)
            self.assertEqual(reopened.revision_id,doc.revision_id)
            recipe=compile_recipe(reopened)
            rendered=render_phrase(recipe)
            self.assertEqual(rendered.diagnostics['source_preset_id'],fid)
            self.assertGreater(float(np.max(np.abs(rendered.mix))),0.)
            d=recipe.to_dict()
            source=_production_preset_source(d,legacy_object('synth',d['source']['params']),MelodicRenderSpec())
            expected,_=v3.render_source(presets.recipe_for(fid),12000,bpm=200.)
            np.testing.assert_array_equal(source,expected)

    def test_malformed_saved_source_rejected_before_render(self):
        d=doc_for(presets.IDS[0]).to_dict()
        project=Project.from_document(d['project'])
        base=project.head_recipe.to_dict();base['source']['params']['drive_db']+=1.
        project.commit(Contract(base));d['project']=project.to_document()
        with self.assertRaises(ValueError):TimelineDocument(d)
        with self.assertRaises(ValueError):apply_source_preset(default_document(12000),ov.VARIANTS[0].id)

    def test_oversampled_source_memory_is_reserved(self):
        recipe=compile_recipe(doc_for(presets.IDS[0]))
        d=recipe.to_dict();p=d['source']['params']
        source=int(np.ceil(p['sr']*60/p['bpm']*p['beat_fill']))
        self.assertGreater(memory_estimate(recipe),source*4096)

    def test_cancellation_checked_before_approved_source(self):
        from zaaggenz_jobs.model import JobContext,CancellationToken
        from zaaggenz_jobs import JobError
        token=CancellationToken();token.cancel()
        ctx=JobContext('cancel-test',token,lambda _:None)
        d=compile_recipe(doc_for(presets.IDS[0])).to_dict()
        with self.assertRaises(JobError),patch.object(presets,'render') as render:
            _production_preset_source(d,legacy_object('synth',d['source']['params']),MelodicRenderSpec(),ctx)
        render.assert_not_called()

    def test_same_restrained_score_for_every_source(self):
        expected=None
        for r in ov.VARIANTS:
            source,_=ov.render_source(r,12000)
            a,score=v3.render_phrase(source,12000,riff=True)
            if expected is None:expected=score
            self.assertEqual(score,expected)
            self.assertEqual(set(e[2] for e in score['events']),{0,-1,-5})

    def test_pack_hashes_pcm24_tiers_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'pack'
            m=ov.build_pack(out,12000)
            self.assertEqual(len(m['files']),17)
            self.assertFalse(m['new_candidates_approved'])
            for row in m['files']:
                path=out/row['path']
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),row['sha256'])
                with wave.open(str(path)) as wav:
                    self.assertEqual((wav.getframerate(),wav.getsampwidth(),wav.getnchannels()),(12000,3,1))
                    self.assertEqual(wav.getnframes(),row['frames'])
            self.assertEqual(len(list((out/'saved_presets/primary').glob('*.json'))),1)
            self.assertEqual(len(list((out/'saved_presets/secondary').glob('*.json'))),3)
            with self.assertRaises(ValueError):ov.build_pack(out,12000)


if __name__=='__main__':unittest.main(verbosity=2)
