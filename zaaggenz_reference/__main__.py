import argparse,json,sys
from pathlib import Path
from .registry import load_registry,load_locators,resolve_assets
from .analysis import analyse_file,compare_planning

ROOT=Path(__file__).resolve().parents[1]


def _strict_json_dumps(value,**kwargs):
    """Serialize evidence as RFC-compatible JSON; NaN/Infinity are forbidden."""
    return json.dumps(value,allow_nan=False,**kwargs)


def main():
    p=argparse.ArgumentParser(description='Verify private references without copying source audio')
    p.add_argument('--registry',type=Path,default=ROOT/'references/private_registry_v1.json');p.add_argument('--locators',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--analyse',action='store_true')
    a=p.parse_args();reg=load_registry(a.registry);loc=load_locators(a.locators);rows=resolve_assets(reg,loc);byid={x['id']:x for x in reg['assets']};out=[];ok=True
    for row in rows:
        clean={k:v for k,v in row.items() if k!='path'}
        if row['status']!='ok':ok=False
        elif a.analyse:
            obs=analyse_file(loc['paths'][row['id']]);clean['analysis']=obs;clean['planning_comparison']=compare_planning(obs,byid[row['id']]['planning']);ok &= clean['planning_comparison']['pass']
        out.append(clean)
    report={'version':'zg-private-reference-verification-v1','source_paths_included':False,'all_ok':bool(ok),'assets':out,
            'warning':'Content identity is the hard source gate. Descriptor agreement is dependency-tolerant and does not imply provenance, rights, chord labels, genre labels or a production chain.'}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(_strict_json_dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8');print(_strict_json_dumps({'all_ok':bool(ok),'assets':len(out)}));return 0 if ok else 2
if __name__=='__main__':sys.exit(main())
