from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
import hashlib,json,os,tempfile,threading,time
from pathlib import Path
from zaaggenz_contracts import digest, validate
from .project import ProjectError

INDEX_VERSION='1.0.0'
DEFAULT_MAX_ENTRIES=8192
DEFAULT_MAX_INDEX_BYTES=8*1024*1024
HARD_MAX_ENTRIES=65536
HARD_MAX_INDEX_BYTES=64*1024*1024
_MIN_INDEX_BYTES=len((json.dumps({'version':INDEX_VERSION,'clock':0,'entries':{}},sort_keys=True,separators=(',',':'))+'\n').encode('utf-8'))
_ROOT_LOCKS={}
_ROOT_LOCKS_GUARD=threading.Lock()

def _hex_sha(value):
    return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)

def _pcm_expected_bytes(asset):
    if asset['identity_domain']!='pcm-f32le-interleaved-v1': return None
    return asset['frame_count']*asset['channels']*4

def _validate_asset_payload(asset,payload,blob_sha256=None):
    """Verify exact bytes against every supported AudioAssetRef identity domain."""
    validate(asset,'AudioAssetRef')
    if not isinstance(payload,(bytes,bytearray)): raise ProjectError('artifact payload must be bytes')
    payload=bytes(payload)
    blob=hashlib.sha256(payload).hexdigest() if blob_sha256 is None else blob_sha256
    if not _hex_sha(blob): raise ProjectError('invalid artifact byte identity')
    domain=asset['identity_domain']
    if domain=='pcm-f32le-interleaved-v1':
        expected=_pcm_expected_bytes(asset)
        if len(payload)!=expected: raise ProjectError('PCM artifact byte length does not match AudioAssetRef')
        if asset['content_sha256']!=blob: raise ProjectError('PCM artifact bytes do not match AudioAssetRef')
    elif domain=='encoded-file-bytes-v1':
        if asset['content_sha256']!=blob: raise ProjectError('artifact bytes do not match AudioAssetRef')
    else:
        raise ProjectError('unsupported AudioAssetRef identity domain')
    return payload,blob

def _thread_lock(root):
    key=str(root.resolve())
    with _ROOT_LOCKS_GUARD:
        lock=_ROOT_LOCKS.get(key)
        if lock is None:
            lock=threading.RLock();_ROOT_LOCKS[key]=lock
        return lock

@contextmanager
def _process_lock(path):
    """Cross-platform advisory lock for cooperative cache users on one local root."""
    f=open(path,'a+b');acquired=False
    try:
        f.seek(0,os.SEEK_END)
        if f.tell()==0:
            f.write(b'\0');f.flush();os.fsync(f.fileno())
        f.seek(0)
        if os.name=='nt':
            import msvcrt
            while True:
                try:
                    msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1);break
                except OSError:
                    time.sleep(.01)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_EX)
        acquired=True;yield
    finally:
        try:
            if acquired:
                f.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(),fcntl.LOCK_UN)
        finally:
            f.close()

def cache_key(recipe_sha256,engine_sha256,product):
    if product not in ('synth','arrange','arrange_bass','bass'): raise ProjectError('invalid product')
    for x in (recipe_sha256,engine_sha256):
        if not _hex_sha(x): raise ProjectError('invalid SHA-256 identifier')
    return digest({'domain':'zaaggenz.artifact-cache-v1','recipe_sha256':recipe_sha256,
                   'engine_sha256':engine_sha256,'product':product})

