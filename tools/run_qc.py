"""Generate deterministic automated QC report; not a listening-quality verdict."""
import argparse,json,platform,sys
from pathlib import Path
from zaaggenz_qc import fixture,fixture_names,diagnose

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=12000);args=p.parse_args()
    rows=[]
    for name in fixture_names():
        f=fixture(name,args.sample_rate,.5);rows.append({'fixture':name,'generation':f.generation,**diagnose(f.data,f.sample_rate_hz,'automated')})
    result={'version':'zg-qc-report-v1','evaluation_mode':'automated','sample_rate_hz':args.sample_rate,
            'listening_based':False,'python':sys.version.split()[0],'platform':platform.platform(),'fixtures':rows,
            'warning':'Synthetic numerical QC only; not a perceptual/artistic score and not reference-track ground truth.'}
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8');print(json.dumps({'fixtures':len(rows),'sample_rate_hz':args.sample_rate}))
if __name__=='__main__':main()
