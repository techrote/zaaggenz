from __future__ import annotations
import hashlib
from pathlib import Path
from zaaggenz_contracts import loads

class ReferenceError(ValueError):pass

def _require(c,m):
    if not c:raise ReferenceError(m)

def load_registry(path):
    d=loads(Path(path).read_bytes());_require(type(d)is dict and set(d)=={'version','assets'},'invalid registry root');_require(d['version']=='1.0.0','unsupported registry version');_require(type(d['assets'])is list,'assets must be list')
    ids=set()
    for a in d['assets']:
        required={'id','sha256','bytes','filename_hint','native','rights','planning'}
        _require(type(a)is dict and set(a)==required,'invalid asset record');_require(a['id'] not in ids,'duplicate asset id');ids.add(a['id'])
        _require(type(a['sha256'])is str and len(a['sha256'])==64,'invalid asset hash');_require(type(a['bytes'])is int and a['bytes']>0,'invalid asset bytes')
        _require(a['rights'].get('redistribution')=='not-authorized-in-repository','reference redistribution status must be explicit')
    return d

def load_locators(path):
    d=loads(Path(path).read_bytes());_require(type(d)is dict and set(d)=={'version','paths'} and d['version']=='1.0.0' and type(d['paths'])is dict,'invalid locator file')
    for k,v in d['paths'].items():_require(type(k)is str and type(v)is str and v,'invalid locator entry')
    return d

def _sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def resolve_assets(registry,locators):
    paths=locators['paths'];out=[]
    for asset in registry['assets']:
        raw=paths.get(asset['id'])
        row={'id':asset['id'],'expected_sha256':asset['sha256'],'expected_bytes':asset['bytes'],'status':'missing','path':raw}
        if raw:
            p=Path(raw).expanduser()
            if p.is_file():
                row['observed_bytes']=p.stat().st_size;row['observed_sha256']=_sha(p)
                row['status']='ok' if row['observed_bytes']==asset['bytes'] and row['observed_sha256']==asset['sha256'] else 'identity-mismatch'
        out.append(row)
    return out

def require_exact_resolution(rows):
    bad=[r for r in rows if r['status']!='ok']
    if bad:raise ReferenceError('private references unresolved: '+', '.join(r['id']+':'+r['status'] for r in bad))
    return rows
