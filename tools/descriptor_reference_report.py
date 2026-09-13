"""Local-only ZG-014 descriptor calibration on identity-verified private annotated excerpts.

Writes descriptor JSON only. Source audio and local locator paths are never copied into the report.
"""
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from zaaggenz_contracts import loads
from zaaggenz_descriptors import DescriptorAnalysisSpec,analyse_descriptors
from zaaggenz_reference.registry import load_registry,load_locators,resolve_assets,require_exact_resolution
from zaaggenz_reference.annotation import validate_annotation

def decode_excerpt(path,start_s,duration_s,sr):
    if not 0<=start_s or not 0<duration_s<=30:raise ValueError('excerpt span outside local calibration bound')
    cmd=['ffmpeg','-nostdin','-v','error','-ss',f'{start_s:.9f}','-i',str(path),'-t',f'{duration_s:.9f}','-map','0:a:0','-ar',str(sr),'-ac','2','-c:a','pcm_f32le','-f','f32le','pipe:1']
    raw=subprocess.check_output(cmd,timeout=90);a=np.frombuffer(raw,dtype='<f4')
    if len(a)%2:raise RuntimeError('decoded stereo sample count mismatch')
    return a.reshape(-1,2)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--locators',type=Path,required=True);p.add_argument('--registry',type=Path,default=ROOT/'references/private_registry_v1.json');p.add_argument('--annotations',type=Path,default=ROOT/'references/paired_suggestions_v1.json');p.add_argument('--out',type=Path,required=True);p.add_argument('--analysis-sr',type=int,default=12000);p.add_argument('--max-segments',type=int,default=12);a=p.parse_args()
    registry=load_registry(a.registry);locators=load_locators(a.locators);resolved=require_exact_resolution(resolve_assets(registry,locators));paths={r['id']:r['path'] for r in resolved};assets={r['id']:r for r in registry['assets']};annotation=loads(a.annotations.read_bytes());validate_annotation(annotation,set(assets))
    rows=[];spec=DescriptorAnalysisSpec(max_samples=262144)
    for seg in annotation['segments'][:max(0,min(a.max_segments,64))]:
        meta=assets[seg['asset_id']];native=meta['native']['sample_rate_hz'];start=seg['start_sample']/native;duration=(seg['end_sample']-seg['start_sample'])/native;pcm=decode_excerpt(paths[seg['asset_id']],start,duration,a.analysis_sr)
        result=analyse_descriptors(pcm,a.analysis_sr,spec=spec)
        rows.append({'segment_id':seg['id'],'asset_id':seg['asset_id'],'source_sha256':meta['sha256'],'annotation_source':seg['source'],'annotation_confidence':seg['confidence'],'correspondence_group':seg['correspondence_group'],'section_function':seg['section_function'],'label':seg['label'],'native_sample_span':[seg['start_sample'],seg['end_sample']],'analysis_sample_rate_hz':a.analysis_sr,'descriptor_bundle':result.descriptors.to_dict()})
    report={'scope':'local identity-verified private-reference descriptor calibration; no source audio, locator path, correspondence validation or preference inference','annotation_file':str(a.annotations.relative_to(ROOT)) if a.annotations.is_relative_to(ROOT) else a.annotations.name,'segments':rows,'relations':annotation['relations']}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8');print(json.dumps({'segments':len(rows),'out':str(a.out)},indent=2))
if __name__=='__main__':main()
