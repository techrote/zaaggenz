from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import os
import tempfile
from zaaggenz_contracts import Contract, ContractError, digest, loads, validate

FORMAT='zaaggenz-project'
VERSION='1.0.0'
MAX_REVISIONS=4096
MAX_SLOTS=32

class ProjectError(ValueError): pass

def _require(c,m):
    if not c: raise ProjectError(m)

def _revision_id(recipe_sha,parent):
    return digest({'domain':'zaaggenz.project-revision-v1','recipe_sha256':recipe_sha,'parent':parent})

@dataclass(frozen=True)
class Audition:
    base_revision_id: str
    recipe_sha256: str
    recipe_json: str

class Project:
    """Mutable editor container whose committed revision payloads are immutable JSON snapshots."""
    def __init__(self, initial_recipe: Contract):
        if not isinstance(initial_recipe,Contract) or initial_recipe.to_dict()['kind']!='RenderRecipe':
            raise ProjectError('RenderRecipe Contract required')
        self._revisions={}
        self._slots={}
        self._head=None
        self.commit(initial_recipe)

    @classmethod
    def _blank(cls):
        x=cls.__new__(cls);x._revisions={};x._slots={};x._head=None;return x

    @property
    def head(self): return self._head
    @property
    def head_recipe(self): return Contract.from_json(self._revisions[self._head]['recipe_json'])
    @property
    def revision_count(self): return len(self._revisions)

    def commit(self, recipe: Contract):
        if not isinstance(recipe,Contract) or recipe.to_dict()['kind']!='RenderRecipe':
            raise ProjectError('RenderRecipe Contract required')
        if len(self._revisions)>=MAX_REVISIONS: raise ProjectError('revision limit reached')
        recipe_sha=recipe.sha256
        if self._head and self._revisions[self._head]['recipe_sha256']==recipe_sha:
            return self._head
        parent=self._head
        rid=_revision_id(recipe_sha,parent)
        record={'id':rid,'parent':parent,'recipe_sha256':recipe_sha,'recipe_json':recipe.to_json()}
        existing=self._revisions.get(rid)
        if existing is not None and existing!=record: raise ProjectError('revision identity collision')
        self._revisions[rid]=record;self._head=rid;return rid

    def audition(self, recipe: Contract):
        if not isinstance(recipe,Contract) or recipe.to_dict()['kind']!='RenderRecipe':
            raise ProjectError('RenderRecipe Contract required')
        return Audition(self._head,recipe.sha256,recipe.to_json())

    def bind_slot(self,name,*,revision_id,product,cache_key,asset):
        if not isinstance(name,str) or not name or len(name)>64 or '/' in name or '\\' in name:
            raise ProjectError('invalid render slot name')
        if revision_id not in self._revisions: raise ProjectError('unknown revision')
        if product not in ('synth','arrange','arrange_bass','bass'): raise ProjectError('unknown render product')
        if not isinstance(cache_key,str) or len(cache_key)!=64: raise ProjectError('invalid cache key')
        try: validate(asset,'AudioAssetRef')
        except ContractError as e: raise ProjectError(str(e)) from e
        if len(self._slots)>=MAX_SLOTS and name not in self._slots: raise ProjectError('render slot limit reached')
        self._slots[name]={'revision_id':revision_id,'product':product,'cache_key':cache_key,'asset':deepcopy(asset)}

    def slot(self,name): return deepcopy(self._slots.get(name))

    def to_document(self):
        revisions=[]
        # Parent-before-child order, independent of dict insertion after load.
        seen=set();cur=self._head;chain=[]
        while cur is not None:
            if cur in seen: raise ProjectError('revision cycle')
            seen.add(cur);chain.append(cur);cur=self._revisions[cur]['parent']
        for rid in reversed(chain): revisions.append(deepcopy(self._revisions[rid]))
        _require(len(revisions)==len(self._revisions),'unreachable revision records')
        return {'format':FORMAT,'format_version':VERSION,'head':self._head,'revisions':revisions,
                'render_slots':deepcopy(dict(sorted(self._slots.items())))}

    @property
    def sha256(self): return digest(self.to_document())

    @classmethod
    def from_document(cls,doc):
        doc=migrate_document(doc)
        _validate_document(doc)
        p=cls._blank()
        for r in doc['revisions']:
            recipe=Contract.from_json(r['recipe_json'])
            _require(recipe.sha256==r['recipe_sha256'],'recipe hash mismatch')
            _require(_revision_id(r['recipe_sha256'],r['parent'])==r['id'],'revision hash mismatch')
            p._revisions[r['id']]=deepcopy(r)
        p._head=doc['head'];p._slots=deepcopy(doc['render_slots'])
        # Revalidate through canonical emitter to detect cycles/unreachable revisions.
        p.to_document()
        for slot in p._slots.values():
            _require(slot['revision_id'] in p._revisions,'slot references unknown revision')
            validate(slot['asset'],'AudioAssetRef')
        return p

