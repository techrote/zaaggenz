from __future__ import annotations
import math
import numpy as np
from .metrics import _matrix,source_preservation,alignment

class QCError(AssertionError):pass

def check_identity(reference,candidate,*,latency_samples=0,atol=0.,rtol=0.):
    r=_matrix(reference);c=_matrix(candidate)
    if latency_samples:
        if latency_samples>0:r=r[:-latency_samples] if latency_samples<len(r) else r[:0];c=c[latency_samples:]
        else:c=c[:latency_samples] if -latency_samples<len(c) else c[:0];r=r[-latency_samples:]
    if r.shape!=c.shape:raise QCError(f'identity shape mismatch {r.shape} != {c.shape}')
    if atol==0 and rtol==0:
        if not np.array_equal(r,c):raise QCError('expected bit-identical bypass')
    elif not np.allclose(r,c,atol=atol,rtol=rtol,equal_nan=False):raise QCError('identity tolerance exceeded')
    return {'latency_samples':latency_samples,'max_abs_error':float(np.max(np.abs(r-c))) if r.size else 0.,'frames_compared':len(r)}

def check_required_stems(stems,required=('synthline','body','aux','sub','kick','bass','mix')):
    missing=[k for k in required if k not in stems]
    if missing:raise QCError('missing required stems: '+','.join(missing))
    shapes={k:np.asarray(stems[k]).shape for k in required}
    if len(set(shapes.values()))!=1:raise QCError('stem alignment/shape mismatch')
    if float(np.sqrt(np.mean(np.asarray(stems['synthline'],float)**2)))<=1e-8:raise QCError('SYNTHLINE is effectively absent')
    if not all(np.isfinite(np.asarray(stems[k])).all() for k in required):raise QCError('nonfinite stem')
    return {'required':list(required),'shape':list(next(iter(shapes.values()))),'synthline_rms':float(np.sqrt(np.mean(np.asarray(stems['synthline'],float)**2)))}

def check_master_gain(before,after,gain_db,tolerance=2e-6):
    b=_matrix(before);a=_matrix(after)
    if b.shape!=a.shape:raise QCError('master shape mismatch')
    expected=10**(float(gain_db)/20);mask=np.abs(b)<.99/max(expected,1e-30)
    if not np.any(mask):raise QCError('no unclipped samples available for master-gain test')
    ratio=float(np.sqrt(np.mean(a[mask]**2))/max(np.sqrt(np.mean(b[mask]**2)),1e-30))
    if abs(ratio-expected)>tolerance:raise QCError(f'master ratio {ratio} != {expected}')
    return {'gain_db':float(gain_db),'expected_ratio':expected,'measured_ratio':ratio}

def check_source_preservation(reference,candidate,max_gain_aligned_error=1e-7):
    result=source_preservation(reference,candidate)
    if result['gain_aligned_relative_rms']>max_gain_aligned_error:raise QCError('source shape/timbre changed beyond declared tolerance')
    return result
