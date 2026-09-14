"""Generate deterministic ZG-019 engineering evidence from the frozen benchmark recipes."""
from __future__ import annotations
import argparse,json,platform,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from zaaggenz_dsp import reference_error
from zaaggenz_spectral import (LatticeVoice,NonlinearStageSpec,PlacementRequest,SpectralRetuneRequest,
                               run_family)
from zaaggenz_spectral.placement_metrics import difference_metrics,summarize_audio
from zaaggenz_tuning import fixture_pack,tuning_to_spec


def source_from_recipe(recipe):
    sr=int(recipe['sample_rate_hz']);n=round(sr*float(recipe['duration_seconds']));t=np.arange(n,dtype=np.float64)/sr
    out=np.zeros(n,dtype=np.float64)
    for tone in recipe['source']['tones']:
        out+=float(tone['amplitude'])*np.cos(2*np.pi*float(tone['frequency_hz'])*t+float(tone['phase_radians']))
    transient=recipe['source']['transient'];out[int(transient['sample'])]+=float(transient['amplitude'])
    return out.astype(np.float32)


def stage(spec):
    return NonlinearStageSpec(spec['kind'],spec['mode'],int(spec['oversample']),drive_db=float(spec.get('drive_db',0.)),
                              threshold=float(spec.get('threshold',.7)),mix=float(spec['mix']))


def spectral(spec):
    tuning=fixture_pack()[spec['tuning_fixture']]
    return SpectralRetuneRequest(tuning_spec=tuning_to_spec(tuning),voices=(LatticeVoice(int(spec['degree']),tuple(spec['partial_ratios']),'benchmark'),),
        amount=float(spec['amount']),min_confidence=float(spec['min_confidence']),min_hz=float(spec['min_hz']),max_hz=float(spec['max_hz']),
        max_displacement_cents=float(spec['max_displacement_cents']),max_correction_slew_cents_per_second=float(spec['max_correction_slew_cents_per_second']))


def identity_spectral(base):
    d=base.to_dict();return SpectralRetuneRequest(tuning_spec=d['tuning_spec'],voices=base.voices,segments=base.segments,amount=0.,
        min_confidence=base.min_confidence,min_hz=base.min_hz,max_hz=base.max_hz,max_displacement_cents=base.max_displacement_cents,
        max_correction_slew_cents_per_second=base.max_correction_slew_cents_per_second,
        assignment_hysteresis_cents=base.assignment_hysteresis_cents,preserve_ambiguous=base.preserve_ambiguous)


def main():
    p=argparse.ArgumentParser();p.add_argument('--recipe',type=Path,default=ROOT/'examples/zg019_placement_benchmarks.json');p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    recipe=json.loads(args.recipe.read_text());placement=recipe['placement_fixture'];sr=int(placement['sample_rate_hz']);x=source_from_recipe(placement)
    sreq=spectral(placement['spectral_target']);a=stage(placement['stage_a']);b=stage(placement['stage_b']);family=run_family(x,sr,sreq,a,b)
    transient_sample=int(placement['source']['transient']['sample'])
    variants={name:{'spec':result.request.to_dict(),'audio':summarize_audio(result.audio,sr,target_root_hz=440.,transient_sample=transient_sample),
                    'spectral_changed_frames':result.diagnostics['spectral_changed_frames'],'declared_latency_samples':result.diagnostics['declared_latency_samples']}
              for name,result in family.items()}
    pairs={}
    names=('pre','inter','post')
    for i,left in enumerate(names):
        for right in names[i+1:]:pairs[left+'__'+right]=difference_metrics(family[left].audio,family[right].audio)

    zero_a=NonlinearStageSpec(a.kind,a.mode,a.oversample,drive_db=a.drive_db,threshold=a.threshold,mix=0.)
    zero_b=NonlinearStageSpec(b.kind,b.mode,b.oversample,drive_db=b.drive_db,threshold=b.threshold,mix=0.)
    identity=run_family(x,sr,identity_spectral(sreq),zero_a,zero_b)
    identity_rows={name:{'exact':bool(np.array_equal(result.audio,x)),'sha256_f32le':summarize_audio(result.audio,sr)['sha256_f32le'],
                         'declared_latency_samples':result.diagnostics['declared_latency_samples']} for name,result in identity.items()}

    alias=recipe['alias_fixture'];at=np.arange(round(alias['sample_rate_hz']*alias['duration_seconds']),dtype=np.float64)/alias['sample_rate_hz']
    ax=float(alias['source_amplitude'])*np.sin(2*np.pi*float(alias['source_tone_hz'])*at);sh=alias['shaper']
    alias_errors=reference_error(ax,kind=sh['kind'],drive_db=float(sh['drive_db']),mix=float(sh['mix']))
    alias_rows={str(k):v for k,v in alias_errors.items()}

    harmonic_values=[variants[n]['audio']['target_harmonic_power_fraction'] for n in names]
    transient_peaks=[variants[n]['audio']['transient']['window_peak'] for n in names]
    rms_values=[variants[n]['audio']['rms_dbfs'] for n in names]
    failures=[]
    if not all(row['exact'] and row['declared_latency_samples']==0 for row in identity_rows.values()):failures.append('identity placement paths did not align exactly')
    if not all(v['rms_difference']>1e-7 for v in pairs.values()):failures.append('placement order failed to create measurable controlled differences')
    if max(harmonic_values)-min(harmonic_values)<=1e-7:failures.append('placement harmonic products were not measurably distinct')
    if max(transient_peaks)-min(transient_peaks)<=1e-7:failures.append('placement transient shape was not measurably distinct')
    if max(rms_values)-min(rms_values)<=1e-7:failures.append('placement level was not measurably distinct')
    if not alias_errors[4]['rms_error']<alias_errors[2]['rms_error']<alias_errors[1]['rms_error']:failures.append('oversampling did not converge monotonically toward 8x reference')
    if not all(v['spec']['output_policy']['normalization']=='none' and v['spec']['output_policy']['master_gain_db']==0 for v in variants.values()):failures.append('hidden output normalization/gain detected')
    report={'scope':'deterministic synthetic engineering evidence; no preferred sound or listening claim','platform':platform.platform(),'python':sys.version,
            'recipe':recipe,'source':summarize_audio(x,sr,target_root_hz=440.,transient_sample=transient_sample),'variants':variants,
            'pairwise_differences':pairs,'identity':identity_rows,'alias_reference':{'reference_factor':alias['reference_factor'],'errors':alias_rows},
            'observed_spreads':{'target_harmonic_fraction':max(harmonic_values)-min(harmonic_values),'transient_peak':max(transient_peaks)-min(transient_peaks),
                                'rms_db':max(rms_values)-min(rms_values)},'acceptance_failures':failures}
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    if failures:raise SystemExit('ZG-019 evidence failed: '+'; '.join(failures))

if __name__=='__main__':main()
