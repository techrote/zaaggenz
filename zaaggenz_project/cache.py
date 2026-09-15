from __future__ import annotations
from copy import deepcopy
import hashlib,json,os
from pathlib import Path
from zaaggenz_contracts import digest, validate
from .project import ProjectError

INDEX_VERSION='1.0.0'

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
        if len(payload)!=expected:
            raise ProjectError('PCM artifact byte length does not match AudioAssetRef')
        if asset['content_sha256']!=blob:
            raise ProjectError('PCM artifact bytes do not match AudioAssetRef')
    elif domain=='encoded-file-bytes-v1':
        if asset['content_sha256']!=blob:
            raise ProjectError('artifact bytes do not match AudioAssetRef')
    else:  # Shared contract validation should make this unreachable.
        raise ProjectError('unsupported AudioAssetRef identity domain')
    return payload,blob

def cache_key(recipe_sha256,engine_sha256,product):
    if product not in ('synth','arrange','arrange_bass','bass'): raise ProjectError('invalid product')
    for x in (recipe_sha256,engine_sha256):
        if not _hex_sha(x): raise ProjectError('invalid SHA-256 identifier')
    return digest({'domain':'zaaggenz.artifact-cache-v1','recipe_sha256':recipe_sha256,
                   'engine_sha256':engine_sha256,'product':product})

class ArtifactCache:
    """Local bounded byte cache. Locators never enter project/audio identity."""
    def __init__(self,root,max_bytes=512*1024*1024):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        if type(max_bytes)is not int or not 0<=max_bytes<=64*1024**3: raise ProjectError('invalid cache bound')
        self.max_bytes=max_bytes;self.index_path=self.root/'index.json';self._load()
    def _load(self):
        if not self.index_path.exists(): self.index={'version':INDEX_VERSION,'clock':0,'entries':{}};return
        try: d=json.loads(self.index_path.read_text(encoding='utf-8'))
        except (OSError,json.JSONDecodeError,UnicodeError) as e: raise ProjectError('invalid cache index') from e
        if type(d) is not dict or set(d)!={'version','clock','entries'} or d['version']!=INDEX_VERSION or type(d['clock'])is not int or d['clock']<0 or type(d['entries']) is not dict:
            raise ProjectError('unsupported cache index')
        for key,e in d['entries'].items():
            if not _hex_sha(key) or type(e)is not dict or set(e)!={'bytes','blob_sha256','access','asset'}:
                raise ProjectError('invalid cache entry')
            if type(e['bytes'])is not int or e['bytes']<0 or not _hex_sha(e['blob_sha256']) or type(e['access'])is not int or e['access']<0:
                raise ProjectError('invalid cache entry metadata')
            try: validate(e['asset'],'AudioAssetRef')
            except Exception as exc: raise ProjectError('invalid cached AudioAssetRef') from exc
            # Every supported domain hashes the exact cached bytes. This equality is
            # therefore an index-only invariant and can be checked without touching
            # the blob, including for pre-fix entries.
            if e['asset']['content_sha256']!=e['blob_sha256']:
                raise ProjectError('cached artifact identity metadata mismatch')
            expected=_pcm_expected_bytes(e['asset'])
            if expected is not None and e['bytes']!=expected:
                raise ProjectError('cached PCM byte length does not match AudioAssetRef')
        self.index=d
    def _save(self):
        tmp=self.index_path.with_suffix('.tmp');tmp.write_text(json.dumps(self.index,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8');os.replace(tmp,self.index_path)
    def _path(self,key):
        if not _hex_sha(key): raise ProjectError('invalid cache key')
        return self.root/(key+'.bin')
    def put(self,key,payload,asset):
        self._path(key)
        payload,blob=_validate_asset_payload(asset,payload)
        path=self._path(key);tmp=path.with_suffix('.tmp');tmp.write_bytes(payload);os.replace(tmp,path)
        self.index['clock']+=1;self.index['entries'][key]={'bytes':len(payload),'blob_sha256':blob,'access':self.index['clock'],'asset':deepcopy(asset)}
        self._evict();self._save();return key
    def get(self,key):
        self._path(key)
        entry=self.index['entries'].get(key)
        if entry is None:return None
        path=self._path(key)
        if not path.is_file(): raise ProjectError('cache index points to missing artifact')
        payload=path.read_bytes();blob=hashlib.sha256(payload).hexdigest()
        if len(payload)!=entry['bytes'] or blob!=entry['blob_sha256']:
            raise ProjectError('cached artifact integrity failure')
        _validate_asset_payload(entry['asset'],payload,blob)
        self.index['clock']+=1;entry['access']=self.index['clock'];self._save();return payload
    def _evict(self):
        total=sum(e['bytes'] for e in self.index['entries'].values())
        while total>self.max_bytes and self.index['entries']:
            key=min(self.index['entries'],key=lambda k:(self.index['entries'][k]['access'],k))
            e=self.index['entries'].pop(key);total-=e['bytes']
            try:self._path(key).unlink()
            except FileNotFoundError:pass
    @property
    def bytes_used(self):return sum(e['bytes'] for e in self.index['entries'].values())
