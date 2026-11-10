"""MBR-004 Gate B: read-only, full-pipeline, source-matched cross-host trace.

Use immutable original ZG-009 artifact ZIPs on each host. Capture executes
normal TimelineDocument -> compile_recipe -> render_phrase; monkeypatches are
scoped to this synchronous call and restore the original DSP immediately.
Does not change a sonic policy or assert a waveform tolerance.
"""
from __future__ import annotations
import argparse
import base64
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



# Actual read-only tracker operations, with bounded first-frame numerical bytes.
MAX_SUBLEDGER_FRAMES=512
MAX_SNAPSHOT_FRAMES=4
MAX_STAGE_PCM_BYTES=1048576

def _stage_pcm_bytes(a):
    a=np.ascontiguousarray(a,dtype='<f4')
    if a.ndim not in (1,2) or a.nbytes==0 or a.nbytes>MAX_STAGE_PCM_BYTES:
        raise ValueError('bounded spectral stage PCM required')
    if not np.isfinite(a).all():raise ValueError('non-finite spectral stage PCM')
    return {'shape':list(a.shape),'sha256':digest_bytes(a.tobytes()),
            'f32le_b64':base64.b64encode(a.tobytes()).decode('ascii')}

def _checked_stage_pcm(packet,identity):
    shape=packet['shape']
    if not isinstance(shape,list) or len(shape) not in (1,2) or any(type(n)is not int or n<1 for n in shape):
        raise ValueError('bad spectral stage PCM shape')
    size=int(np.prod(shape))*4
    if size==0 or size>MAX_STAGE_PCM_BYTES:raise ValueError('bad spectral stage PCM size')
    raw=base64.b64decode(packet['f32le_b64'],validate=True)
    if len(raw)!=size or digest_bytes(raw)!=packet['sha256']:
        raise ValueError('spectral stage PCM byte identity mismatch')
    a=np.frombuffer(raw,dtype='<f4').reshape(shape).copy()
    if not np.isfinite(a).all() or pcm_identity(a)['f32le_sha256']!=identity['f32le_sha256'] or pcm_identity(a)['f64le_sha256']!=identity['f64le_sha256']:
        raise ValueError('foreign or non-finite spectral analysis input')
    return a


def _numerical_tensor(a):
    a=np.asarray(a)
    if a.ndim<1 or len(a)>MAX_SUBLEDGER_FRAMES or a.nbytes>64*1024*1024:
        raise ValueError('bounded tracker array exceeded')
    if a.dtype.kind=='c':
        f=np.ascontiguousarray(a,dtype='<c16').view('<f8')
        kind='complex128-re-im'
    elif a.dtype.kind=='f':
        f=np.ascontiguousarray(a,dtype='<f8')
        kind='float64'
    else:raise ValueError('tracker numerical array required')
    if not np.isfinite(f).all():raise ValueError('non-finite tracker buffer')
    return {'kind':kind,'shape':list(a.shape),'sha256':digest_bytes(f.tobytes()),
            'frame_sha256':[digest_bytes(np.ascontiguousarray(f[i]).tobytes()) for i in range(len(f))],
            'frame_f64le_b64':[base64.b64encode(np.ascontiguousarray(f[i]).tobytes()).decode()
                               for i in range(min(len(f),MAX_SNAPSHOT_FRAMES))]}

