"""Generate deterministic ZG-017 engineering evidence; no preference/listening claim."""
from __future__ import annotations
import argparse,hashlib,json,math,platform,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from zaaggenz_components import analyse_components
from zaaggenz_tuning import fixture_pack,tuning_to_spec
from zaaggenz_spectral import (LatticeVoice,LatticeSegment,SpectralRetuneRequest,
                               cents_distance,retune_components)

def pcm_sha(x):return hashlib.sha256(np.asarray(x,dtype='<f4',order='C').tobytes()).hexdigest()
def tone(sr,f,duration=1.,amp=.55,phase=.23):
    t=np.arange(round(sr*duration),dtype=np.float64)/sr
    return (amp*np.cos(2*np.pi*f*t+phase)).astype(np.float32)
def phase_delta(a,b):return ((b-a+math.pi)%(2*math.pi))-math.pi
def stereo_phase(row):return phase_delta(row['phases_radians'][0],row['phases_radians'][1])
def spectral_power(x,sr,f):
    a=np.asarray(x,dtype=np.float64)
    if a.ndim==2:a=np.mean(a,axis=1)
    w=np.hanning(len(a));sp=np.abs(np.fft.rfft(a*w))**2;freq=np.fft.rfftfreq(len(a),1/sr);k=int(np.argmin(abs(freq-f)))
    lo=max(0,k-2);hi=min(len(sp),k+3);return float(np.sum(sp[lo:hi]))

def make_request(sr,**kwargs):
    values=dict(tuning_spec=tuning_to_spec(fixture_pack()['12tet-a440']),voices=(LatticeVoice(0,(1.,),'a440'),),
                min_hz=100.,max_hz=1200.,max_displacement_cents=180.,max_correction_slew_cents_per_second=1200.)
    values.update(kwargs);return SpectralRetuneRequest(**values)

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=48000);a=p.parse_args();sr=a.sample_rate
    source=tone(sr,445.,1.0);analysis=analyse_components(source,sr)
    bypass=retune_components(analysis,make_request(sr,amount=0.));retuned=retune_components(analysis,make_request(sr))
    transformed=[d for d in retuned.plan.decisions if d.decision=='transform']
    target_error=float(np.median([abs(cents_distance(d.realised_hz,440.)) for d in transformed])) if transformed else None

    stereo=np.column_stack((source,-source));st_analysis=analyse_components(stereo,sr);st_result=retune_components(st_analysis,make_request(sr))
    src_tracks={t['id']:t for t in st_analysis.bundle.to_dict()['tracks']};phase_errors=[]
    for tr in st_result.bundle.to_dict()['tracks']:
        old=src_tracks[tr['id']]
        for before,after in zip(old['frames'],tr['frames']):
            if abs(after['frequency_hz']-before['frequency_hz'])<1e-10:continue
            phase_errors.append(abs(phase_delta(stereo_phase(after),stereo_phase(before))))

    transient_source=tone(sr,445.,1.0,.25);transient_source[len(transient_source)//2]+=1.
    tr_analysis=analyse_components(transient_source,sr);tr_result=retune_components(tr_analysis,make_request(sr))

    change=sr//2;slew=240.;change_request=make_request(sr,segments=(LatticeSegment(change,(LatticeVoice(1,(1.,),'degree1'),),'raise'),),max_correction_slew_cents_per_second=slew)
    change_result=retune_components(analyse_components(tone(sr,443.,1.2),sr),change_request)
    rows=[d for d in change_result.plan.decisions if d.decision=='transform'];slew_excess=[]
    for first,second in zip(rows,rows[1:]):
        if first.track_id!=second.track_id:continue
        allowed=slew*(second.anchor_sample-first.anchor_sample)/sr
        slew_excess.append(max(0.,abs(second.correction_cents-first.correction_cents)-allowed))

    target_power=spectral_power(retuned.audio,sr,440.);source_power=spectral_power(retuned.audio,sr,445.)
    report={'scope':'deterministic synthetic engineering evidence; not listening preference or source-track evidence',
            'platform':platform.platform(),'python':sys.version,'sample_rate_hz':sr,'method':retuned.diagnostics['method'],
            'identity':{'source_sha256':pcm_sha(source),'bypass_sha256':pcm_sha(bypass.audio),'exact':bool(np.array_equal(source,bypass.audio))},
            'isolated_retune':{'transformed_frames':len(transformed),'median_realised_target_error_cents':target_error,
                               'output_sha256':pcm_sha(retuned.audio),'target_440_power':target_power,'source_445_power':source_power,
                               'target_to_source_bin_power_db':10*math.log10(max(target_power,1e-300)/max(source_power,1e-300))},
            'stereo':{'changed_frames_checked':len(phase_errors),'max_interchannel_phase_error_radians':max(phase_errors,default=0.)},
            'remainders':{'transient_identical':bool(np.array_equal(tr_result.transient,tr_analysis.transient)),
                          'residual_identical':bool(np.array_equal(tr_result.residual,tr_analysis.residual)),
                          'transient_sha256':pcm_sha(tr_result.transient),'residual_sha256':pcm_sha(tr_result.residual)},
            'target_change':{'start_sample':change,'segments':change_result.diagnostics['target_segments'],
                             'max_slew_excess_cents':max(slew_excess,default=0.),
                             'last_requested_hz':rows[-1].requested_hz if rows else None},
            'finite_output':bool(np.isfinite(retuned.audio).all() and np.isfinite(change_result.audio).all())}
    failures=[]
    if not report['identity']['exact']:failures.append('amount-zero path was not exact')
    if not transformed:failures.append('isolated tone produced no transformed frames')
    if target_error is None or target_error>=1.:failures.append('isolated target error exceeded 1 cent')
    if report['stereo']['changed_frames_checked']<1 or report['stereo']['max_interchannel_phase_error_radians']>=1e-8:failures.append('stereo relation was not preserved')
    if not report['remainders']['transient_identical'] or not report['remainders']['residual_identical']:failures.append('remainder ownership changed')
    if report['target_change']['segments']!=2 or report['target_change']['max_slew_excess_cents']>=1e-6:failures.append('target-change slew bound failed')
    if not report['finite_output']:failures.append('nonfinite output')
    report['acceptance_failures']=failures
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    if failures:raise SystemExit('ZG-017 evidence failed: '+'; '.join(failures))
if __name__=='__main__':main()
