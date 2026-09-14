"""Deterministic ZG-018 engineering evidence; never a preference or pleasure claim."""
from __future__ import annotations
import argparse,hashlib,json,platform,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from zaaggenz_components import analyse_components
from zaaggenz_spectral import ChordnessRequest,CombTemplate,apply_chordness,cents_distance

def pcm_sha(x):return hashlib.sha256(np.asarray(x,dtype='<f4',order='C').tobytes()).hexdigest()
def tone(sr,f,duration=1.,amp=.45,phase=.2):
    t=np.arange(round(sr*duration),dtype=np.float64)/sr
    return (amp*np.cos(2*np.pi*f*t+phase)).astype(np.float32)
def mixture(sr,freqs):
    out=np.zeros(sr,dtype=np.float32)
    for i,f in enumerate(freqs):out+=tone(sr,f,amp=.28,phase=.17+i*.31)
    return out
def request(templates,mode,**kwargs):
    values=dict(selected_template_ids=tuple(x.id for x in templates),max_selected_templates=len(templates),min_confidence=.4,
                max_assignment_cents=180.,max_displacement_cents=100.,max_correction_slew_cents_per_second=2400.,
                max_gain_db=4.,max_gain_slew_db_per_second=60.)
    values.update(kwargs);return ChordnessRequest(tuple(templates),mode=mode,**values)

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=48000);a=p.parse_args();sr=a.sample_rate
    base=tone(sr,445.);base_analysis=analyse_components(base,sr);single=(CombTemplate('a',(440.,)),)
    off=apply_chordness(base_analysis,ChordnessRequest(single,mode='off'))
    reweight=apply_chordness(base_analysis,request(single,'reweight'))
    src=base_analysis.bundle.to_dict();rw=reweight.bundle.to_dict();freq_equal=True;phase_equal=True;amp_changes=0
    for ta,tb in zip(src['tracks'],rw['tracks']):
        for fa,fb in zip(ta['frames'],tb['frames']):
            freq_equal&=fa['frequency_hz']==fb['frequency_hz'];phase_equal&=fa['phases_radians']==fb['phases_radians'];amp_changes+=fa['amplitudes']!=fb['amplitudes']

    templates=(CombTemplate('low',(440.,),1),CombTemplate('high',(660.,),1));analysis=analyse_components(mixture(sr,(445.,665.)),sr)
    retuned=apply_chordness(analysis,request(templates,'retune'));hybrid=apply_chordness(analysis,request(templates,'hybrid'))
    active=[d for d in retuned.decisions if d.decision!='preserve' and d.target_hz is not None]
    before=float(np.median([d.assignment_distance_cents for d in active])) if active else None
    after=float(np.median([abs(cents_distance(d.realised_hz,d.target_hz)) for d in active])) if active else None
    assigned_templates=sorted({d.template_id for d in active});max_over=max((x['occupancy']-x['capacity'] for x in retuned.occupancy),default=0)

    local=(CombTemplate('local.a',(437.2,701.3),1),CombTemplate('local.b',(523.7,1003.7),1))
    local_result=apply_chordness(analyse_components(mixture(sr,(442.,706.)),sr),request(local,'retune',max_assignment_cents=220.,max_displacement_cents=160.))
    local_targets=sorted({d.target_hz for d in local_result.decisions if d.decision!='preserve' and d.target_hz is not None})

    report={'scope':'deterministic synthetic engineering evidence; not listening preference, pleasure, or source-track evidence',
            'platform':platform.platform(),'python':sys.version,'sample_rate_hz':sr,'method':'zg.multi_comb_chordness.v1',
            'off':{'source_sha256':pcm_sha(base),'output_sha256':pcm_sha(off.audio),'exact':bool(np.array_equal(base,off.audio))},
            'reweight':{'frequency_exact':bool(freq_equal),'phase_exact':bool(phase_equal),'amplitude_changed_frames':int(amp_changes),
                        'retuned_frames':reweight.diagnostics['retuned_frames'],'reweighted_frames':reweight.diagnostics['reweighted_frames']},
            'multi_comb':{'assigned_templates':assigned_templates,'active_frames':len(active),'median_assignment_distance_before_cents':before,
                          'median_realised_target_error_after_cents':after,'max_capacity_excess':int(max_over)},
            'hybrid':{'target_comb_fit_before':hybrid.diagnostics['target_comb_fit_before'],'target_comb_fit_after':hybrid.diagnostics['target_comb_fit_after'],
                      'roughness_before':hybrid.diagnostics['roughness_before'],'roughness_after':hybrid.diagnostics['roughness_after'],
                      'objective_interpretation':hybrid.objective_after['interpretation']},
            'local_targets':{'declared_hz':[437.2,701.3,523.7,1003.7],'assigned_hz':local_targets},
            'ownership':{'transient_identical':bool(np.array_equal(hybrid.transient,analysis.transient)),
                         'residual_identical':bool(np.array_equal(hybrid.residual,analysis.residual))},
            'finite_output':bool(np.isfinite(hybrid.audio).all() and np.isfinite(local_result.audio).all())}
    failures=[]
    if not report['off']['exact']:failures.append('off path not exact')
    if not freq_equal or not phase_equal or amp_changes<1 or reweight.diagnostics['retuned_frames']!=0:failures.append('reweight-only invariant failed')
    if assigned_templates!=['high','low'] or not active or max_over>0:failures.append('multi-comb/capacity assignment failed')
    if before is None or after is None or not after<before:failures.append('retune did not move assigned components toward targets')
    if hybrid.diagnostics['target_comb_fit_after'] is None or hybrid.diagnostics['target_comb_fit_after']<=hybrid.diagnostics['target_comb_fit_before']:failures.append('hybrid did not improve declared comb fit')
    if 437.2 not in local_targets or 701.3 not in local_targets:failures.append('explicit local targets were not addressable')
    if not report['ownership']['transient_identical'] or not report['ownership']['residual_identical']:failures.append('remainder ownership changed')
    if not report['finite_output']:failures.append('nonfinite output')
    report['acceptance_failures']=failures;a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    if failures:raise SystemExit('ZG-018 evidence failed: '+'; '.join(failures))
if __name__=='__main__':main()
