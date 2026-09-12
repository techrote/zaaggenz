"""Baseline-independent spectral experiments; all inputs are analytic/seeded.
See notes and SOURCE_REGISTER.md. These are not integrated audio effects.
"""
from __future__ import annotations
import math
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy import signal, optimize
from common import METHOD, SEED, rms, db, cents, dump, table, mono


def stft(x, n, hop):
    """Real FFT, periodic Hann, explicit half-window zero padding, raw FFT units."""
    x = mono(x)
    if n < 16 or n % 2 or not 0 < hop <= n//2:
        raise ValueError('even window >=16 and hop <= half-window required')
    padded = np.pad(x, (n//2, n//2))
    extra = (-(len(padded)-n)) % hop
    padded = np.pad(padded, (0, extra))
    frames = sliding_window_view(padded, n)[::hop]
    w = signal.windows.hann(n, sym=False)
    return np.fft.rfft(frames*w, axis=-1), w


def istft(z, w, hop, length):
    n = len(w)
    y = np.zeros((len(z)-1)*hop+n); norm = np.zeros_like(y)
    for i, frame in enumerate(np.fft.irfft(z, n=n, axis=-1)):
        sl = slice(i*hop, i*hop+n)
        y[sl] += frame*w; norm[sl] += w*w
    valid = norm > 1e-14
    y[valid] /= norm[valid]
    return y[n//2:n//2+length]


def integrated_phase(f, sr, initial=0.0):
    """Trapezoidal integration; phase at sample 0 is the supplied phase."""
    f = mono(f)
    return initial + 2*np.pi*np.r_[0, np.cumsum((f[1:]+f[:-1])*.5)]/sr


def run_resolution(out):
    rows=[]; rng=np.random.default_rng(SEED)
    for sr in (44100, 48000, 96000):
        t=np.arange(round(1.3*sr))/sr
        for n in (512,2048,8192,32768):
            hop=n//4
            # Reconstruction, including edges and nonzero end-sample.
            x=.2*np.sin(2*np.pi*48*t)+.03*rng.standard_normal(len(t)); x[0]+=.3
            z,w=stft(x,n,hop); y=istft(z,w,hop,len(x))
            null=db(rms(y-x)/rms(x))
            for f in (34.7,48.,123.45,973.21):
                a=np.sin(2*np.pi*f*t+.37); Z,_=stft(a,n,hop)
                centres=np.arange(len(Z))*hop
                good=np.where((centres>=n//2)&(centres+n//2<len(a)))[0]
                mags=np.abs(Z[good]); k=np.argmax(mags,axis=1)
                interp=[]; ph=[]
                for j,kk in zip(good,k):
                    if 0<kk<Z.shape[1]-1:
                        u=np.log(np.maximum(abs(Z[j,kk-1:kk+2]),1e-20))
                        denom=u[0]-2*u[1]+u[2]
                        d=.5*(u[0]-u[2])/denom if abs(denom)>1e-15 else 0
                        interp.append((kk+np.clip(d,-.5,.5))*sr/n)
                    if j+1<len(Z) and 0<kk<Z.shape[1]-1:
                        delta=np.angle(Z[j+1,kk]*np.conj(Z[j,kk])*np.exp(-2j*np.pi*hop*kk/n))
                        ph.append(kk*sr/n+delta*sr/(2*np.pi*hop))
                # Null estimates are valid abstentions, not fabricated zero error.
                er=lambda a: float(np.median(np.abs(np.asarray(a)-f))) if a else None
                rows.append(dict(sr=sr,window=n,hop=hop,support_ms=1000*n/sr,
                    bin_hz=sr/n,true_hz=f,parabolic_mae_hz=er(interp),
                    phase_mae_hz=er(ph),null_db=null,valid_estimates=len(ph)))
    table(out/'resolution.csv',rows)
    twin=[]
    sr=48000; t=np.arange(2*sr)/sr
    for n in (512,2048,4096,8192,16384,32768):
        Z,_=stft(np.sin(2*np.pi*48*t)+.8*np.sin(2*np.pi*55*t+.3),n,n//4)
        mag=np.mean(abs(Z[2:-2]),axis=0); freq=np.fft.rfftfreq(n,1/sr)
        peaks,_=signal.find_peaks(mag, prominence=max(mag)*.07)
        found=freq[peaks[(freq[peaks]>30)&(freq[peaks]<90)]]
        count=sum(bool(np.any(abs(found-f)<1.5)) for f in (48,55))
        twin.append(dict(window=n,bin_hz=sr/n,support_ms=1000*n/sr,
                         found_hz=[float(v) for v in found],resolved_truths=count))
    f=48+7*np.linspace(0,1,sr)
    correct=integrated_phase(f,sr); naive=2*np.pi*f*np.arange(sr)/sr
    ic=np.diff(correct)*sr/(2*np.pi); ib=np.diff(naive)*sr/(2*np.pi)
    result={'method':METHOD,'two_tone':twin,'phase_glide':{
        'frequency_target_start_hz':48.,'frequency_target_end_hz':55.,
        'integrated_endpoint_hz':float(ic[-1]),'naive_endpoint_hz':float(ib[-1]),
        'comment':'oracle frequency input, NOT an implemented partial tracker'},
        'max_identity_relative_rms_db':max(r['null_db'] for r in rows)}
    dump(out/'resolution_summary.json',result)
    return result


def lowpass(x,sr,f):
    return signal.sosfiltfilt(signal.butter(4,f,fs=sr,output='sos'),x)


def bands(x,sr,cross):
    if len(cross)!=3 or not 0<cross[0]<cross[1]<cross[2]<sr/2:
        raise ValueError('three increasing in-band crossovers required')
    l=[lowpass(x,sr,f) for f in cross]
    return [l[0],l[1]-l[0],l[2]-l[1],np.asarray(x)-l[2]]


def project(x,sr,cross,b):
    return bands(x,sr,cross)[b]


def crush(x,bits=7,hold=4):
    """Fixed-reference symmetric mid-tread quantiser; zero maps exactly to zero."""
    if not 2<=bits<=24 or not 1<=hold<=64:
        raise ValueError('invalid quantiser bounds')
    y=mono(x)[(np.arange(len(x))//hold)*hold]
    levels=2**(bits-1)-1
    return np.round(np.clip(y,-1,1)*levels)/levels


def run_bands(out):
    rows=[]; sr=48000; t=np.arange(sr)/sr
    x=sum(.10*np.sin(2*np.pi*f*t+.3) for f in (70,105,260,520,1500,3600,8000))
    for cross in ((105,520,3600),(90,700,5000),(180,1000,6400)):
        b=bands(x,sr,cross)
        wrong=sum(project(v,sr,cross,i) for i,v in enumerate(b))
        identity=x+sum(project(v-v,sr,cross,i) for i,v in enumerate(b))
        delta=crush(b[2])-b[2]; confined=project(delta,sr,cross,2)
        freqs=np.fft.rfftfreq(len(x),1/sr)
        # Remove edge regions by tapered analysis; transition allowance is explicit.
        power=lambda a: abs(np.fft.rfft(a*signal.windows.hann(len(a),sym=False)))**2
        outside=(freqs<cross[1]/1.5)|(freqs>cross[2]*1.5)
        leakage=lambda a: float(power(a)[outside].sum()/max(power(a).sum(),1e-30))
        rows.append({'crossovers':list(cross),'dry_sum_relative_db':db(rms(sum(b)-x)/rms(x)),
            'refilter_unchanged_relative_db':db(rms(wrong-x)/rms(x)),
            'delta_identity_relative_db':db(rms(identity-x)/rms(x)),
            'unconfined_effect_leakage_fraction':leakage(delta),
            'confined_effect_leakage_fraction':leakage(confined),
            'effect_rms':rms(confined), 'edge_policy':'whole-file filtfilt; not causal or chunk-equivalent'})
    dump(out/'band_delta.json',{'method':METHOD,'rows':rows,
        'transition_exclusion':'below f_low/1.5 or above f_high*1.5; energy ratio of EFFECT DELTA, not whole output',
        'silence_quantiser_max':float(np.max(abs(crush(np.zeros(128)))))})
    return rows


def nonlinearity(x,kind,drive):
    z=drive*x
    if kind=='tanh': return np.tanh(z)
    if kind=='hard': return np.clip(z,-1,1)
    if kind=='fold': return 2/np.pi*np.arcsin(np.sin(np.pi*z))
    raise ValueError(kind)


def run_alias(out):
    sr=48000; seconds=.36; rows=[]
    # Analytic inputs at every sampling rate isolate nonlinear aliasing, not
    # quality of an upsampler. Proxy references are 64x and 128x, not ground truth.
    for freq in (48.,997.,6123.):
        for kind in ('hard','tanh','fold'):
            for drive in (2.,8.):
                def render(os):
                    t=np.arange(round(seconds*sr*os))/(sr*os)
                    x=.4*np.sin(2*np.pi*freq*t)+.13*np.sin(2*np.pi*freq*1.37*t+.4)
                    y=nonlinearity(x,kind,drive)
                    return signal.resample_poly(y,1,os,window=('kaiser',10.)) if os>1 else y
                ref=render(64); higher=render(128); edge=2400; sl=slice(edge,-edge)
                floor=db(rms(ref[sl]-higher[sl])/rms(higher[sl]))
                for os in (1,2,4,8):
                    y=render(os)
                    rows.append(dict(frequency_hz=freq,kind=kind,drive=drive,oversample=os,
                        error_vs_64x_db=db(rms(y[sl]-ref[sl])/rms(ref[sl])),
                        reference_64_vs_128_db=floor))
    table(out/'nonlinear_alias.csv',rows)
    return rows


def rough_pair(f1,f2,a1,a2,weight='minimum'):
    f1,f2,a1,a2=np.broadcast_arrays(f1,f2,a1,a2)
    s=.24/(.0207*np.minimum(f1,f2)+18.96)
    d=s*abs(f1-f2)
    w=np.minimum(a1,a2) if weight=='minimum' else a1*a2
    return w*5*(np.exp(-3.51*d)-np.exp(-5.75*d))


def dissonance_curves(f,a,cgrid,weight='minimum'):
    ratios=2**(cgrid/1200)
    cross=rough_pair(f[None,:,None],ratios[:,None,None]*f[None,None,:],
                     a[None,:,None],a[None,None,:],weight).sum(axis=(1,2))
    i,j=np.triu_indices(len(f),1)
    internal=float(rough_pair(f[i],f[j],a[i],a[j],weight).sum())
    shifted=rough_pair(ratios[:,None]*f[i],ratios[:,None]*f[j],a[i],a[j],weight).sum(axis=1)
    return cross, cross+internal+shifted


def run_dissonance(out):
    c=np.arange(0.,1200.1,2.); rows=[]; selected=[]
    for kind in ('harmonic','odd','stretched'):
        for root in (34.7,48.,96.,192.,500.):
            for n in (8,16):
                k=np.arange(1,n+1,dtype=float)
                f=root*(2*k-1 if kind=='odd' else k**1.08 if kind=='stretched' else k)
                a=k**-.7; a/=np.sqrt(np.sum(a*a))
                for weighting in ('minimum','product'):
                    cross,total=dissonance_curves(f,a,c,weighting)
                    minima={}
                    for name,curve in (('cross',cross),('total',total)):
                        ix,_=signal.find_peaks(-curve,prominence=max(np.ptp(curve)*.001,1e-9))
                        ix=ix[(c[ix]>=100)&(c[ix]<=1150)]
                        ranked=sorted(ix,key=lambda q:curve[q])[:6]
                        minima[name]=[float(c[q]) for q in ranked]
                    rows.append(dict(timbre=kind,root_hz=root,partials=n,weight=weighting,
                                     cross_minima_cents=minima['cross'],total_minima_cents=minima['total']))
                    if root in (48.,500.) and n==16 and weighting=='minimum':
                        for i in range(0,len(c),5):
                            selected.append(dict(timbre=kind,root_hz=root,cents=c[i],cross=cross[i],total=total[i]))
    dump(out/'dissonance_minima.json',{'method':METHOD,'parameter_count':len(rows),'rows':rows,
          'limitations':['Synthetic spectra only; not LOCKED BLOOM or reference-track pitch extraction.',
            'Grid minima have 2-cent sampling, not perceptual precision.',
            'Cross-tone interactions differ from total pairwise dissonance.',
            'Minimum/product weighting are sensitivity alternatives, not interchangeable models.',
            'Values are model scores, not key/scale/chord correctness or pleasure.']})
    table(out/'dissonance_curves.csv',selected)
    return rows


def comb(root_ratios, f0=48., count=32):
    f=(np.asarray(root_ratios)[:,None]*f0*np.arange(1,count+1)).ravel()
    return np.unique(np.round(f[(f>=48)&(f<=1200)],8))


def affinity(source,target,width=20.):
    return float(np.mean(np.exp(-.5*(np.min(abs(cents(source[:,None]/target[None,:])),axis=1)/width)**2)))


def run_chordness(out):
    rng=np.random.default_rng(SEED+7)
    target_sets={'one_root':comb([1]),'major':comb([1,1.25,1.5]),
                 'chromatic':comb(2**(np.arange(12)/12))}
    random_sources=np.exp(rng.uniform(np.log(48),np.log(1200),(512,24)))
    actual=48*np.arange(1,25)
    rows=[]
    for name,target in target_sets.items():
        null=np.array([affinity(v,target) for v in random_sources]); fit=affinity(actual,target)
        rows.append(dict(target=name,teeth=len(target),random_mean=float(null.mean()),
            random_sd=float(null.std(ddof=1)),harmonic_source_fit=fit,
            calibrated_z=float((fit-null.mean())/null.std(ddof=1))))
    # Failure fixture: three components independently attracted to one easy tooth.
    source=np.array([100.,101.,102.]); target=np.array([100.,150.,200.])
    costs=abs(cents(source[:,None]/target[None,:])); cap=50.
    # Dummy columns preserve unassigned components rather than coercing huge moves.
    aug=np.c_[costs,np.full((len(source),len(source)),cap)]
    rr,cc=optimize.linear_sum_assignment(aug)
    assigned=[int(v) if v<len(target) else None for v in cc]
    result={'method':METHOD,'random_trials':512,'kernel_width_cents':20.,'density_bias':rows,
      'capacity_example':{'naive_target_indices':np.argmin(costs,axis=1).tolist(),
                          'capacity_target_indices':assigned,'dummy_cost_cents':cap},
      'warning':'Null is log-uniform synthetic input; its z-score is NOT calibrated to mastered music or perceived chordness.'}
    dump(out/'chordness_bias.json',result)
    return result


def main(out):
    out.mkdir(parents=True,exist_ok=True)
    return dict(resolution=run_resolution(out),bands=run_bands(out),
       alias_rows=len(run_alias(out)),dissonance_cases=len(run_dissonance(out)),chordness=run_chordness(out))
