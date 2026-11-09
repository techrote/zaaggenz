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


def capture_document(document, *, expected_pcm=None, provenance=None, frozen_pre_rack=None):
    """Capture actual registered processing boundaries without modifying DSP.

    expected_pcm: independent original exported WAV.
    frozen_pre_rack: EXPLICIT counterfactual, not evidence of actual pre-rack PCM.
    """
    from zaaggenz_timeline.model import TimelineDocument, compile_recipe
    from zaaggenz_melody.render import render_phrase
    from zaaggenz_spectral import band_selective as bs
    from zaaggenz_spectral import rack_executor as rx
    from zaaggenz_dsp import band_router as br
    from zaaggenz_dsp.multiband import split_bands

    doc=TimelineDocument(document)
    recipe=compile_recipe(doc)
    trace={'trace_version':TRACE_VERSION,'source':provenance or {},
           'document_revision_id':doc.revision_id,
           'compiled_recipe_sha256':recipe.sha256,
           'rack_sha256':None,'source_pre_rack':None,'rack_output':None,
           'spectral':[],'stages':[],'bands':[],'projection':None,
           'environment':{'python':platform.python_version(),'platform':platform.platform(),
                          'numpy':np.__version__,'scipy':scipy.__version__,
                          'wav_decoder':'strict-riff-ieee754-f32le-v1'}}
    curr={'band':None,'analysis':None,'spectral':None}
    origin_analyse=bs.analyse_components
    origin_retune=bs.retune_components
    origin_chord=bs.apply_chordness
    origin_stage=rx.process_builtin_stage
    origin_route=rx.route_band_processors
    origin_execute=rx.execute_rack

    def analyse(*args,**kwargs):
        result=origin_analyse(*args,**kwargs)
        curr['analysis']=result
        return result

    def spectral_call(origin,*args,**kwargs):
        result=origin(*args,**kwargs)
        analysis=args[0]
        row={'band_index':curr['band'],'request':result.request.to_dict(),
             'analysis_input':pcm_identity(analysis.source),
             'analysis_diagnostics':analysis.diagnostics,
             'tracked':_frame_ledger(analysis),
             'decisions':_decisions(analysis,result),
             'diagnostics':result.diagnostics,
             'result_audio':pcm_identity(result.audio)}
        row['changed_support_extent']=_support_extent(row)
        trace['spectral'].append(row)
        curr['spectral']=len(trace['spectral'])-1
        return result

    def stage(audio,sr,name,spec,**kwargs):
        before=np.asarray(audio,dtype=np.float64)
        curr['spectral']=None
        processed,measured=origin_stage(audio,sr,name,spec,**kwargs)
        row={'band_index':curr['band'],'stage':name,'input':pcm_identity(before),
             'output':pcm_identity(processed),'delta':delta_metrics(processed,before),
             'executed':measured is not None}
        if name=='spectral' and curr['spectral'] is not None:
            row['spectral_trace_index']=curr['spectral']
            start=trace['spectral'][curr['spectral']]['changed_support_extent']
            if start is not None and start[0]>0:
                row['stage_pre_support_delta']=delta_metrics(
                    np.asarray(processed)[:start[0]],before[:start[0]])
        trace['stages'].append(row)
        return processed,measured

    def route(source,sr,crossovers,processors,confine_flags,**kwargs):
        observed=[None]*4
        def wrap(index,proc):
            if proc is None:return None
            def call(band):
                curr['band']=index
                before=np.asarray(band,dtype=np.float64).copy()
                after=proc(band)
                observed[index]=(before,np.asarray(after,dtype=np.float64).copy())
                curr['band']=None
                return after
            return call
        processed,report=origin_route(source,sr,crossovers,
            tuple(wrap(i,p) for i,p in enumerate(processors)),
            confine_flags,**kwargs)
        independently=np.asarray(source,dtype=np.float64).copy()
        for i,obs in enumerate(observed):
            if obs is None:continue
            before,after=obs
            raw=after-before
            routed=split_bands(raw,sr,crossovers)[i] if confine_flags[i] else raw
            independently=independently+routed
            trace['bands'].append({'index':i,'input':pcm_identity(before),
                                  'output':pcm_identity(after),'raw_delta':pcm_identity(raw),
                                  'routed_delta':pcm_identity(routed),
                                  'confine_delta':bool(confine_flags[i])})
        trace['projection']={'policy':br.FILTER_POLICY,
                             'independent_routed_vs_production':delta_metrics(independently,processed),
                             'crossovers_hz':list(crossovers)}
        return processed,report

    def execute(source,sr,rack,**kwargs):
        trace['generated_source_pre_rack']=pcm_identity(source)
        if frozen_pre_rack is not None:
            frozen=np.asarray(frozen_pre_rack)
            if frozen.shape!=np.asarray(source).shape or not np.isfinite(frozen).all():
                raise ValueError('frozen pre-rack PCM must match generated length/channels and be finite')
            source=np.asarray(frozen,dtype=np.float64).copy()
            trace['input_policy']='EXPLICIT-COUNTERFACTUAL-FROZEN-PCM-NOT-AUTHENTICATED-PRE-RACK'
        else:
            trace['input_policy']='ordinary-compiled-timeline-synthline'
        trace['source_pre_rack']=pcm_identity(source)
        trace['sample_rate_hz']=sr
        result,diagnostics=origin_execute(source,sr,rack,**kwargs)
        trace['rack_output']=pcm_identity(result)
        trace['rack_sha256']=diagnostics['rack_sha256']
        trace['rack_sonic_sha256']=diagnostics['rack_sonic_sha256']
        trace['implementation_sha256']=diagnostics['implementation_sha256']
        trace['rack_filter']=diagnostics['filter']
        return result,diagnostics

    with ExitStack() as stack:
        stack.enter_context(patch.object(bs,'analyse_components',analyse))
        stack.enter_context(patch.object(bs,'retune_components',
            lambda *a,**k:spectral_call(origin_retune,*a,**k)))
        stack.enter_context(patch.object(bs,'apply_chordness',
            lambda *a,**k:spectral_call(origin_chord,*a,**k)))
        stack.enter_context(patch.object(rx,'process_builtin_stage',stage))
        stack.enter_context(patch.object(rx,'route_band_processors',route))
        stack.enter_context(patch.object(rx,'execute_rack',execute))
        rendered=render_phrase(recipe)
    trace['final_pcm']=pcm_identity(rendered.mix)
    if expected_pcm is not None:
        trace['original_export_comparison']=delta_metrics(rendered.mix,expected_pcm)
        trace['original_export_pcm']=pcm_identity(expected_pcm)
    return trace


