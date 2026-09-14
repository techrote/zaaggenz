"""Generate deterministic ZG-021 engineering evidence from the frozen band-selective recipe."""
from __future__ import annotations
import argparse,hashlib,json,platform,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from zaaggenz_dsp import BitcrushSpec,CompressionSpec,compress,split_bands
from zaaggenz_spectral import (BandSelectiveRequest,BandSlotSpec,LatticeVoice,SpectralRetuneRequest,process_band_selective)
from zaaggenz_tuning import fixture_pack,tuning_to_spec

def rms(x):
    a=np.asarray(x,dtype=np.float64);return float(np.sqrt(np.mean(a*a))) if a.size else 0.
def sha(x):return hashlib.sha256(np.asarray(x,dtype='<f4',order='C').tobytes()).hexdigest()
def source(recipe):
    sr=int(recipe['sample_rate_hz']);n=round(sr*float(recipe['duration_seconds']));t=np.arange(n,dtype=np.float64)/sr;out=np.zeros(n)
    for row in recipe['source'].values():out+=float(row['amplitude'])*np.cos(2*np.pi*float(row['frequency_hz'])*t+float(row['phase_radians']))
    return out.astype(np.float32)
def spectral(recipe):
    s=recipe['spectral'];return SpectralRetuneRequest(tuning_spec=tuning_to_spec(fixture_pack()[s['tuning_fixture']]),voices=(LatticeVoice(int(s['degree']),tuple(s['partial_ratios']),'selected-band'),),amount=float(s['amount']),min_confidence=float(s['min_confidence']),min_hz=float(s['min_hz']),max_hz=float(s['max_hz']),max_displacement_cents=float(s['max_displacement_cents']),max_correction_slew_cents_per_second=float(s['max_correction_slew_cents_per_second']))
def slot(recipe):
    c=recipe['compression'];b=recipe['bitcrush']
    return BandSlotSpec(gain_db=float(recipe['gain_db']),compression=CompressionSpec(**c),bitcrush=BitcrushSpec(**b),spectral=spectral(recipe),stage_order=tuple(recipe['stage_order']))
def band_rms(x,sr,cross):return [rms(v) for v in split_bands(np.asarray(x,dtype=np.float64),sr,cross)]

def main():
    p=argparse.ArgumentParser();p.add_argument('--recipe',type=Path,default=ROOT/'examples/zg021_band_selective.json');p.add_argument('--out',type=Path,required=True);args=p.parse_args();recipe=json.loads(args.recipe.read_text());sr=int(recipe['sample_rate_hz']);cross=tuple(recipe['crossovers_hz']);x=source(recipe);s=slot(recipe)
    confined=process_band_selective(x,sr,BandSelectiveRequest(cross,(None,None,s,None),(True,True,True,True)))
    spill=process_band_selective(x,sr,BandSelectiveRequest(cross,(None,None,s,None),(True,True,False,True)))
    identity_slot=BandSlotSpec(gain_db=0.,compression=CompressionSpec(threshold_db=-40.,ratio=1.,attack_ms=1.,release_ms=20.,makeup_db=0.,wet=1.),bitcrush=BitcrushSpec(bit_depth=4,hold_samples=8,wet=0.))
    identity=process_band_selective(x,sr,BandSelectiveRequest(cross,(None,None,identity_slot,None)))
    delta_c=np.asarray(confined.audio)-x;delta_s=np.asarray(spill.audio)-x;cband=band_rms(delta_c,sr,cross);sband=band_rms(delta_s,sr,cross);srcbands=band_rms(x,sr,cross)
    protected={'sub':{'source_rms':srcbands[0],'confined_delta_rms':cband[0],'spill_delta_rms':sband[0]},'synthline_lowmid':{'source_rms':srcbands[1],'confined_delta_rms':cband[1],'spill_delta_rms':sband[1]},'air_reference':{'source_rms':srcbands[3],'confined_delta_rms':cband[3],'spill_delta_rms':sband[3]}}
    stage_rows=confined.slot_reports[2]['stages'];spectral_row=next(row for row in stage_rows if row['stage']=='spectral');compression_row=next(row for row in stage_rows if row['stage']=='compression');bitcrush_row=next(row for row in stage_rows if row['stage']=='bitcrush')
    control=np.concatenate((np.full(sr//10,.03),np.full(sr//10,.8),np.full(sr//10,.03))).astype(np.float64);control_result=compress(control,sr,CompressionSpec(threshold_db=-18.,ratio=4.,attack_ms=5.,release_ms=80.))
    report={'scope':recipe['scope'],'platform':platform.platform(),'python':sys.version,'recipe':recipe,'source_sha256':sha(x),'confined_sha256':sha(confined.audio),'spill_sha256':sha(spill.audio),
        'identity':{'exact':bool(np.array_equal(identity.audio,x)),'sha256':sha(identity.audio)},
        'confined':{'delta_rms_by_band':dict(zip(('sub','lowmid','highmid','air'),cband)),'band_report':confined.band_reports[2].to_dict(),'inspection':confined.inspection},
        'spill':{'delta_rms_by_band':dict(zip(('sub','lowmid','highmid','air'),sband)),'band_report':spill.band_reports[2].to_dict(),'inspection':spill.inspection},
        'protected_pockets':protected,
        'stages':{'spectral_changed_frames':spectral_row['diagnostics']['changed_frames'],'compression_max_gr_db':compression_row['diagnostics']['max_gain_reduction_db'],'compression_control_separate':compression_row['diagnostics']['control_signal_separate_from_audio'],'bitcrush_alias_policy':bitcrush_row['diagnostics']['alias_policy']},
        'compression_fixture':{'max_gain_reduction_db':control_result.diagnostics['max_gain_reduction_db'],'control_signal_separate_from_audio':control_result.diagnostics['control_signal_separate_from_audio']},
        'output_policy':confined.inspection['request']['output_policy']}
    failures=[];selected=max(cband[2],1e-15);limit=float(recipe['confined_leakage_limit_relative_to_selected'])
    if not report['identity']['exact']:failures.append('identity controls were not exact')
    if spectral_row['diagnostics']['changed_frames']<1:failures.append('selected-band spectral retune changed no frames')
    if cband[2]<=1e-5:failures.append('selected highmid delta was not measurable')
    if cband[0]>selected*limit or cband[1]>selected*limit or cband[3]>selected*limit:failures.append('confined selected-band delta exceeded protected-pocket leakage allowance')
    if sband[0]<=cband[0]*float(recipe['spill_gain_required_over_confined_sub']):failures.append('explicit spill did not measurably increase sub-band delta')
    if control_result.diagnostics['max_gain_reduction_db']<=1.:failures.append('compression control fixture produced no meaningful gain reduction')
    if not compression_row['diagnostics']['control_signal_separate_from_audio']:failures.append('compressor control signal separation not declared')
    if report['output_policy']['normalization']!='none' or report['output_policy']['master_gain_db']!=0:failures.append('hidden normalization/gain policy detected')
    report['acceptance_failures']=failures;args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    if failures:raise SystemExit('ZG-021 evidence failed: '+'; '.join(failures))
if __name__=='__main__':main()
