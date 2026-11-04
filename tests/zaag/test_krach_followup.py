from __future__ import annotations
import unittest
import numpy as np
from zaaggenz_zaag import (FAMILIES,PRODUCTION_PRESET_IDS,krach_candidates,product_preset_catalogue,
    render_family_source,build_krach_audition_pack,family_demo_manifest,krach_loop_manifest,render_arrangement)

class KrachFollowupTests(unittest.TestCase):
    def test_four_krach_candidates_are_audition_only_and_not_product_presets(self):
        rows=krach_candidates();self.assertEqual(len(rows),4)
        ids={x.id for x in rows}
        self.assertEqual(ids,{
            'zaag.krach-black-mass','zaag.krach-dark-bounce',
            'zaag.krach-mid-shred','zaag.krach-air-teeth'})
        self.assertTrue(all(x.classification=='krach-candidate' for x in rows))
        self.assertTrue(ids.isdisjoint(PRODUCTION_PRESET_IDS))
        catalogue=product_preset_catalogue()
        self.assertEqual(catalogue['default'],'locked_bloom')
        self.assertTrue(ids.isdisjoint({x['id'] for x in catalogue['presets']}))
        self.assertEqual(len(FAMILIES),13)

    def test_four_mechanisms_render_deterministically_and_are_not_degenerate(self):
        rendered=[]
        for recipe in krach_candidates():
            a=render_family_source(recipe,12000);b=render_family_source(recipe,12000)
            np.testing.assert_array_equal(a.audio,b.audio);rendered.append(a)
        self.assertEqual({x.diagnostics['character_profile'] for x in rendered},
            {'krach-black-mass','krach-dark-bounce','krach-mid-shred','krach-air-teeth'})
        self.assertEqual(len({x.diagnostics['output_pcm_sha256'] for x in rendered}),4)
        maximum=0.
        for i,left in enumerate(rendered):
            a=left.audio.astype(np.float64);a-=np.mean(a)
            for right in rendered[i+1:]:
                b=right.audio.astype(np.float64);b-=np.mean(b);n=min(len(a),len(b))
                denom=np.linalg.norm(a[:n])*np.linalg.norm(b[:n])
                corr=0. if denom==0 else abs(float(np.dot(a[:n],b[:n])/denom))
                maximum=max(maximum,corr)
        self.assertLess(maximum,.97)

    def test_krach_pack_is_exactly_four_pending_owner_items(self):
        pack=build_krach_audition_pack(12000,-14.)
        self.assertEqual(len(pack.items),4)
        self.assertEqual(pack.manifest['status'],'pending-owner')
        self.assertEqual(pack.manifest['audition_revision'],'zg022-krach-followup-232-v1')
        self.assertEqual(set(pack.manifest['candidate_intents']),{x.id for x in krach_candidates()})
        self.assertTrue(pack.manifest['existing_production_presets_unchanged'])
        self.assertIsNone(pack.manifest['new_default'])
        self.assertFalse(pack.manifest['owner_decisions'])
        self.assertTrue(all(x.peak<=.980001 for x in pack.items))

    def test_each_krach_candidate_has_identical_pattern_melodic_and_root_loop_evidence(self):
        for recipe in krach_candidates():
            melodic=family_demo_manifest(recipe.id,12000)
            loop=krach_loop_manifest(recipe.id,12000)
            self.assertEqual(melodic.bars,1);self.assertEqual(len(melodic.events),8)
            self.assertEqual(loop.bars,2);self.assertEqual(loop.bpm,190.)
            self.assertEqual(len(loop.events),16)
            self.assertTrue(all(row['degrees']==[0] for row in loop.events))
            a=render_arrangement(loop);b=render_arrangement(loop)
            np.testing.assert_array_equal(a.audio,b.audio)
            self.assertEqual(a.diagnostics['pcm_sha256'],b.diagnostics['pcm_sha256'])

if __name__=='__main__':unittest.main(verbosity=2)
