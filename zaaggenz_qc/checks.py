from __future__ import annotations
import math
import numpy as np
from .metrics import _matrix,source_preservation,alignment

class QCError(AssertionError):pass


def _require_finite_audio(label,*arrays):
    for value in arrays:
        if not np.isfinite(value).all():raise QCError(f'{label}: non-finite audio')


def _require_finite_scalar(label,value):
    try:v=float(value)
    except (TypeError,ValueError,OverflowError) as exc:raise QCError(f'{label}: invalid numeric metric') from exc
    if not math.isfinite(v):raise QCError(f'{label}: non-finite metric')
    return v


def _rms_finite(value,label):
    a=np.asarray(value,dtype=np.float64)
    _require_finite_audio(label,a)
    if not a.size:return 0.
    peak=float(np.max(np.abs(a)))
    if peak==0:return 0.
    # Scale first so squaring finite but very large samples cannot overflow and
    # turn an acceptance comparison into NaN/Inf by accident.
    rms=peak*float(np.sqrt(np.mean((a/peak)**2)))
    return _require_finite_scalar(label+' RMS',rms)


def check_identity(reference,candidate,*,latency_samples=0,atol=0.,rtol=0.):
    r=_matrix(reference);c=_matrix(candidate)
    _require_finite_audio('identity',r,c)
    if not math.isfinite(float(atol)) or not math.isfinite(float(rtol)) or atol<0 or rtol<0:raise QCError('identity tolerances must be finite and nonnegative')
    if latency_samples:
        if latency_samples>0:r=r[:-latency_samples] if latency_samples<len(r) else r[:0];c=c[latency_samples:]
        else:c=c[:latency_samples] if -latency_samples<len(c) else c[:0];r=r[-latency_samples:]
    if r.shape!=c.shape:raise QCError(f'identity shape mismatch {r.shape} != {c.shape}')
    if atol==0 and rtol==0:
        if not np.array_equal(r,c):raise QCError('expected bit-identical bypass')
    elif not np.allclose(r,c,atol=atol,rtol=rtol,equal_nan=False):raise QCError('identity tolerance exceeded')
    error=float(np.max(np.abs(r-c))) if r.size else 0.
    _require_finite_scalar('identity max_abs_error',error)
    return {'latency_samples':latency_samples,'max_abs_error':error,'frames_compared':len(r)}


def check_required_stems(stems,required=('synthline','body','aux','sub','kick','bass','mix')):
    missing=[k for k in required if k not in stems]
    if missing:raise QCError('missing required stems: '+','.join(missing))
    arrays={k:np.asarray(stems[k]) for k in required}
    shapes={k:arrays[k].shape for k in required}
    if len(set(shapes.values()))!=1:raise QCError('stem alignment/shape mismatch')
    _require_finite_audio('required stems',*(arrays[k] for k in required))
    synthline_rms=_rms_finite(arrays['synthline'],'SYNTHLINE')
    if synthline_rms<=1e-8:raise QCError('SYNTHLINE is effectively absent')
    return {'required':list(required),'shape':list(next(iter(shapes.values()))),'synthline_rms':synthline_rms}


def check_master_gain(before,after,gain_db,tolerance=2e-6):
    b=_matrix(before);a=_matrix(after)
    if b.shape!=a.shape:raise QCError('master shape mismatch')
    _require_finite_audio('master gain',b,a)
    gain_db=_require_finite_scalar('master gain_db',gain_db)
    tolerance=_require_finite_scalar('master tolerance',tolerance)
    if tolerance<0:raise QCError('master tolerance must be nonnegative')
    with np.errstate(over='ignore',invalid='ignore'):
        expected=float(np.power(10.0,gain_db/20.0))
    expected=_require_finite_scalar('master expected ratio',expected)
    mask=np.abs(b)<.99/max(expected,1e-30)
    if not np.any(mask):raise QCError('no unclipped samples available for master-gain test')
    before_rms=_rms_finite(b[mask],'master before')
    after_rms=_rms_finite(a[mask],'master after')
    ratio=after_rms/max(before_rms,1e-30)
    ratio=_require_finite_scalar('master measured ratio',ratio)
    if abs(ratio-expected)>tolerance:raise QCError(f'master ratio {ratio} != {expected}')
    return {'gain_db':gain_db,'expected_ratio':expected,'measured_ratio':ratio}


def check_source_preservation(reference,candidate,max_gain_aligned_error=1e-7):
    r=_matrix(reference);c=_matrix(candidate)
    _require_finite_audio('source preservation',r,c)
    limit=_require_finite_scalar('source-preservation tolerance',max_gain_aligned_error)
    if limit<0:raise QCError('source-preservation tolerance must be nonnegative')
    with np.errstate(over='ignore',invalid='ignore',divide='ignore'):
        result=source_preservation(r,c)
    required=('gain_fit','correlation','gain_aligned_relative_rms','gain_aligned_error_db','crest_delta_db')
    for key in required:_require_finite_scalar('source preservation '+key,result[key])
    if result['gain_aligned_relative_rms']>limit:raise QCError('source shape/timbre changed beyond declared tolerance')
    return result
