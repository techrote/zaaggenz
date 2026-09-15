import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zaaggenz_project import ArtifactCache, ProjectError


def _asset(payload=b''):
    return {'kind':'AudioAssetRef','version':'1.0.0','content_sha256':hashlib.sha256(payload).hexdigest(),
            'identity_domain':'encoded-file-bytes-v1','sample_rate_hz':48000,'channels':1,
            'channel_layout':'mono','frame_count':1,'level_domain':'post_master','sample_policy':'unclamped_float'}


def _zero_pcm_asset():
    payload=b''
    return {'kind':'AudioAssetRef','version':'1.0.0','content_sha256':hashlib.sha256(payload).hexdigest(),
            'identity_domain':'pcm-f32le-interleaved-v1','sample_rate_hz':48000,'channels':1,
            'channel_layout':'mono','frame_count':0,'level_domain':'post_master','sample_policy':'unclamped_float'}


def _key(number):
    return f'{number:064x}'


class CacheMetadataBoundTests(unittest.TestCase):
    def test_zero_byte_artifacts_are_bounded_by_entry_count(self):
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,max_bytes=1,max_entries=3,max_index_bytes=4096);asset=_zero_pcm_asset()
            for i in range(1,7):c.put(_key(i),b'',asset)
            self.assertEqual(c.entries_used,3)
            self.assertLessEqual(c.index_bytes_used,4096)
            self.assertEqual(set(c.index['entries']),{_key(4),_key(5),_key(6)})
            self.assertEqual(len(list(Path(td).glob('*.bin'))),3)

    def test_exact_entry_boundary_and_lru_reopen_are_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,100,max_entries=3,max_index_bytes=4096)
            for i,payload in enumerate((b'a',b'b',b'c'),1):c.put(_key(i),payload,_asset(payload))
            self.assertEqual(c.entries_used,3)
            self.assertEqual(c.get(_key(1)),b'a')  # key 1 is now newest; key 2 is oldest.
            reopened=ArtifactCache(td,100,max_entries=2,max_index_bytes=4096)
            self.assertEqual(set(reopened.index['entries']),{_key(1),_key(3)})
            self.assertIsNone(reopened.get(_key(2)))
            self.assertEqual(reopened.get(_key(1)),b'a');self.assertEqual(reopened.get(_key(3)),b'c')

    def test_exact_index_byte_boundary_and_one_byte_under(self):
        with tempfile.TemporaryDirectory() as td:
            key=_key(1);c=ArtifactCache(td,100,max_entries=10,max_index_bytes=4096);c.put(key,b'a',_asset(b'a'))
            exact=c.index_bytes_used
            exact_fit=ArtifactCache(td,100,max_entries=10,max_index_bytes=exact)
            self.assertEqual(exact_fit.get(key),b'a')
            exact_after_touch=exact_fit.index_bytes_used
            if exact_after_touch!=exact:
                exact=exact_after_touch
            one_under=ArtifactCache(td,100,max_entries=10,max_index_bytes=exact-1)
            self.assertEqual(one_under.entries_used,0)
            self.assertIsNone(one_under.get(key));self.assertFalse(Path(td,key+'.bin').exists())

    def test_oversized_but_compactable_existing_index_is_canonicalized_on_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            key=_key(1);c=ArtifactCache(td,100,max_entries=10,max_index_bytes=4096);c.put(key,b'a',_asset(b'a'))
            index_path=Path(td,'index.json');doc=json.loads(index_path.read_text(encoding='utf-8'))
            canonical=(json.dumps(doc,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
            pretty=(json.dumps(doc,sort_keys=True,indent=8)+'\n').encode('utf-8')
            self.assertGreater(len(pretty),len(canonical));index_path.write_bytes(pretty)
            reopened=ArtifactCache(td,100,max_entries=10,max_index_bytes=len(canonical))
            self.assertEqual(reopened.get(key),b'a')
            self.assertLessEqual(index_path.stat().st_size,reopened.max_index_bytes)

    def test_hard_index_size_ceiling_rejects_before_json_parse(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td,'index.json').write_bytes(b'{' + b' ' * 64)
            with patch('zaaggenz_project.cache.HARD_MAX_INDEX_BYTES',64):
                with self.assertRaisesRegex(ProjectError,'hard metadata safety bound'):
                    ArtifactCache(td,100,max_entries=4,max_index_bytes=64)

    def test_configured_bounds_reject_bool_zero_and_hard_limit_overflow(self):
        with tempfile.TemporaryDirectory() as td:
            for kwargs in ({'max_entries':True},{'max_entries':0},{'max_entries':65537},
                           {'max_index_bytes':True},{'max_index_bytes':42},{'max_index_bytes':64*1024*1024+1}):
                with self.subTest(kwargs=kwargs):
                    with self.assertRaises(ProjectError):ArtifactCache(td,100,**kwargs)

    def test_payload_byte_eviction_still_precedes_no_identity_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,max_bytes=1,max_entries=10,max_index_bytes=4096)
            c.put(_key(1),b'a',_asset(b'a'));c.put(_key(2),b'b',_asset(b'b'))
            self.assertIsNone(c.get(_key(1)));self.assertEqual(c.get(_key(2)),b'b')
            self.assertEqual(c.index['entries'][_key(2)]['asset'],_asset(b'b'))


if __name__=='__main__':unittest.main(verbosity=2)
