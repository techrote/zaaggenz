from __future__ import annotations
from collections import OrderedDict
from zaaggenz_contracts import digest,validate
from .stft import STFTSpec,AnalysisError

def analysis_key(asset,spec,channel_policy='preserve-channels-v1',method='zg-multiresolution-features-v1'):
    validate(asset,'AudioAssetRef')
    if not isinstance(spec,STFTSpec):raise AnalysisError('STFTSpec required')
    if channel_policy not in ('preserve-channels-v1','mean-power-observation-v1'):raise AnalysisError('unknown channel policy')
    return digest({'domain':'zaaggenz.analysis-cache-v1','asset_sha256':asset['content_sha256'],
      'identity_domain':asset['identity_domain'],'sample_rate_hz':asset['sample_rate_hz'],'channels':asset['channels'],
      'method':method,'spec':spec.metadata(),'channel_policy':channel_policy})

class AnalysisCache:
    def __init__(self,max_entries=32):
        if type(max_entries)is not int or not 0<=max_entries<=1024:raise AnalysisError('invalid cache bound')
        self.max_entries=max_entries;self._items=OrderedDict()
    def get(self,key):
        value=self._items.pop(key,None)
        if value is not None:self._items[key]=value
        return value
    def put(self,key,value):
        if not isinstance(key,str) or len(key)!=64:raise AnalysisError('invalid analysis key')
        self._items.pop(key,None);self._items[key]=value
        while len(self._items)>self.max_entries:self._items.popitem(last=False)
    def clear(self):self._items.clear()
    def __len__(self):return len(self._items)
