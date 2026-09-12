from __future__ import annotations
import hashlib,re
from pathlib import Path
from zaaggenz_contracts import loads

class ReferenceError(ValueError):pass

def _require(c,m):
    if not c:raise ReferenceError(m)

def _sha_text(v):return type(v)is str and re.fullmatch(r'[0-9a-f]{64}',v) is not None

def load_registry(path):
    d=loads(Path(path).read_bytes());_require(type(d)is dict and set(d)=={'version','assets'},'invalid registry root');_require(d['version']=='1.0.0','unsupported registry version');_require(type(d['assets'])is list and len(d['assets'])<=256,'assets must be a bounded list')
    ids=set()
    for a in d['assets']:
        required={'id','sha256','bytes','filename_hint','native','rights','planning'}
        _require(type(a)is dict and set(a)==required,'invalid asset record')
        _require(type(a['id'])is str and re.fullmatch(r'[a-z][a-z0-9_.-]{0,63}',a['id']) is not None,'invalid asset id')
        _require(a['id'] not in ids,'duplicate asset id');ids.add(a['id'])
        _require(_sha_text(a['sha256']),'invalid asset hash');_require(type(a['bytes'])is int and a['bytes']>0,'invalid asset bytes')
        _require(type(a['filename_hint'])is str and 0<len(a['filename_hint'])<=512 and '\n' not in a['filename_hint'] and '\r' not in a['filename_hint'],'invalid filename hint')
        n=a['native'];_require(type(n)is dict and set(n)=={'sample_rate_hz','channels','codec'},'invalid native-format record')
        _require(type(n['sample_rate_hz'])is int and 8000<=n['sample_rate_hz']<=192000 and n['channels'] in (1,2) and type(n['codec'])is str and 0<len(n['codec'])<=32,'invalid native-format values')
        r=a['rights'];_require(type(r)is dict and set(r)=={'status','redistribution','note'},'invalid rights record')
        _require(r['redistribution']=='not-authorized-in-repository','reference redistribution status must be explicit')
        _require(type(r['status'])is str and type(r['note'])is str,'invalid rights text')
        p=a['planning'];required_plan={'decoded_24k_duration_s','sample_peak_24k','integrated_lufs','true_peak_dbtp','energetic_medians'}
        _require(type(p)is dict and set(p)==required_plan,'invalid planning record')
        _require(all(type(p[k])in (int,float) and type(p[k])is not bool for k in ('decoded_24k_duration_s','sample_peak_24k','integrated_lufs','true_peak_dbtp')),'invalid planning scalar')
        med=p['energetic_medians'];_require(type(med)is dict and set(med)=={'power_centroid_hz','power_flatness','crest_db'},'invalid planning medians')
        _require(all(type(v)in (int,float) and type(v)is not bool for v in med.values()),'invalid planning median scalar')
    return d

def load_locators(path):
    d=loads(Path(path).read_bytes());_require(type(d)is dict and set(d)=={'version','paths'} and d['version']=='1.0.0' and type(d['paths'])is dict and len(d['paths'])<=256,'invalid locator file')
    for k,v in d['paths'].items():_require(type(k)is str and re.fullmatch(r'[a-z][a-z0-9_.-]{0,63}',k) is not None and type(v)is str and 0<len(v)<=4096 and '\x00' not in v,'invalid locator entry')
    return d

def _sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def resolve_assets(registry,locators):
    known={a['id'] for a in registry['assets']};paths=locators['paths'];unknown=set(paths)-known
    _require(not unknown,'locator contains unknown asset ids: '+', '.join(sorted(unknown)))
    out=[]
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
