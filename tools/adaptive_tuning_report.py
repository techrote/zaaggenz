"""Generate deterministic ZG-020 dissonance-map/adaptive-tuning engineering evidence."""
from __future__ import annotations
import argparse,json,platform,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from zaaggenz_tuning import (AdaptiveState,AdaptiveTuningRequest,AdaptiveVoice,AdaptiveWeights,IntervalGrid,ab_recipe,
    commit_proposal,harmonic_spectrum,interaction_roughness,propose_adaptive_tuning,sensitivity_candidates)

def make_request(recipe,desired,*,max_total=None,max_step=None,root_lock=True,confidence=1.):
    root_hz=recipe['dissonance']['root_hz'];a=recipe['adaptive'];nominal=a['nominal_interval_cents']
    root=AdaptiveVoice('root',0.,harmonic_spectrum('rootspec',root_hz,partials=recipe['dissonance']['partials']),'root')
    upper=AdaptiveVoice('upper',nominal,harmonic_spectrum('upperspec',root_hz*2**(nominal/1200.),partials=recipe['dissonance']['partials'],confidence=confidence))
    w=a['weights']
    return AdaptiveTuningRequest((root,upper),tuple(a['candidate_intervals_cents']),'root',desired_tension=desired,root_lock=root_lock,
        max_total_drift_cents=a['max_total_drift_cents'] if max_total is None else max_total,
        max_step_cents=a['max_step_cents'] if max_step is None else max_step,search_step_cents=a['search_step_cents'],
        min_separation_cents=a['min_separation_cents'],weights=AdaptiveWeights(w['tension'],w['voice_leading'],w['drift'],w['candidate_proximity']))

def nearest(candidates,target):return min(candidates,key=lambda x:abs(x.cents-target))