def migrate_document(doc):
    if type(doc) is not dict: raise ProjectError('project root must be an object')
    if doc.get('format')!=FORMAT: raise ProjectError('not a zaaggenz project')
    version=doc.get('format_version')
    if version==VERSION: return deepcopy(doc)
    raise ProjectError(f'unsupported project format {version!r}; no silent migration is defined')

def _validate_document(doc):
    expected={'format','format_version','head','revisions','render_slots'}
    _require(set(doc)==expected,'project has missing/unknown top-level fields')
    _require(type(doc['head']) is str and len(doc['head'])==64,'invalid project head')
    _require(type(doc['revisions']) is list and 1<=len(doc['revisions'])<=MAX_REVISIONS,'invalid revision list')
    _require(type(doc['render_slots']) is dict and len(doc['render_slots'])<=MAX_SLOTS,'invalid render slots')
    ids=set()
    for r in doc['revisions']:
        _require(type(r) is dict and set(r)=={'id','parent','recipe_sha256','recipe_json'},'invalid revision record')
        _require(type(r['id']) is str and len(r['id'])==64 and r['id'] not in ids,'duplicate/invalid revision id')
        _require(r['parent'] is None or (type(r['parent']) is str and len(r['parent'])==64),'invalid parent id')
        _require(type(r['recipe_sha256']) is str and len(r['recipe_sha256'])==64,'invalid recipe hash')
        _require(type(r['recipe_json']) is str and len(r['recipe_json'].encode('utf-8'))<=2_000_000,'invalid recipe snapshot')
        ids.add(r['id'])
    _require(doc['head'] in ids,'head is missing')
    for name,s in doc['render_slots'].items():
        _require(type(name) is str and name and len(name)<=64 and '/' not in name and '\\' not in name,'invalid slot name')
        _require(type(s) is dict and set(s)=={'revision_id','product','cache_key','asset'},'invalid slot record')
        _require(s['revision_id'] in ids,'slot revision missing')
        _require(s['product'] in ('synth','arrange','arrange_bass','bass'),'invalid slot product')
        _require(type(s['cache_key']) is str and len(s['cache_key'])==64,'invalid slot cache key')

def load_project(path):
    path=Path(path)
    try:
        data=path.read_bytes()
        if len(data)>16_000_000: raise ProjectError('project file too large')
        return Project.from_document(loads(data))
    except (OSError,ContractError) as e: raise ProjectError(str(e)) from e

def save_project(project,path):
    if not isinstance(project,Project): raise ProjectError('Project required')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(project.to_document(),ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':'))+'\n'
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            f.write(text);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

def recipe_diff(a,b):
    a=a.to_dict() if isinstance(a,Contract) else deepcopy(a);b=b.to_dict() if isinstance(b,Contract) else deepcopy(b)
    validate(a,'RenderRecipe');validate(b,'RenderRecipe')
    out=[]
    def walk(x,y,path):
        if type(x)!=type(y): out.append({'path':path,'before':x,'after':y});return
        if type(x) is dict:
            for k in sorted(set(x)|set(y)):
                if k not in x or k not in y: out.append({'path':path+'/'+k,'before':x.get(k),'after':y.get(k)})
                else: walk(x[k],y[k],path+'/'+k)
        elif type(x) is list:
            if len(x)!=len(y): out.append({'path':path+'/length','before':len(x),'after':len(y)})
            for i,(vx,vy) in enumerate(zip(x,y)): walk(vx,vy,path+'/'+str(i))
        elif x!=y: out.append({'path':path or '/','before':x,'after':y})
    walk(a,b,'');return out
