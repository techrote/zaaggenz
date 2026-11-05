"""NYQ-004 proof WAV files bind actual controlled event PCM and reproducible metadata."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile

from tools.nyq004_proof_pack import PACK_VERSION, RATE, generate_pack


class Nyq004ProofPackTests(unittest.TestCase):
    def test_pack_is_source_bound_complete_and_byte_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp)/'one', Path(tmp)/'two'
            first = generate_pack(a)
            second = generate_pack(b)
            self.assertEqual(first, second)
            self.assertEqual(first['format'], PACK_VERSION)
            self.assertEqual(len(first['cases']), 8)
            self.assertIn('NOT Compose/export qualified', first['scope'])
            self.assertEqual(
                (a/'manifest.json').read_bytes(), (b/'manifest.json').read_bytes())
            paths = sorted(x.name for x in a.iterdir())
            self.assertEqual(len(paths), 9)
            self.assertEqual(paths, sorted(x.name for x in b.iterdir()))
            pids = set()
            ledgers = set()
            for case in first['cases']:
                file = case['file']
                self.assertEqual((a/file).read_bytes(), (b/file).read_bytes())
                rate, audio = wavfile.read(a/file)
                self.assertEqual(rate, RATE)
                self.assertEqual(audio.shape, (RATE,))
                self.assertEqual(audio.dtype, np.float32)
                self.assertTrue(np.isfinite(audio).all())
                import hashlib
                self.assertEqual(hashlib.sha256(audio.tobytes()).hexdigest(),
                                 case['pcm_sha256'])
                self.assertEqual(hashlib.sha256((a/file).read_bytes()).hexdigest(),
                                 case['wav_sha256'])
                if case['sonic_spec'] is None:
                    self.assertIsNone(case['diagnostics'])
                else:
                    self.assertFalse(case['diagnostics']['product_rack_export_qualified'])
                    self.assertEqual(case['diagnostics']['source_asset_sha256'],
                                     first['source_asset_sha256'])
                    self.assertEqual(case['diagnostics']['sonic_sha256'],
                                     __import__('zaaggenz_contracts.nyquismic',
                                                fromlist=['SonicSpec']).SonicSpec.from_dict(
                                                case['sonic_spec']).sonic_sha256)
                    pids.add(case['pcm_sha256'])
                    ledgers.add(case['diagnostics']['event_ledger_sha256'])
            derived = first['cases'][-2]
            self.assertEqual(derived['file'], '06_input_rms.wav')
            control = derived['control_provenance']
            self.assertFalse(control['graph_ancestry_verified'])
            self.assertEqual(control['declared_upstream_ids'], ['proof-input'])
            self.assertEqual(control['consumer_id'], 'proof-clock')
            self.assertEqual(control['policy']['source_sha256'],
                             first['cases'][0]['pcm_sha256'])
            self.assertEqual(control['compiler']['source_sha256'],
                             first['cases'][0]['pcm_sha256'])
            self.assertEqual(control['compiler']['windows'], 8)
            self.assertEqual(control['compiler']['lookahead_s'], '1/8')
            self.assertEqual(control['compiler']['route_sha256'],
                             __import__('zaaggenz_contracts.nyquismic',
                                        fromlist=['ModulationRoute']).ModulationRoute.from_dict(
                                            control['route']).sha256)
            self.assertEqual(derived['sonic_spec']['clock']['routes'][0],
                             control['route'])
            self.assertNotEqual(derived['pcm_sha256'],
                                first['cases'][1]['pcm_sha256'])
            transient = first['cases'][-1]
            self.assertEqual(transient['file'], '07_input_rms_rise.wav')
            tc = transient['control_provenance']
            self.assertFalse(tc['graph_ancestry_verified'])
            self.assertEqual(tc['consumer_id'], 'proof-transient-clock')
            self.assertEqual(tc['declared_upstream_ids'], ['proof-input'])
            self.assertEqual(tc['policy']['source']['source_sha256'],
                             first['cases'][0]['pcm_sha256'])
            self.assertEqual(tc['compiler']['windows'], 16)
            self.assertEqual(tc['compiler']['lookahead_s'], '1/16')
            self.assertEqual(tc['compiler']['policy_sha256'],
                             __import__('zaaggenz_contracts.nyquismic_transient',
                                        fromlist=['UpstreamTransientPolicy']).UpstreamTransientPolicy.from_dict(
                                            tc['policy']).sha256)
            self.assertEqual(tc['compiler']['route_sha256'],
                             __import__('zaaggenz_contracts.nyquismic',
                                        fromlist=['ModulationRoute']).ModulationRoute.from_dict(
                                            tc['route']).sha256)
            self.assertEqual(transient['sonic_spec']['clock']['routes'][0],
                             tc['route'])
            self.assertGreater(sum(p['value'] != '0/1' for p in tc['route']['points']), 1)
            self.assertNotEqual(transient['diagnostics']['event_ledger_sha256'],
                                derived['diagnostics']['event_ledger_sha256'])
            self.assertNotEqual(transient['pcm_sha256'], derived['pcm_sha256'])
            self.assertGreaterEqual(len(pids), 3)
            self.assertGreaterEqual(len(ledgers), 3)
            with self.assertRaises(FileExistsError):
                generate_pack(a)


if __name__ == '__main__':
    unittest.main()
