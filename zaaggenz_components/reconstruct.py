from __future__ import annotations
import math
import numpy as np
from scipy import signal
from zaaggenz_contracts import Contract,validate
from .model import ComponentError

def _data(bundle):
    d=bundle.to_dict() if isinstance(bundle,Contract) else bundle
    try:validate(d,'PartialTrackBundle')
    except Exception as exc:raise ComponentError('valid PartialTrackBundle required') from exc
    return d

def reconstruct_components(bundle):
    """Resynthesise only the sinusoidal ownership described by a component bundle."""
    d=_data(bundle);asset=d['asset'];n=asset['frame_count'];ch=asset['channels'];sr=asset['sample_rate_hz']
    out=np.zeros((n,ch),dtype=np.float64)
    for track in d['tracks']:
        num=np.zeros((n,ch),dtype=np.float64);den=np.zeros(n,dtype=np.float64)
        for row in track['frames']:
            s=row['support'];lo,hi,anchor=s['start_sample'],s['end_sample'],s['anchor_sample'];win_n=hi-lo
            if win_n<2:continue
            start=max(0,lo);end=min(n,hi)
            if start>=end:continue
            w=signal.windows.hann(win_n,sym=False);local=np.arange(start,end)-lo;weight=w[local]
            tau=(np.arange(start,end,dtype=np.float64)-anchor)/sr
            for c in range(ch):
                phase=2*math.pi*row['frequency_hz']*tau+row['phases_radians'][c]
                num[start:end,c]+=row['amplitudes'][c]*np.cos(phase)*weight
            den[start:end]+=weight
        good=den>1e-7
        if np.any(good):num[good]/=den[good,None]
        out+=num
    out=np.asarray(out,dtype=np.float32)
    return out[:,0] if ch==1 else out
