"""Generate deterministic ZG-023 inspector demo-fixture evidence without applying the transform."""
from __future__ import annotations
import argparse,json,platform,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_inspector import InspectorService

def main():
    p=argparse.ArgumentParser();p.add_argument('--sample-rate',type=int,default=48000);p.add_argument('--out',type=Path,required=True);args=p.parse_args();service=InspectorService(args.sample_rate,demo_fixture=True)
    try:
        state=service.state();snap=state['snapshot'];failures=[]
        if state['source_binding']['kind']!='demo-fixture':failures.append('fixture evidence did not use explicit demo binding')
        if snap['method']['id']!='zg.harmonic_comb_inspector.v1':failures.append('wrong inspector method id')
        if len(snap['target_combs'])<2:failures.append('source/target comb evidence missing')
        if not snap['components'] or not any(x['requested_hz'] is not None for x in snap['components']):failures.append('requested/estimated/realised component evidence missing')
        if not snap['remainder']:failures.append('remainder timeline missing')
        if len(snap['compatibility'])<20:failures.append('interval compatibility map missing')
        if state['working']['revision_id']!=state['slots']['A']['revision_id']:failures.append('analysis auto-applied unexpectedly')
        if state['slots']['A']['audio_sha256']==state['slots']['B']['audio_sha256']:failures.append('fixture transform produced no comparison delta')
        if state['snapshot_stale']:failures.append('initial fixture unexpectedly stale')
        if not state['policy']['stale_result_rejected'] or state['policy']['analysis_auto_apply']:failures.append('non-destructive state policy wrong')
        report={'scope':'deterministic explicit synthetic engineering/UI evidence; no production-source, listening or preference claim','platform':platform.platform(),'python':sys.version,'sample_rate_hz':args.sample_rate,
                'source_binding':state['source_binding'],'state_policy':state['policy'],'slot_identities':state['slots'],'snapshot_id':snap['snapshot_id'],'stage_order':snap['stage_order'],
                'counts':{'target_combs':len(snap['target_combs']),'components':len(snap['components']),'remainder_bins':len(snap['remainder']),'compatibility_points':len(snap['compatibility']),**snap['uncertainty']['counts']},
                'controls':snap['controls'],'diagnostics':snap['diagnostics'],'compensation':state['compensation'],'acceptance_failures':failures}
        args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))
        if failures:raise SystemExit('ZG-023 inspector evidence failed: '+'; '.join(failures))
    finally:service.close()
if __name__=='__main__':main()
