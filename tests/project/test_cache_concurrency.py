import hashlib
import json
import multiprocessing
from pathlib import Path
import tempfile
import threading
import unittest

from zaaggenz_project import ArtifactCache, ProjectError


def _asset(payload):
    return {'kind':'AudioAssetRef','version':'1.0.0','content_sha256':hashlib.sha256(payload).hexdigest(),
            'identity_domain':'encoded-file-bytes-v1','sample_rate_hz':48000,'channels':1,
            'channel_layout':'mono','frame_count':1,'level_domain':'post_master','sample_policy':'unclamped_float'}


def _process_put(root,key,payload,queue):
    try:
        ArtifactCache(root,4096).put(key,payload,_asset(payload));queue.put(None)
    except Exception as exc:  # pragma: no cover - reported to parent process
        queue.put(f'{type(exc).__name__}: {exc}')


class CacheConcurrencyTests(unittest.TestCase):
    def test_two_instances_threaded_puts_do_not_lose_updates(self):
        with tempfile.TemporaryDirectory() as td:
            a=ArtifactCache(td,4096);b=ArtifactCache(td,4096);barrier=threading.Barrier(3);errors=[]
            def put(cache,key,payload):
                try:barrier.wait();cache.put(key,payload,_asset(payload))
                except Exception as exc:errors.append(exc)
            threads=[threading.Thread(target=put,args=(a,'a'*64,b'alpha')),
                     threading.Thread(target=put,args=(b,'b'*64,b'beta'))]
            for t in threads:t.start()
            barrier.wait()
            for t in threads:t.join()
            self.assertEqual(errors,[])
            reopened=ArtifactCache(td,4096)
            self.assertEqual(reopened.get('a'*64),b'alpha');self.assertEqual(reopened.get('b'*64),b'beta')

    def test_process_lock_serializes_two_cache_instances(self):
        with tempfile.TemporaryDirectory() as td:
            ArtifactCache(td,4096)
            ctx=multiprocessing.get_context('spawn');queue=ctx.Queue()
            ps=[ctx.Process(target=_process_put,args=(td,'c'*64,b'gamma',queue)),
                ctx.Process(target=_process_put,args=(td,'d'*64,b'delta',queue))]
            for p in ps:p.start()
            for p in ps:
                p.join(20);self.assertEqual(p.exitcode,0)
            self.assertEqual([queue.get(timeout=5) for _ in ps],[None,None])
            reopened=ArtifactCache(td,4096)
            self.assertEqual(reopened.get('c'*64),b'gamma');self.assertEqual(reopened.get('d'*64),b'delta')

    def test_get_put_race_preserves_both_committed_entries(self):
        with tempfile.TemporaryDirectory() as td:
            a=ArtifactCache(td,4096);b=ArtifactCache(td,4096);a.put('a'*64,b'alpha',_asset(b'alpha'))
            barrier=threading.Barrier(3);errors=[]
            def reads():
                try:
                    barrier.wait()
                    for _ in range(32):self.assertEqual(a.get('a'*64),b'alpha')
                except Exception as exc:errors.append(exc)
            def writes():
                try:barrier.wait();b.put('b'*64,b'beta',_asset(b'beta'))
                except Exception as exc:errors.append(exc)
            ts=[threading.Thread(target=reads),threading.Thread(target=writes)]
            for t in ts:t.start()
            barrier.wait()
            for t in ts:t.join()
            self.assertEqual(errors,[]);reopened=ArtifactCache(td,4096)
            self.assertEqual(reopened.get('a'*64),b'alpha');self.assertEqual(reopened.get('b'*64),b'beta')

    def test_same_key_identical_is_idempotent_and_conflict_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            key='a'*64;a=ArtifactCache(td,4096);b=ArtifactCache(td,4096)
            a.put(key,b'alpha',_asset(b'alpha'));b.put(key,b'alpha',_asset(b'alpha'))
            with self.assertRaisesRegex(ProjectError,'already bound'):
                b.put(key,b'other',_asset(b'other'))
            reopened=ArtifactCache(td,4096);self.assertEqual(reopened.get(key),b'alpha')
            self.assertEqual(reopened.index['entries'][key]['asset'],_asset(b'alpha'))

    def test_pre_index_failure_leaves_only_recoverable_orphan(self):
        with tempfile.TemporaryDirectory() as td:
            key='a'*64;c=ArtifactCache(td,4096);original=c._publish_index
            def fail(_index):raise OSError('injected index publication failure')
            c._publish_index=fail
            with self.assertRaises(OSError):c.put(key,b'alpha',_asset(b'alpha'))
            self.assertTrue(Path(td,key+'.bin').is_file());self.assertFalse(Path(td,'index.json').exists())
            c._publish_index=original;reopened=ArtifactCache(td,4096)
            self.assertIsNone(reopened.get(key));self.assertFalse(Path(td,key+'.bin').exists())

    def test_post_index_pre_cleanup_failure_is_reconciled_as_orphan(self):
        with tempfile.TemporaryDirectory() as td:
            old='a'*64;new='b'*64;c=ArtifactCache(td,5);c.put(old,b'alpha',_asset(b'alpha'))
            original=c._cleanup_evicted;c._cleanup_evicted=lambda _keys:None
            c.put(new,b'bravo',_asset(b'bravo'))
            self.assertTrue(Path(td,old+'.bin').is_file());self.assertEqual(c.get(new),b'bravo')
            c._cleanup_evicted=original;reopened=ArtifactCache(td,5)
            self.assertFalse(Path(td,old+'.bin').exists());self.assertIsNone(reopened.get(old));self.assertEqual(reopened.get(new),b'bravo')

    def test_stale_temps_and_unindexed_blobs_are_recovered(self):
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,4096);c.put('a'*64,b'alpha',_asset(b'alpha'))
            Path(td,'index.tmp').write_text('stale',encoding='utf-8')
            Path(td,'index.json.deadbeef.tmp').write_text('stale',encoding='utf-8')
            Path(td,'c'*64+'.tmp').write_bytes(b'stale')
            Path(td,'d'*64+'.bin.deadbeef.tmp').write_bytes(b'stale')
            Path(td,'e'*64+'.bin').write_bytes(b'orphan')
            reopened=ArtifactCache(td,4096)
            self.assertEqual(reopened.get('a'*64),b'alpha')
            for name in ('index.tmp','index.json.deadbeef.tmp','c'*64+'.tmp','d'*64+'.bin.deadbeef.tmp','e'*64+'.bin'):
                self.assertFalse(Path(td,name).exists(),name)

    def test_missing_indexed_blob_fails_closed_without_rebinding(self):
        with tempfile.TemporaryDirectory() as td:
            key='a'*64;c=ArtifactCache(td,4096);c.put(key,b'alpha',_asset(b'alpha'));Path(td,key+'.bin').unlink()
            with self.assertRaisesRegex(ProjectError,'missing artifact'):ArtifactCache(td,4096)
            d=json.loads(Path(td,'index.json').read_text(encoding='utf-8'));self.assertIn(key,d['entries'])

    def test_reopen_reconciles_byte_bound_transactionally(self):
        with tempfile.TemporaryDirectory() as td:
            c=ArtifactCache(td,20);c.put('a'*64,b'aaaa',_asset(b'aaaa'));c.put('b'*64,b'bbbb',_asset(b'bbbb'))
            reopened=ArtifactCache(td,4)
            self.assertLessEqual(reopened.bytes_used,4);self.assertIsNone(reopened.get('a'*64));self.assertEqual(reopened.get('b'*64),b'bbbb')


if __name__=='__main__':unittest.main(verbosity=2)