def matched_stage_probe(current,reference):
    """Separate *new-execution* tracker probe on exact common Windows-stage PCM."""
    from zaaggenz_components import tracker as tr
    if (reference.get('input_policy')!='ordinary-compiled-timeline-synthline' or
        reference.get('source',{}).get('archive_sha256')!='9cbf9dbbb01dd236facc00b528c66e023c472bf7f601f99658026567dae42abc' or
        reference.get('source',{}).get('export_wav_sha256')!='2db1913eaafe142b060bd89849bb54552a7b98907019fb5de9dca44c0e569d8f' or
        reference.get('original_export_comparison',{}).get('nonzero_samples')!=0):
        raise ValueError('source trace not authenticated original Windows normal replay')
    for key in ('document_revision_id','compiled_recipe_sha256','rack_sha256',
                'rack_sonic_sha256','implementation_sha256','sample_rate_hz'):
        if current.get(key)!=reference.get(key):
            raise ValueError('foreign stage source/rack: '+key)
    if len(current.get('spectral',[]))!=1 or len(reference.get('spectral',[]))!=1:
        raise ValueError('one original spectral stage required')
    s=reference['spectral'][0]
    if current['spectral'][0]['request']!=s['request']:
        raise ValueError('foreign original spectral request')
    x=_checked_stage_pcm(s['subledger']['stage_input_f32le_b64'],s['analysis_input'])
    tap={'stft':None,'candidates':[],'assignments':[],'transient':None}
    with ExitStack() as stack:
        _tracker_taps(stack,[tap])
        analysis=tr.analyse_components(x,current['sample_rate_hz'])
    observed=pcm_identity(analysis.source)
    if observed['f32le_sha256']!=s['analysis_input']['f32le_sha256']:
        raise ValueError('tracker consumed a changed stage input')
    return {'input_policy':'MATCHED-WINDOWS-STAGE-F32-NEW-EXECUTION-NOT-ORIGINAL-TRACKER',
            'analysis_input':observed,'subledger':tap,'tracked':_frame_ledger(analysis),
            'diagnostics':analysis.diagnostics,'request':s['request'],
            'reference_archive_sha256':reference['source']['archive_sha256']}


def _anchor_frame_rows(tracked):
    rows={}
    for t in tracked:
        for f in t['frames']:
            rows.setdefault(str(f['anchor']),[]).append({
                'frequency_hz':f['frequency_hz'],'confidence':f['confidence'],
                'action':f['action'],'continuity':t['continuity']})
    return {key:sorted(value,key=lambda x:float.fromhex(x['frequency_hz']))
            for key,value in rows.items()}


