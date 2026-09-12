"""Reproduce independent preliminary evidence, not the missing zaaggenz instrument.

python research/preflight-2026-09-12/run.py --out /tmp/zg-results
Optional: --audio-dir /local/private/music --planning /local/paired_summary.json
"""
from __future__ import annotations
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import numpy as np
import scipy
from common import METHOD, SEED, dump, sha
import spectral_probes, musical_probes, design_simulation, residual_probe


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=Path(__file__).parent/'results')
    parser.add_argument('--audio-dir',type=Path)
    parser.add_argument('--planning',type=Path)
    parser.add_argument('--replicates',type=int,default=2000)
    args=parser.parse_args()
    if not 100<=args.replicates<=10000: parser.error('replicates must be 100..10000')
    out=args.out;out.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    spectral_probes.main(out)
    musical_probes.main(out)
    design_simulation.run_statistics(out,args.replicates)
    design_simulation.run_job_model(out)
    residual_probe.run(out)
    reference={'status':'not requested; no source audio required for synthetic probes'}
    if args.audio_dir:
        import reference_precompute
        ref=reference_precompute.main(args.audio_dir,out,args.planning)
        reference={'status':'analysed locally; source audio never copied',
                   'tracks':[{'id':r['id'],'sha256':r['sha256']} for r in ref['tracks']],
                   'missing_inputs':ref['missing_inputs']}
    # Data hashes are reproducible in this environment; wallclock is not a result hash.
    files=[p for p in sorted(out.iterdir()) if p.suffix in ('.csv','.json') and p.name not in ('MANIFEST.json','RUN_ENVIRONMENT.json') and (args.audio_dir or not p.name.startswith('reference_'))]
    dump(out/'MANIFEST.json',{'method':METHOD,'seed':SEED,'synthetic_only':not bool(args.audio_dir),
          'reference_run':reference,'files':{p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in files},
          'source_files':{p.name:sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))},
          'precision_note':'CSV/JSON store computed values; -300 dB is a reporting floor, not an exact residual measurement. Fixture identities are not production acceptance.'})
    ffmpeg=None
    if args.audio_dir:
        ffmpeg=subprocess.check_output(['ffmpeg','-version'],text=True).splitlines()[0]
    dump(out/'RUN_ENVIRONMENT.json',{'python':sys.version.split()[0],'numpy':np.__version__,'scipy':scipy.__version__,
          'platform':platform.platform(),'machine':platform.machine(),'ffmpeg':ffmpeg,
          'elapsed_seconds':time.perf_counter()-started,
          'threads':{k:os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS')},
          'reproduction':'Numerical tolerances across environments; bitwise file hashes only claimed in recorded environment.'})
    print(f'{len(files)} result files written to {out}. No source audio emitted.')


if __name__=='__main__': main()