class ArtifactCache:
    """Transactional local cache bounded by payload bytes, entry count and index metadata bytes."""
    def __init__(self,root,max_bytes=512*1024*1024,*,max_entries=DEFAULT_MAX_ENTRIES,max_index_bytes=DEFAULT_MAX_INDEX_BYTES):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        if type(max_bytes)is not int or not 0<=max_bytes<=64*1024**3: raise ProjectError('invalid cache bound')
        if type(max_entries)is not int or not 1<=max_entries<=HARD_MAX_ENTRIES: raise ProjectError('invalid cache entry bound')
        if type(max_index_bytes)is not int or not _MIN_INDEX_BYTES<=max_index_bytes<=HARD_MAX_INDEX_BYTES:
            raise ProjectError('invalid cache metadata bound')
        self.max_bytes=max_bytes;self.max_entries=max_entries;self.max_index_bytes=max_index_bytes
        self.index_path=self.root/'index.json';self.lock_path=self.root/'.cache.lock'
        self._thread_lock=_thread_lock(self.root);self.index=self._empty_index();self._load()
    @contextmanager
    def _locked(self):
        with self._thread_lock:
            with _process_lock(self.lock_path): yield
    def _empty_index(self): return {'version':INDEX_VERSION,'clock':0,'entries':{}}
    def _path(self,key):
        if not _hex_sha(key): raise ProjectError('invalid cache key')
        return self.root/(key+'.bin')
    def _index_payload(self,index):
        return (json.dumps(index,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
    def _entry_metadata_bytes(self,key,entry):
        key_bytes=json.dumps(key,separators=(',',':')).encode('utf-8')
        entry_bytes=json.dumps(entry,sort_keys=True,separators=(',',':')).encode('utf-8')
        return len(key_bytes)+1+len(entry_bytes)
    def _index_size(self,index):
        empty={'version':index['version'],'clock':index['clock'],'entries':{}}
        size=len(self._index_payload(empty));entries=index['entries']
        if entries:
            size+=sum(self._entry_metadata_bytes(key,entry) for key,entry in entries.items())+len(entries)-1
        return size
    def _read_index(self):
        if not self.index_path.exists(): return self._empty_index()
        try:
            with self.index_path.open('rb') as f:
                raw=f.read(HARD_MAX_INDEX_BYTES+1)
        except OSError as e:
            raise ProjectError('cannot read cache index') from e
        if len(raw)>HARD_MAX_INDEX_BYTES:
            raise ProjectError('cache index exceeds hard metadata safety bound')
        try:d=json.loads(raw.decode('utf-8'))
        except (json.JSONDecodeError,UnicodeError,ValueError) as e: raise ProjectError('invalid cache index') from e
        if type(d) is not dict or set(d)!={'version','clock','entries'} or d['version']!=INDEX_VERSION or type(d['clock'])is not int or d['clock']<0 or type(d['entries']) is not dict:
            raise ProjectError('unsupported cache index')
        if len(d['entries'])>HARD_MAX_ENTRIES: raise ProjectError('cache index exceeds hard entry safety bound')
        for key,e in d['entries'].items():
            if not _hex_sha(key) or type(e)is not dict or set(e)!={'bytes','blob_sha256','access','asset'}:
                raise ProjectError('invalid cache entry')
            if type(e['bytes'])is not int or e['bytes']<0 or not _hex_sha(e['blob_sha256']) or type(e['access'])is not int or e['access']<0:
                raise ProjectError('invalid cache entry metadata')
            try: validate(e['asset'],'AudioAssetRef')
            except Exception as exc: raise ProjectError('invalid cached AudioAssetRef') from exc
            if e['asset']['content_sha256']!=e['blob_sha256']:
                raise ProjectError('cached artifact identity metadata mismatch')
            expected=_pcm_expected_bytes(e['asset'])
            if expected is not None and e['bytes']!=expected:
                raise ProjectError('cached PCM byte length does not match AudioAssetRef')
            if not self._path(key).is_file(): raise ProjectError('cache index points to missing artifact')
        return d
    def _is_stale_temp(self,path):
        name=path.name
        if name=='index.tmp': return True
        if name.startswith('index.json.') and name.endswith('.tmp'): return True
        if name.endswith('.tmp') and _hex_sha(name[:-4]): return True
        if name.endswith('.tmp') and '.bin.' in name:
            return _hex_sha(name.split('.bin.',1)[0])
        return False
    def _cleanup_stale_temps(self):
        for path in self.root.iterdir():
            if path.is_file() and self._is_stale_temp(path):
                try:path.unlink()
                except OSError as exc: raise ProjectError('cannot reconcile stale cache temporary file') from exc
    def _cleanup_orphans(self,index):
        keep=set(index['entries'])
        for path in self.root.glob('*.bin'):
            key=path.name[:-4]
            if _hex_sha(key) and key not in keep:
                try:path.unlink()
                except FileNotFoundError:pass
                except OSError as exc: raise ProjectError('cannot reconcile orphan cache artifact') from exc
    def _fsync_root(self):
        if os.name=='nt': return
        try:
            fd=os.open(self.root,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
        except OSError:pass
    def _write_temp(self,prefix,payload):
        fd,tmp=tempfile.mkstemp(prefix=prefix,suffix='.tmp',dir=self.root)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(payload);f.flush();os.fsync(f.fileno())
            return Path(tmp)
        except Exception:
            try:os.close(fd)
            except OSError:pass
            try:os.unlink(tmp)
            except FileNotFoundError:pass
            raise
    def _publish_index(self,index):
        payload=self._index_payload(index)
        if len(payload)>self.max_index_bytes: raise ProjectError('cache index exceeds configured metadata bound')
        if len(payload)>HARD_MAX_INDEX_BYTES: raise ProjectError('cache index exceeds hard metadata safety bound')
        tmp=self._write_temp('index.json.',payload)
        try:os.replace(tmp,self.index_path);self._fsync_root()
        finally:
            try:tmp.unlink()
            except FileNotFoundError:pass
    def _publish_blob(self,key,payload):
        path=self._path(key);tmp=self._write_temp(key+'.bin.',payload)
        try:os.replace(tmp,path);self._fsync_root()
        finally:
            try:tmp.unlink()
            except FileNotFoundError:pass
    def _evicted(self,index):
        evicted=[];entries=index['entries'];total=sum(e['bytes'] for e in entries.values())
        metadata_size=self._index_size(index)
        ordered=sorted(entries,key=lambda k:(entries[k]['access'],k));pos=0
        while (total>self.max_bytes or len(entries)>self.max_entries or metadata_size>self.max_index_bytes) and entries:
            key=ordered[pos];pos+=1;e=entries.pop(key);total-=e['bytes'];evicted.append(key)
            metadata_size-=self._entry_metadata_bytes(key,e)
            if entries: metadata_size-=1
        if metadata_size>self.max_index_bytes:
            raise ProjectError('configured cache metadata bound cannot represent the cache index')
        return evicted
    def _cleanup_evicted(self,keys):
        for key in keys:
            try:self._path(key).unlink()
            except FileNotFoundError:pass
            except OSError:pass
    def _index_file_exceeds_configured_bound(self):
        if not self.index_path.exists(): return False
        try:return self.index_path.stat().st_size>self.max_index_bytes
        except OSError as exc: raise ProjectError('cannot stat cache index') from exc
    def _reconcile_index(self,index):
        candidate=deepcopy(index);evicted=self._evicted(candidate)
        republish=bool(evicted) or self._index_file_exceeds_configured_bound()
        if republish:
            self._publish_index(candidate);self._cleanup_evicted(evicted);return candidate
        return index
    def _load(self):
        with self._locked():
            self._cleanup_stale_temps();d=self._reconcile_index(self._read_index())
            self._cleanup_orphans(d);self.index=d
    def _verified_entry_payload(self,key,entry):
        path=self._path(key)
        if not path.is_file(): raise ProjectError('cache index points to missing artifact')
        payload=path.read_bytes();blob=hashlib.sha256(payload).hexdigest()
        if len(payload)!=entry['bytes'] or blob!=entry['blob_sha256']: raise ProjectError('cached artifact integrity failure')
        _validate_asset_payload(entry['asset'],payload,blob);return payload
    def put(self,key,payload,asset):
        self._path(key);payload,blob=_validate_asset_payload(asset,payload)
        with self._locked():
            current=self._reconcile_index(self._read_index());existing=current['entries'].get(key)
            if existing is not None:
                old_payload=self._verified_entry_payload(key,existing)
                if old_payload!=payload or existing['asset']!=asset:
                    self.index=current;raise ProjectError('cache key already bound to a different artifact')
                candidate=deepcopy(current);candidate['clock']+=1;candidate['entries'][key]['access']=candidate['clock']
                evicted=self._evicted(candidate);self._publish_index(candidate);self.index=candidate;self._cleanup_evicted(evicted);return key
            try:self._path(key).unlink()
            except FileNotFoundError:pass
            self._publish_blob(key,payload)
            candidate=deepcopy(current);candidate['clock']+=1
            candidate['entries'][key]={'bytes':len(payload),'blob_sha256':blob,'access':candidate['clock'],'asset':deepcopy(asset)}
            evicted=self._evicted(candidate)
            for live_key in candidate['entries']:
                if not self._path(live_key).is_file(): raise ProjectError('cache transaction would publish a missing artifact')
            self._publish_index(candidate);self.index=candidate;self._cleanup_evicted(evicted);return key
    def get(self,key):
        self._path(key)
        with self._locked():
            current=self._reconcile_index(self._read_index());entry=current['entries'].get(key)
            if entry is None:self.index=current;return None
            payload=self._verified_entry_payload(key,entry)
            candidate=deepcopy(current);candidate['clock']+=1;candidate['entries'][key]['access']=candidate['clock']
            evicted=self._evicted(candidate);self._publish_index(candidate);self.index=candidate;self._cleanup_evicted(evicted);return payload
    @property
    def bytes_used(self):
        with self._locked():
            self.index=self._reconcile_index(self._read_index());return sum(e['bytes'] for e in self.index['entries'].values())
    @property
    def entries_used(self):
        with self._locked():
            self.index=self._reconcile_index(self._read_index());return len(self.index['entries'])
    @property
    def index_bytes_used(self):
        with self._locked():
            self.index=self._reconcile_index(self._read_index());return self._index_size(self.index)
