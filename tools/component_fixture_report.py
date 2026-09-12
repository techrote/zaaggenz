"""Generate deterministic ZG-013 synthetic quality measurements; not a listening score."""
from __future__ import annotations
import argparse,json,math,platform,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from scipy import signal
from zaaggenz_components import analyse_components

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=12000);a=p.parse_args();sr=a.sample_rate
    def tone(f,n,amp=.6):t=np.arange(n)/sr;return (amp*np.cos(2*np.pi*f*t+.2)).astype(np.float32)
    n=round(sr*1.5);t=np.arange(n)/sr
    fixtures={'tone440':tone(440,n),'chirp300_600':signal.chirp(t,300,t[-1],600).astype(np.float32),
              'noise':np.random.default_rng(4).normal(0,.2,n).astype(np.float32)}
    x=tone(330,n,.2);x[n//2]+=1;fixtures['tone_plus_impulse']=x
    rows={}
    for name,x in fixtures.items():
        r=analyse_components(x,sr);d=dict(r.diagnostics)
        if name=='tone440':
            fs=[f['frequency_hz'] for tr in r.bundle.to_dict()['tracks'] for f in tr['frames']]
            d['median_abs_frequency_error_hz']=float(np.median(np.abs(np.asarray(fs)-440))) if fs else None
        if name=='chirp300_600':
            tracks=r.bundle.to_dict()['tracks'];tr=max(tracks,key=lambda z:len(z['frames'])) if tracks else None;errors=[]
            if tr:
                for f in tr['frames']:
                    at=f['support']['anchor_sample']/sr;truth=300+300*at/t[-1];errors.append(abs(f['frequency_hz']-truth))
            d['median_abs_frequency_error_hz']=float(np.median(errors)) if errors else None
        rows[name]=d
    report={'scope':'synthetic deterministic fixtures; no perceptual quality claim','platform':platform.platform(),'python':sys.version,'sample_rate_hz':sr,'fixtures':rows}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
