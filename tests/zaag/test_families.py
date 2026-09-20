from __future__ import annotations
import json,unittest
from pathlib import Path
import numpy as np
from zaaggenz_contracts.legacy import adapt_parameters
from zaaggenz_zaag import (LOCKED_BLOOM,FAMILIES,candidates,contrasts,registry_payload,registry_sha256,
    render_family_source,family_demo_manifest,example_manifests,render_arrangement,build_owner_audition_pack)

ROOT=Path(__file__).resolve().parents[2]

class ZaagFamilyTests(unittest.TestCase):
    def test_locked_bloom_anchor_matches_recovered_contract_and_is_not_reconstructed(self):
        baseline=json.loads((ROOT/'baseline/V1_2_1_CONTRACT.json').read_text())
        preset=baseline['preset_contracts']
        self.assertEqual(LOCKED_BLOOM.canonical_json_sha256,preset['locked_bloom_canonical_json_sha256'])
        self.assertEqual(LOCKED_BLOOM.invariants,preset['locked_bloom_invariants'])
        self.assertEqual(LOCKED_BLOOM.render_hashes['ci_12k'],baseline['renders']['ci_12k']['locked_bloom_one']['float32_sha256'])
        self.assertTrue(baseline['portability']['owner_listening_required_before_default_sound_change'])
        self.assertNotIn('synth_overrides',LOCKED_BLOOM.to_dict())

    def test_registry_has_six_candidates_three_controls_and_no_new_default(self):
        self.assertEqual(len(candidates()),6);self.assertEqual(len(contrasts()),3);self.assertEqual(len(FAMILIES),9)
        self.assertEqual(len({x.id for x in FAMILIES}),9);self.assertTrue(all(not x.approved_default for x in FAMILIES))
        payload=registry_payload();self.assertIsNone(payload['new_default']);self.assertTrue(payload['owner_approval_required'])
        self.assertEqual(len(registry_sha256()),64)

    def test_every_family_has_bounded_controls_range_policy_cost_and_limitations(self):
        for recipe in FAMILIES:
            adapt_parameters('synth',recipe.synth_overrides)
            self.assertTrue(recipe.tuning_guidance);self.assertTrue(recipe.limitations)
            self.assertLess(recipe.useful_pitch_range_hz[0],recipe.useful_pitch_range_hz[1])
            self.assertIn(recipe.expert.phase_policy,('source-derived','reset-event'))
            self.assertIn(recipe.expert.tail_policy,('preserve','truncate'))
            self.assertIn(recipe.expert.quality_cost,('low','medium','high'))
            self.assertTrue(all(0<=v<=1 for v in recipe.macros.to_dict().values()))

    def test_all_family_sources_render_deterministically_and_are_distinct(self):
        hashes=[]
        for recipe in FAMILIES:
            a=render_family_source(recipe,12000);b=render_family_source(recipe,12000)
            np.testing.assert_array_equal(a.audio,b.audio);self.assertEqual(a.diagnostics['normalization'],'none')
            self.assertEqual(a.diagnostics['recipe_sha256'],recipe.sha256);hashes.append(a.diagnostics['output_pcm_sha256'])
        self.assertEqual(len(set(hashes)),len(hashes))

    def test_replacement_candidates_use_six_distinct_character_profiles_and_are_not_waveform_degenerate(self):
        rendered=[render_family_source(recipe,12000) for recipe in candidates()]
        profiles=[x.diagnostics['character_profile'] for x in rendered]
        self.assertEqual(set(profiles),{'bark','snarl','chop','split','crush','rip'})
        maximum=0.
        for i,left in enumerate(rendered):
            a=left.audio.astype(np.float64);a-=np.mean(a)
            for right in rendered[i+1:]:
                b=right.audio.astype(np.float64);b-=np.mean(b);n=min(len(a),len(b))
                denom=np.linalg.norm(a[:n])*np.linalg.norm(b[:n])
                corr=0. if denom==0 else abs(float(np.dot(a[:n],b[:n])/denom))
                maximum=max(maximum,corr)
        self.assertLess(maximum,.97)

    def test_each_candidate_has_a_reproducible_melodic_demo(self):
        for recipe in candidates():
            manifest=family_demo_manifest(recipe.id,12000)
            self.assertEqual(manifest.bars,1);self.assertEqual(len(manifest.events),8)
            a=render_arrangement(manifest);b=render_arrangement(manifest)
            np.testing.assert_array_equal(a.audio,b.audio)

    def test_three_examples_reproduce_and_reuse_each_family_source_once(self):
        manifests=example_manifests(12000);self.assertEqual([x.bars for x in manifests],[1,4,16])
        for manifest in manifests:
            a=render_arrangement(manifest);b=render_arrangement(manifest)
            np.testing.assert_array_equal(a.audio,b.audio);self.assertEqual(a.diagnostics['pcm_sha256'],b.diagnostics['pcm_sha256'])
            self.assertTrue(all(v==1 for v in a.diagnostics['source_renders_per_family'].values()))
            self.assertEqual(a.diagnostics['source_policy'],'render-each-family-once-then-source-derived-pitch')
            self.assertEqual(a.diagnostics['normalization'],'none')
        self.assertEqual(len(manifests[1].events),32);self.assertEqual(len(manifests[2].events),64)

    def test_owner_audition_is_level_matched_multi_endpoint_and_pending(self):
        pack=build_owner_audition_pack(12000,-14.)
        self.assertEqual(len(pack.items),9);self.assertEqual(pack.manifest['status'],'pending-owner')
        self.assertEqual(pack.manifest['audition_revision'],'zg022-brutal-family-redesign-229-v1')
        self.assertEqual(set(pack.manifest['candidate_intents']),{x.id for x in candidates()})
        self.assertEqual({x['id'] for x in pack.manifest['endpoints']},{'bounce','melodic_identity','source_character','usefulness'})
        self.assertFalse(pack.manifest['anchor_audio_included']);self.assertTrue(pack.manifest['rejected_variants_retained_as_evidence'])
        self.assertIn('Explicit owner approval',pack.manifest['decision_policy'])
        self.assertTrue(all(item.peak<=.980001 for item in pack.items))
        self.assertEqual(len(pack.manifest['manifest_sha256']),64)

if __name__=='__main__':unittest.main(verbosity=2)
