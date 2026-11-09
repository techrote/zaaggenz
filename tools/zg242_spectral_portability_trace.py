"""MBR-004 Gate B: read-only, full-pipeline, source-matched cross-host trace.

Use immutable original ZG-009 artifact ZIPs on each host. Capture executes
normal TimelineDocument -> compile_recipe -> render_phrase; monkeypatches are
scoped to this synchronous call and restore the original DSP immediately.
Does not change a sonic policy or assert a waveform tolerance.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import platform
import struct
import sys
from unittest.mock import patch
import zipfile

import numpy as np
import scipy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

TRACE_VERSION = 'zg242-stage-local-portability-v1'
MAX_DECISIONS = 250_000


def decode_float32_wav(raw):
    """Strict dependency-free reader for original IEEE float WAV exports."""
    if len(raw)<12 or raw[:4]!=b'RIFF' or raw[8:12]!=b'WAVE':
        raise ValueError('RIFF/WAVE header required')
    total=struct.unpack_from('<I',raw,4)[0]+8
    if total>len(raw) or total<12 or total!=len(raw):
        raise ValueError('RIFF length mismatch')
    pos=12; fmt=None; samples=None
    while pos<total:
        if pos+8>total:raise ValueError('truncated WAV chunk header')
        tag,size=struct.unpack_from('<4sI',raw,pos);pos+=8
        if pos+size>total:raise ValueError('truncated WAV chunk data')
        chunk=memoryview(raw)[pos:pos+size]
        if tag==b'fmt ':
            if fmt is not None or size<16:raise ValueError('duplicate/short WAV fmt chunk')
            kind,channels,rate,byte_rate,align,bits=struct.unpack_from('<HHIIHH',chunk)
            if (kind!=3 or channels not in (1,2) or not 8000<=rate<=192000 or
                bits!=32 or align!=channels*4 or byte_rate!=rate*align):
                raise ValueError('unsupported non-IEEE-f32 WAV format')
            fmt=(channels,rate,align)
        elif tag==b'data':
            if samples is not None:raise ValueError('duplicate WAV data chunk')
            samples=bytes(chunk)
        pos+=size+(size&1)
    if fmt is None or samples is None:raise ValueError('missing WAV fmt/data')
    channels,rate,align=fmt
    if len(samples)%align:raise ValueError('partial WAV frame')
    result=np.frombuffer(samples,dtype='<f4').reshape(-1,channels).copy()
    if not np.isfinite(result).all():raise ValueError('non-finite WAV samples')
    return (result[:,0] if channels==1 else result),rate


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def pcm_identity(x):
    a=np.asarray(x)
    if not np.isfinite(a).all():
        raise ValueError('non-finite PCM cannot enter the provenance trace')
    f=np.ascontiguousarray(a,dtype='<f8')
    q=np.ascontiguousarray(a,dtype='<f4')
    return {'shape':list(a.shape),'f64le_sha256':digest_bytes(f.tobytes()),
            'f32le_sha256':digest_bytes(q.tobytes()),
            'rms':float(np.sqrt(np.mean(f*f))) if f.size else 0.,
            'peak':float(np.max(np.abs(f),initial=0.))}


def delta_metrics(a,b):
    a=np.asarray(a,dtype=np.float64)
    b=np.asarray(b,dtype=np.float64)
    if a.shape!=b.shape:raise ValueError('source-mismatched PCM dimensions')
    d=a-b
    return {'rms_fs':float(np.sqrt(np.mean(d*d))) if d.size else 0.,
            'peak_fs':float(np.max(np.abs(d),initial=0.)),
            'nonzero_samples':int(np.count_nonzero(d)),
            'samples':int(d.size)}


def _canonical(value):
    """Keep exact native float binary decisions for cross-host diagnostics."""
    if isinstance(value,(float,np.floating)):return float(value).hex()
    if isinstance(value,(int,np.integer)):return int(value)
    if isinstance(value,dict):return {str(k):_canonical(v) for k,v in sorted(value.items())}
    if isinstance(value,(tuple,list)):return [_canonical(v) for v in value]
    return value


def _frame_ledger(analysis):
    tracks=analysis.bundle.to_dict()['tracks']
    if sum(len(t['frames']) for t in tracks)>MAX_DECISIONS:
        raise ValueError('bounded spectral ledger exceeded')
    return [{'id':t['id'],'continuity':t['continuity'],
             'frames':[{'index':i,'anchor':r['support']['anchor_sample'],
                        'support':r['support'],'frequency_hz':float(r['frequency_hz']).hex(),
                        'confidence':float(r['confidence']).hex(),'action':r['action'],
                        'amplitudes':_canonical(r['amplitudes']),
                        'phases_radians':_canonical(r['phases_radians'])}
                       for i,r in enumerate(t['frames'])]}
            for t in tracks]


def _decisions(analysis,result):
    raw=result.plan.decisions if hasattr(result,'plan') else result.decisions
    source={(t['id'],i):r for t in analysis.bundle.to_dict()['tracks']
            for i,r in enumerate(t['frames'])}
    if len(raw)>MAX_DECISIONS:raise ValueError('bounded transform decision ledger exceeded')
    output=[]
    for decision in raw:
        d=decision.to_dict()
        frame=source[(d['track_id'],d['frame_index'])]
        output.append({'track_id':d['track_id'],'frame_index':d['frame_index'],
                       'support':frame['support'],'decision':_canonical(d)})
    return output


def _support_extent(spectral):
    supports=[d['support'] for d in spectral['decisions']
              if d['decision']['decision'] not in ('preserve',)]
    if not supports:return None
    return [min(s['start_sample'] for s in supports),max(s['end_sample'] for s in supports)]