def _first_tensor_delta(a,b):
    if a['kind']!=b['kind'] or a['shape']!=b['shape']:
        return {'kind':'type-or-shape','left':[a['kind'],a['shape']],
                'right':[b['kind'],b['shape']]}
    if a['sha256']==b['sha256']:return None
    if len(a['frame_sha256'])!=len(b['frame_sha256']):return {'kind':'frame-count'}
    frame=next((i for i,(x,y) in enumerate(zip(a['frame_sha256'],b['frame_sha256']))
                if x!=y),None)
    if frame is None:raise ValueError('inconsistent tracker tensor digest')
    d={'kind':'bitwise-f64','frame':frame}
    if frame>=len(a['frame_f64le_b64']) or frame>=len(b['frame_f64le_b64']):
        return {**d,'detail':'earliest frame hashed; first four raw frames retained'}
    x=np.frombuffer(base64.b64decode(a['frame_f64le_b64'][frame],validate=True),dtype='<f8')
    y=np.frombuffer(base64.b64decode(b['frame_f64le_b64'][frame],validate=True),dtype='<f8')
    if x.shape!=y.shape:raise ValueError('tracker snapshot length mismatch')
    indexes=np.flatnonzero(x.view('<u8')!=y.view('<u8'))
    if not len(indexes):raise ValueError('frame hash disagrees with snapshot')
    idx=int(indexes[0]);is_complex=a['kind'].startswith('complex')
    coord=np.unravel_index(idx//(2 if is_complex else 1),a['shape'][1:])
    return {**d,'index':[int(k) for k in coord],
            'component':('real' if idx%2==0 else 'imag') if is_complex else 'value',
            'ubuntu_hex':float(x[idx]).hex(),'windows_hex':float(y[idx]).hex(),
            'ubuntu':float(x[idx]),'windows':float(y[idx]),'delta':float(x[idx]-y[idx])}

def _tracker_taps(stack,active):
    from zaaggenz_components import tracker as tr
    original_stft=tr.stft
    original_peaks=tr.signal.find_peaks
    original_parabola=tr._parabolic_frequency
    original_fit=tr._fit_candidates
    original_assignment=tr.optimize.linear_sum_assignment
    original_transient=tr._transient_mask
    pending={'peak':None,'parabolas':[]}

    def stft(*a,**kw):
        if active[0] is None:return original_stft(*a,**kw)
        fft=np.fft.rfft;row={}
        def tap(weighted,*args,**kwargs):
            row['weighted']=_numerical_tensor(weighted)
            result=fft(weighted,*args,**kwargs)
            row['rfft']=_numerical_tensor(result)
            return result
        with patch.object(np.fft,'rfft',tap):
            result=original_stft(*a,**kw)
        if 'rfft' not in row:raise ValueError('native rfft was not observed')
        active[0]['stft']={'input':pcm_identity(a[0]),'spec':result.spec.metadata(),
          'sample_rate_hz':result.sample_rate_hz,
          'anchors':result.anchors.tolist(),'supports':result.supports.tolist(),
          'valid_fraction':[float(x).hex() for x in result.valid_fraction],**row}
        return result

    def peaks(magnitude,*a,**kw):
        ids,props=original_peaks(magnitude,*a,**kw)
        if active[0] is not None:
            pending['peak']={'magnitude':_numerical_tensor(np.asarray(magnitude)[None,:]),
                'prominence':_canonical(kw.get('prominence')),
                'height':_canonical(kw.get('height')),
                'distance':_canonical(kw.get('distance')),
                'local_bins':[int(k) for k in ids]}
        return ids,props

    def parabola(mag,k,sr,nfft):
        result=original_parabola(mag,k,sr,nfft)
        if active[0] is not None:
            pending['parabolas'].append({'bin':int(k),
                'magnitudes_hex':[float(v).hex() for v in mag[max(0,k-1):k+2]],
                'hz_hex':float(result).hex()})
        return result

    def fit(a,sr,r,i,frequencies,confidences,ambiguity):
        result=original_fit(a,sr,r,i,frequencies,confidences,ambiguity)
        if active[0] is not None:
            active[0]['candidates'].append({'frame':int(i),'anchor':int(r.anchors[i]),
                'support':[int(v) for v in r.supports[i]],
                'peaks':pending['peak'],'parabolas':pending['parabolas'],
                'selected_frequency_hex':_canonical(frequencies),
                'pre_fit_confidence_hex':_canonical(confidences),
                'ambiguous':[bool(v) for v in ambiguity],'fitted':_canonical(result)})
        pending['peak']=None;pending['parabolas']=[]
        return result

    def assign(cost,*a,**kw):
        rr,cc=original_assignment(cost,*a,**kw)
        if active[0] is not None:
            caller=sys._getframe(1)
            if caller.f_code.co_name!='_track':
                raise ValueError('unexpected tracker assignment caller')
            local=caller.f_locals;spec=local['spec']
            pairs=[(int(i),int(j)) for i,j in zip(rr,cc)]
            active[0]['assignments'].append({'frame':int(local['frame']),
                'predicted_hz_hex':_canonical(local['preds']),
                'candidate_hz_hex':_canonical([x['frequency_hz'] for x in local['cands']]),
                'cost_cents_hex':_canonical(np.asarray(cost).tolist()),
                'max_jump_cents_hex':float(spec.max_jump_cents).hex(),
                'selected_pairs':[[i,j] for i,j in pairs],
                'admitted_pairs':[[i,j] for i,j in pairs if cost[i,j]<=spec.max_jump_cents]})
        return rr,cc

    def transient(*a,**kw):
        result=original_transient(*a,**kw)
        if active[0] is not None:
            mask,onsets,detector=result
            active[0]['transient']={'mask':pcm_identity(mask),
                                    'onsets':int(onsets),'detector':detector}
        return result

    stack.enter_context(patch.object(tr,'stft',stft))
    stack.enter_context(patch.object(tr.signal,'find_peaks',peaks))
    stack.enter_context(patch.object(tr,'_parabolic_frequency',parabola))
    stack.enter_context(patch.object(tr,'_fit_candidates',fit))
    stack.enter_context(patch.object(tr.optimize,'linear_sum_assignment',assign))
    stack.enter_context(patch.object(tr,'_transient_mask',transient))


def _assignment_decision_witness(frame, ubuntu, windows, candidate_rows):
    """Describe a changed native assignment without equating tracker IDs.

    Totals are post-hoc sums of captured hexadecimal costs, not observations
    of the Hungarian solver's internal accumulation or tie-breaking policy.
    """
    anchor=next((c['anchor'] for c in candidate_rows if c is not None),None)
    if ubuntu is None or windows is None:
        return {'frame':frame,'anchor_sample':anchor,
                'kind':'assignment-frame-admission',
                'ubuntu_present':ubuntu is not None,'windows_present':windows is not None}
    chosen=[{tuple(v) for v in z['selected_pairs']} for z in (ubuntu,windows)]
    admitted=[{tuple(v) for v in z['admitted_pairs']} for z in (ubuntu,windows)]
    changed=sorted(chosen[0]^chosen[1] | admitted[0]^admitted[1])
    def details(packet,own,other):
        matrix=packet['cost_cents_hex']
        limit=float.fromhex(packet['max_jump_cents_hex'])
        def total(pairs):
            return float(sum(float.fromhex(matrix[i][j]) for i,j in pairs)).hex()
        out={'selected_pairs':packet['selected_pairs'],
             'admitted_pairs':packet['admitted_pairs'],
             'max_jump_cents_hex':packet['max_jump_cents_hex'],
             'changed_pair_costs':[{
                 'row':i,'column':j,
                 'predicted_hz_hex':packet['predicted_hz_hex'][i],
                 'candidate_hz_hex':packet['candidate_hz_hex'][j],
                 'cost_cents_hex':matrix[i][j],
                 'accepted_by_jump':float.fromhex(matrix[i][j])<=limit}
                 for i,j in changed],
             'selected_total_cents_hex':total(own),
             'other_host_pairing_total_cents_hex':total(other)}
        rows=sorted({i for i,_ in changed})
        cols=sorted({j for _,j in changed})
        if len(rows)==2 and len(cols)==2:
            i,k=rows;j,l=cols
            out['two_row_alternatives_cents_hex']={
                'diagonal':float(float.fromhex(matrix[i][j])+float.fromhex(matrix[k][l])).hex(),
                'cross':float(float.fromhex(matrix[i][l])+float.fromhex(matrix[k][j])).hex()}
        return out
    return {'frame':frame,'anchor_sample':anchor,
            'kind':'hungarian-pairing-or-jump-admission',
            'selected_pairs_differ':chosen[0]!=chosen[1],
            'admitted_pairs_differ':admitted[0]!=admitted[1],
            'ubuntu':details(ubuntu,chosen[0],chosen[1]),
            'windows':details(windows,chosen[1],chosen[0]),
            'near_tie_note':'Derived totals are diagnostic post-hoc float sums; not the solver objective or an acceptance tolerance'}


def compare_subledger(u,w):
    if (u['analysis_input']['shape']!=w['analysis_input']['shape'] or
        u['analysis_input']['f64le_sha256']!=w['analysis_input']['f64le_sha256']):
        return {'input_matched':False,'first_boundary':'different-f64-analysis-input'}
    a,b=u.get('subledger'),w.get('subledger')
    if not a or not b or not a.get('stft') or not b.get('stft'):
        return {'input_matched':True,'first_boundary':'missing-actual-tracker-capture'}
    x,y=a['stft'],b['stft']
    out={'input_matched':True,'first_boundary':None,
         'first_numeric_boundary':None,'first_candidate_difference':None,
         'first_discrete_boundary':None,'first_assignment_difference':None,
         'first_assignment_numeric_difference':None}
    for field in ('input','spec','sample_rate_hz','anchors','supports','valid_fraction'):
        if x[field]!=y[field]:out['first_boundary']='stft-'+field;break
    if out['first_boundary'] is None:
        for field in ('weighted','rfft'):
            d=_first_tensor_delta(x[field],y[field])
            if d is not None:
                out['first_boundary']='stft-'+('weighted-Hann-input' if field=='weighted' else 'native-rfft-output')
                out['first_numeric_difference']=d
                out['first_numeric_boundary']={'stage':out['first_boundary'],
                    'anchor_sample':x['anchors'][d['frame']] if 'frame' in d and d['frame']<len(x['anchors']) else None,
                    **d}
                break
    left={z['frame']:z for z in a['candidates']}
    right={z['frame']:z for z in b['candidates']}
    for frame in sorted(set(left)|set(right)):
        p,q=left.get(frame),right.get(frame)
        if p is None or q is None:
            out['first_discrete_boundary']={'frame':frame,'kind':'candidate-frame-admission'}
            break
        for field in ('peaks','parabolas','selected_frequency_hex','pre_fit_confidence_hex',
                      'ambiguous','fitted'):
            if p[field]!=q[field]:
                if out['first_candidate_difference'] is None:
                    d={'frame':frame,'anchor':p['anchor'],'field':field,
                       'ubuntu':str(p[field])[:800],'windows':str(q[field])[:800]}
                    if field=='peaks' and p[field] and q[field]:
                        d['first_magnitude_delta']=_first_tensor_delta(p[field]['magnitude'],q[field]['magnitude'])
                    out['first_candidate_difference']=d
                if out['first_discrete_boundary'] is None:
                    pa,pb=p['peaks'],q['peaks']
                    if (pa is None)!=(pb is None) or (pa and pb and pa['local_bins']!=pb['local_bins']):
                        out['first_discrete_boundary']={'frame':frame,'kind':'scipy-peak-selection',
                            'ubuntu':None if pa is None else pa['local_bins'],
                            'windows':None if pb is None else pb['local_bins']}
                    elif len(p['selected_frequency_hex'])!=len(q['selected_frequency_hex']):
                        out['first_discrete_boundary']={'frame':frame,'kind':'frequency-confidence-admission',
                            'ubuntu':p['selected_frequency_hex'],'windows':q['selected_frequency_hex']}
                    elif p['ambiguous']!=q['ambiguous']:
                        out['first_discrete_boundary']={'frame':frame,'kind':'peak-ambiguity'}
                    elif len(p['fitted'])!=len(q['fitted']):
                        out['first_discrete_boundary']={'frame':frame,'kind':'weighted-fit-admission'}
                break
    aa={z['frame']:z for z in a['assignments']}
    bb={z['frame']:z for z in b['assignments']}
    # Numeric differences and actual discrete choices are independent scans.
    # In particular, frame 2's changed float cost must not mask frame 13's
    # different Hungarian pairing when frame 2 still admits the same pairs.
    for frame in sorted(set(aa)|set(bb)):
        p,q=aa.get(frame),bb.get(frame)
        if p==q:
            continue
        if out['first_assignment_difference'] is None:
            out['first_assignment_difference']={'frame':frame,'ubuntu':p,'windows':q}
        if p is not None and q is not None and out['first_assignment_numeric_difference'] is None:
            lp,rp=p['cost_cents_hex'],q['cost_cents_hex']
            if len(lp)!=len(rp) or any(len(a)!=len(b) for a,b in zip(lp,rp)):
                out['first_assignment_numeric_difference']={'frame':frame,'kind':'cost-matrix-shape'}
            else:
                for i,(row_u,row_w) in enumerate(zip(lp,rp)):
                    j=next((k for k,(cu,cw) in enumerate(zip(row_u,row_w)) if cu!=cw),None)
                    if j is not None:
                        out['first_assignment_numeric_difference']={
                            'frame':frame,'row':i,'column':j,
                            'anchor_sample':next((z['anchor'] for z in (left.get(frame),right.get(frame))
                                                  if z is not None),None),
                            'ubuntu_cost_cents_hex':row_u[j],
                            'windows_cost_cents_hex':row_w[j],
                            'ubuntu_prediction_hz_hex':p['predicted_hz_hex'][i],
                            'windows_prediction_hz_hex':q['predicted_hz_hex'][i],
                            'ubuntu_candidate_hz_hex':p['candidate_hz_hex'][j],
                            'windows_candidate_hz_hex':q['candidate_hz_hex'][j]}
                        break
        choice_diff=(p is None or q is None or
                     p['selected_pairs']!=q['selected_pairs'] or
                     p['admitted_pairs']!=q['admitted_pairs'])
        if choice_diff and (out['first_discrete_boundary'] is None or
                            frame<out['first_discrete_boundary']['frame']):
            out['first_discrete_boundary']=_assignment_decision_witness(
                frame,p,q,(left.get(frame),right.get(frame)))
        # Continue until the first *discrete* assignment split is seen.
        # Early numeric drift alone never terminates the scan.
        if choice_diff:
            break
    if out['first_numeric_boundary'] is None and out['first_assignment_numeric_difference'] is not None:
        out['first_numeric_boundary']={'stage':'assignment-cost',
                                       **out['first_assignment_numeric_difference']}
    if out['first_numeric_boundary'] is None and out['first_candidate_difference'] is not None:
        out['first_numeric_boundary']={'stage':'post-fft-candidate',
                                       **out['first_candidate_difference']}
    if out['first_boundary'] is None and out['first_candidate_difference'] is not None:
        out['first_boundary']='post-fft-peak-fit'
    if out['first_boundary'] is None and out['first_assignment_difference'] is not None:
        out['first_boundary']='assignment-cost'
    return out


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
    curr={'band':None,'analysis':None,'spectral':None,'subledger':None}
    active=[None]
    origin_analyse=bs.analyse_components
    origin_retune=bs.retune_components
    origin_chord=bs.apply_chordness
    origin_stage=rx.process_builtin_stage
    origin_route=rx.route_band_processors
    origin_execute=rx.execute_rack

    def analyse(*args,**kwargs):
        probe={'version':'zg242-actual-tracker-subledger-v1','input':pcm_identity(args[0]),
               'stft':None,'candidates':[],'assignments':[],'transient':None,
                'stage_input_f32le_b64':_stage_pcm_bytes(args[0])}
        active[0]=probe
        try:result=origin_analyse(*args,**kwargs)
        finally:active[0]=None
        curr['subledger']=probe
        curr['analysis']=result
        return result

    def spectral_call(origin,*args,**kwargs):
        result=origin(*args,**kwargs)
        analysis=args[0]
        row={'band_index':curr['band'],'request':result.request.to_dict(),
             'analysis_input':pcm_identity(analysis.source),
             'analysis_diagnostics':analysis.diagnostics,
             'tracked':_frame_ledger(analysis),
              'subledger':curr['subledger'],
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
        _tracker_taps(stack,active)
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


def compare_trace(a,b):
    """Fail closed on source mismatch; inspect discrete frames before PCM."""
    required=('document_revision_id','compiled_recipe_sha256','rack_sonic_sha256','sample_rate_hz')
    for key in required:
        if key not in a or key not in b or a[key]!=b[key]:
            raise ValueError('foreign or mismatched source/recipe: '+key)
    report={'trace_version':TRACE_VERSION,'identity':{k:a[k] for k in required},
            'source_pcm_equal':a['source_pre_rack']['f32le_sha256']==b['source_pre_rack']['f32le_sha256'],
            'rack_pcm_equal':a['rack_output']['f32le_sha256']==b['rack_output']['f32le_sha256'],
            'final_pcm_equal':a['final_pcm']['f32le_sha256']==b['final_pcm']['f32le_sha256'],
            'spectral':[],'stages':[]}
    for index in range(max(len(a['spectral']),len(b['spectral']))):
        left=a['spectral'][index] if index<len(a['spectral']) else None
        right=b['spectral'][index] if index<len(b['spectral']) else None
        if left is None or right is None:
            report['spectral'].append({'index':index,'missing_host':True});continue
        def flatten(t):
            return {(tr['id'],frame['index']):frame for tr in t['tracked'] for frame in tr['frames']}
        u,w=flatten(left),flatten(right)
        decu={(d['track_id'],d['frame_index']):d for d in left['decisions']}
        decw={(d['track_id'],d['frame_index']):d for d in right['decisions']}
        keys=set(decu)|set(decw)
        disagreements=[key for key in sorted(keys) if decu.get(key)!=decw.get(key)]
        row={'index':index,'analysis_pcm_equal':left['analysis_input']['f32le_sha256']==right['analysis_input']['f32le_sha256'],
             'tracked_frame_count':[len(u),len(w)],
             'tracked_frame_keys_only_left':len(set(u)-set(w)),
             'tracked_frame_keys_only_right':len(set(w)-set(u)),
             'tracker_frame_value_mismatches':sum(u.get(k)!=w.get(k) for k in set(u)&set(w)),
             'decision_count':[len(decu),len(decw)],
             'decision_mismatches':len(disagreements),
             'first_decision_mismatches':[{'key':list(k),'left':decu.get(k),'right':decw.get(k)}
                                          for k in disagreements[:8]],
             'changed_support_extent':[left['changed_support_extent'],right['changed_support_extent']],
              'tracker_subledger':compare_subledger(left,right)}
        report['spectral'].append(row)
    if bool(a.get('matched_stage'))!=bool(b.get('matched_stage')):
        raise ValueError('matched-stage result missing on one host')
    if a.get('matched_stage'):
        u,w=a['matched_stage'],b['matched_stage']
        if u['reference_archive_sha256']!=w['reference_archive_sha256']:
            raise ValueError('mismatched common source receipt')
        matched=compare_subledger(u,w)
        p,q=_anchor_frame_rows(u['tracked']),_anchor_frame_rows(w['tracked'])
        first=next((k for k in sorted(set(p)|set(q),key=int) if p.get(k)!=q.get(k)),None)
        matched['first_physical_decision_difference']=None if first is None else {
            'anchor_sample':int(first),'ubuntu':p.get(first),'windows':q.get(first)}
        report['matched_stage']=matched
    for index in range(max(len(a['stages']),len(b['stages']))):
        left=a['stages'][index] if index<len(a['stages']) else None
        right=b['stages'][index] if index<len(b['stages']) else None
        report['stages'].append({'index':index,
             'name':left['stage'] if left else (right['stage'] if right else None),
             'input_pcm_equal':bool(left and right and left['input']['f32le_sha256']==right['input']['f32le_sha256']),
             'output_pcm_equal':bool(left and right and left['output']['f32le_sha256']==right['output']['f32le_sha256'])})
    return report


def _from_artifact(path,name):
    if not name.endswith('.zgtimeline.json') or '/' in name or '\\' in name:
        raise ValueError('expected an artifact-local .zgtimeline.json basename')
    with zipfile.ZipFile(path) as z:
        document=json.loads(z.read(name))
        raw=z.read(name)
        wav=name.removesuffix('.zgtimeline.json')+'.wav'
        audio=None
        if wav in z.namelist():audio,sr=decode_float32_wav(z.read(wav))
        else:sr=None
        return document,audio,sr,{'archive':Path(path).name,
            'archive_sha256':digest_bytes(Path(path).read_bytes()),
            'saved_document_sha256':digest_bytes(raw),
            'saved_document_name':name,'export_name':wav if audio is not None else None,
            'export_wav_sha256':digest_bytes(z.read(wav)) if audio is not None else None}


def original_artifact_inventory(ubuntu_path,windows_path):
    """Original exported PCM census. Descriptive deltas, NOT an admission screen."""
    host_paths={'ubuntu':Path(ubuntu_path),'windows':Path(windows_path)}
    zipped={h:zipfile.ZipFile(path) for h,path in host_paths.items()}
    try:
        names={h:{n for n in z.namelist() if n.endswith('.wav') and '/' not in n}
               for h,z in zipped.items()}
        if names['ubuntu']!=names['windows']:
            raise ValueError('the original WAV inventories differ across hosts')
        cases=[]
        for name in sorted(names['ubuntu']):
            samples={};rates={};raw_hashes={}
            for host,z in zipped.items():
                raw=z.read(name)
                raw_hashes[host]=digest_bytes(raw)
                audio,sr=decode_float32_wav(raw)
                samples[host]=audio
                rates[host]=sr
            if rates['ubuntu']!=rates['windows'] or samples['ubuntu'].shape!=samples['windows'].shape:
                raise ValueError('cross-host WAV rate/layout mismatch: '+name)
            err=delta_metrics(samples['ubuntu'],samples['windows'])
            rms=[pcm_identity(samples[host])['rms'] for host in ('ubuntu','windows')]
            cases.append({'name':name,'sample_rate_hz':rates['ubuntu'],
                          'shape':list(samples['ubuntu'].shape),'wav_sha256':raw_hashes,
                          'pcm_sha256':{h:pcm_identity(samples[h])['f32le_sha256'] for h in samples},
                          'rms_fs':{'ubuntu':rms[0],'windows':rms[1]},
                          'cross_host':{**err,'relative_to_smaller_output_rms':
                              (err['rms_fs']/min(rms) if min(rms)>0 else None)}})
        evidence={}
        for name in ('rack-order-numerical-evidence.json','rack-retune-numerical-evidence.json'):
            if all(name in z.namelist() for z in zipped.values()):
                evidence[name]={h:json.loads(z.read(name)) for h,z in zipped.items()}
        return {'trace_version':TRACE_VERSION,
                'type':'ORIGINAL-ARTIFACT-PCM-INVENTORY-NOT-ADMISSION',
                'source_run_id':42597270382,
                'source_head':'f28b4db07b863653370baf55b076f34f73c6a628',
                'artifact_zip_sha256':{h:digest_bytes(path.read_bytes()) for h,path in host_paths.items()},
                'wav_pair_count':len(cases),
                'rms_above_descriptive_1e_minus_6':sum(x['cross_host']['rms_fs']>1e-6 for x in cases),
                'cases':cases,'original_browser_decisions':evidence,
                'policy':'No gate tolerance adopted; >1e-6 is a descriptive census label only'}
    finally:
        for z in zipped.values():z.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    capture=sub.add_parser('capture',help='rerender original saved project and capture stage-local ledgers')
    capture.add_argument('--artifact',required=True,type=Path)
    capture.add_argument('--document',required=True)
    capture.add_argument('--out',required=True,type=Path)
    capture.add_argument('--frozen-pre-rack-wav',help='OPTIONAL counterfactual artifact-local dry PCM; not original pre-rack state')
    capture.add_argument('--match-stage-from',type=Path,help='optional separate matched tracker probe from original Windows normal trace')
    compare=sub.add_parser('compare',help='independent source-matched cross-host trace diff')
    compare.add_argument('--ubuntu',required=True,type=Path)
    compare.add_argument('--windows',required=True,type=Path)
    compare.add_argument('--out',required=True,type=Path)
    inventory=sub.add_parser('inventory',help='independently decode original cross-host WAVs and decision summaries')
    inventory.add_argument('--ubuntu',required=True,type=Path)
    inventory.add_argument('--windows',required=True,type=Path)
    inventory.add_argument('--out',required=True,type=Path)
    args=parser.parse_args(argv)
    if args.action=='capture':
        doc,expected,sr,prov=_from_artifact(args.artifact,args.document)
        frozen=None
        if args.frozen_pre_rack_wav:
            name=args.frozen_pre_rack_wav
            if '/' in name or '\\' in name or not name.endswith('.wav'):
                raise ValueError('frozen input must be a local WAV basename')
            with zipfile.ZipFile(args.artifact) as z:raw=z.read(name)
            frozen,freeze_sr=decode_float32_wav(raw)
            if sr is not None and freeze_sr!=sr:
                raise ValueError('frozen rate does not match expected output rate')
            prov['counterfactual_dry_wav']=name
            prov['counterfactual_wav_sha256']=digest_bytes(raw)
        trace=capture_document(doc,expected_pcm=expected,provenance=prov,frozen_pre_rack=frozen)
        if sr is not None and trace.get('sample_rate_hz')!=sr:
            raise ValueError('artifact exported rate does not match replay rate')
        if args.match_stage_from:
            if args.frozen_pre_rack_wav:
                raise ValueError('counterfactual dry substitution incompatible with matched stage')
            trace['matched_stage']=matched_stage_probe(
                trace,json.loads(args.match_stage_from.read_text(encoding='utf-8')))
        data=trace
    elif args.action=='compare':
        data=compare_trace(json.loads(args.ubuntu.read_text()),json.loads(args.windows.read_text()))
    else:data=original_artifact_inventory(args.ubuntu,args.windows)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(data,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'action':args.action,'trace_version':TRACE_VERSION,
        'out':str(args.out),'spectral_traces':len(data.get('spectral',[])),
        'original_wav_pairs':data.get('wav_pair_count'),
        'source_match':data.get('source_pcm_equal'),
        'original_export_difference':data.get('original_export_comparison')},sort_keys=True))


if __name__ == '__main__':
    main()