def main():
    p=argparse.ArgumentParser();p.add_argument('--recipe',type=Path,default=ROOT/'examples/zg020_adaptive_tuning.json');p.add_argument('--out',type=Path,required=True);args=p.parse_args();recipe=json.loads(args.recipe.read_text())
    d=recipe['dissonance'];grid=IntervalGrid(**d['grid']);harmonic=harmonic_spectrum('harmonic',d['root_hz'],partials=d['partials'],amplitude_power=d['amplitude_power'],stretch=d['harmonic_stretch']);stretched=harmonic_spectrum('stretched',d['root_hz'],partials=d['partials'],amplitude_power=d['amplitude_power'],stretch=d['stretched_stretch'])
    sens=d['sensitivity'];hcurve,hcand,hmeta=sensitivity_candidates(harmonic,harmonic,grid,bandwidth_scales=tuple(sens['bandwidth_scales']),amplitude_exponents=tuple(sens['amplitude_exponents']),match_tolerance_cents=sens['match_tolerance_cents'],min_stability=sens['min_stability']);scurve,scand,smeta=sensitivity_candidates(stretched,stretched,grid,bandwidth_scales=tuple(sens['bandwidth_scales']),amplitude_exponents=tuple(sens['amplitude_exponents']),match_tolerance_cents=sens['match_tolerance_cents'],min_stability=sens['min_stability'])
    hf=nearest(hcand,702.);sf=nearest(scand,710.)
    loud=harmonic_spectrum('loud',d['root_hz'],partials=d['partials'],amplitude_power=d['amplitude_power']);loud=type(loud)(loud.id,loud.frequencies_hz,tuple(x*100 for x in loud.amplitudes),loud.confidence,loud.source)
    gain_base=interaction_roughness(harmonic,harmonic,702.).value;gain_loud=interaction_roughness(loud,harmonic,702.).value

    a=recipe['adaptive'];low=propose_adaptive_tuning(make_request(recipe,a['low_tension']));high=propose_adaptive_tuning(make_request(recipe,a['high_tension']))
    seq_req=make_request(recipe,a['sequence_tension'],max_total=a['sequence_max_total_drift_cents'],max_step=a['sequence_max_step_cents']);state=AdaptiveState();history=[]
    for _ in range(a['sequence_steps']):
        proposal=propose_adaptive_tuning(seq_req,state);history.append({'step':state.step_index,'proposal':proposal.offset_mapping(),'status':proposal.status});state=commit_proposal(proposal)
    low_conf=propose_adaptive_tuning(make_request(recipe,0.,confidence=.2));moving_root=propose_adaptive_tuning(make_request(recipe,a['high_tension'],root_lock=False))

    lock_req=make_request(recipe,a['low_tension'],max_total=a['max_total_drift_cents'],max_step=a['max_step_cents'],root_lock=True)
    lock_state=AdaptiveState((('root',18.),('upper',0.)),7);lock_history=[]
    for _ in range(4):
        before=lock_state.mapping()['root'];proposal=propose_adaptive_tuning(lock_req,lock_state);after=proposal.offset_mapping()['root']
        lock_history.append({'step':lock_state.step_index,'before_root_cents':before,'after_root_cents':after,'status':proposal.status,'transition':proposal.search['root_lock_transition']})
        if proposal.status!='proposed':break
        lock_state=commit_proposal(proposal)
        if abs(after)<=1e-9:break

    report={'scope':recipe['scope'],'platform':platform.platform(),'python':sys.version,'recipe':recipe,
        'dissonance':{'method':hcurve.model.to_dict(),'harmonic_fifth_candidate':hf.to_dict(),'stretched_fifth_candidate':sf.to_dict(),
                      'harmonic_sensitivity':hmeta,'stretched_sensitivity':smeta,'global_gain_invariance_abs_error':abs(gain_base-gain_loud)},
        'adaptive':{'low_tension':low.to_dict(),'high_tension':high.to_dict(),'low_tension_ab':ab_recipe(low),'high_tension_ab':ab_recipe(high),
                    'sequence_history':history,'sequence_final_state':state.to_dict(),'low_confidence':low_conf.to_dict(),'moving_root':moving_root.to_dict(),
                    'root_lock_transition_history':lock_history,'root_lock_transition_final_state':lock_state.to_dict()},
        'interpretation':'engineering compatibility/tuning proposals only; candidate minima and objective values do not predict liking or style'}
    failures=[]
    if abs(hf.cents-702.)>4.:failures.append('harmonic fifth-region minimum moved outside fixture tolerance')
    if abs(sf.cents-710.)>4. or sf.cents<=hf.cents+3.:failures.append('stretched fixture did not shift the fifth-region candidate')
    if report['dissonance']['global_gain_invariance_abs_error']>1e-12:failures.append('global gain changed normalized interaction score')
    lo=low.offset_mapping();hi=high.offset_mapping()
    if low.status!='proposed' or lo['root']!=0 or not lo['upper']<0:failures.append('low-tension bounded fifth correction failed')
    if high.status!='proposed' or hi['upper']==lo['upper'] or abs(high.objective['predicted_tension']-a['high_tension'])>abs(low.objective['predicted_tension']-a['high_tension'])+1e-12:failures.append('desired tension did not alter the proposal as intended')
    if any(abs(v)>a['sequence_max_total_drift_cents']+1e-9 for v in state.mapping().values()):failures.append('sequence exceeded cumulative drift bound')
    if low_conf.status!='abstained':failures.append('low-confidence input did not abstain')
    if moving_root.status!='proposed':failures.append('moving-root mode failed to produce a bounded proposal')
    if not low.request.to_dict()['amplitude_policy'].startswith('immutable'):failures.append('adaptive amplitude policy was not immutable')
    if not lock_history or any(row['status']!='proposed' for row in lock_history):failures.append('root-lock transition did not remain proposal-valid')
    if any(abs(row['after_root_cents']-row['before_root_cents'])>a['max_step_cents']+1e-9 for row in lock_history):failures.append('root-lock transition exceeded max step')
    if any(abs(row['after_root_cents'])>abs(row['before_root_cents'])+1e-9 for row in lock_history):failures.append('root-lock transition moved away from zero')
    if abs(lock_state.mapping()['root'])>1e-9:failures.append('root-lock transition did not converge to zero')
    report['acceptance_failures']=failures;args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    if failures:raise SystemExit('ZG-020 evidence failed: '+'; '.join(failures))
if __name__=='__main__':main()
