from __future__ import annotations
import hashlib,json,os
from pathlib import Path
from zaaggenz_contracts import digest, validate, ContractError
from .project import ProjectError

INDEX_VERSION='1.0.0'

def cache_key(recipe_sha256,engine_sha256,product):
    if product not in ('synth','arrange','arrange_bass','bass'): raise ProjectError('invalid product')
    for x in (recipe_sha256,engine_sha256):
        if not isinstance(x,str) or len(x)!=64: raise ProjectError('invalid SHA-256 identifier')
    return digest({'domain':'zaaggenz.artifact-cache-v1','recipe_sha256':recipe_sha256,
                   'engine_sha256':engine_sha256,'product':product})

class ArtifactCache:
    """Local bounded byte cache. Locators never enter project/audio identity."""
    def __init__(self,root,max_bytes=512*1024*1024):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        if not 0<=max_bytes<=64*1024**3: raise ProjectError('invalid cache bound')
        self.max_bytes=int(max_bytes);self.index_path=self.root/'index.json';self._load()
    def _load(self):
        if not self.index_path.exists(): self.index={'version':INDEX_VERSION,'clock':0,'entries':{}};return
        try: d=json.loads(self.index_path.read_text(encoding='utf-8'))
        except (OSError,json.JSONDecodeError) as e: raise ProjectError('invalid cache index') from e
        if type(d) is not dict or set(d)!={'version','clock','entries'} or d['version']!=INDEX_VERSION or type(d['entries']) is not dict:
            raise ProjectError('unsupported cache index')
        self.index=d
    def _save(self):
        tmp=self.index_path.with_suffix('.tmp');tmp.write_text(json.dumps(self.index,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8');os.replace(tmp,self.index_path)
    def _path(self,key):
        if not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef' for c in key): raise ProjectError('invalid cache key')
        return self.root/(key+'.bin')
    def put(self,key,payload,asset):
        self._path(key);validate(asset,'AudioAssetRef')
        if not isinstance(payload,(bytes,bytearray)): raise ProjectError('artifact payload must be bytes')
        payload=bytes(payload);blob=hashlib.sha256(payload).hexdigest()
        if asset['identity_domain']=='encoded-file-bytes-v1' and asset['content_sha256']!=blob:
            raise ProjectError('artifact bytes do not match AudioAssetRef')
        path=self._path(key);tmp=path.with_suffix('.tmp');tmp.write_bytes(payload);os.replace(tmp,path)
        self.index['clock']+=1;self.index['entries'][key]={'bytes':len(payload),'blob_sha256':blob,'access':self.index['clock'],'asset':asset}
        self._evict();self._save();return key
    def get(self,key):
        entry=self.index['entries'].get(key)
        if entry is None:return None
        path=self._path(key)
        if not path.is_file(): raise ProjectError('cache index points to missing artifact')
        payload=path.read_bytes()
        if len(payload)!=entry['bytes'] or hashlib.sha256(payload).hexdigest()!=entry['blob_sha256']:
            raise ProjectError('cached artifact integrity failure')
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
