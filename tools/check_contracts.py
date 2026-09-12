"""Cross-platform contract and recovered-baseline verification from repository root."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', action='store_true', help='Also run all 13 inherited smoke scripts')
    p.add_argument('--report', type=Path)
    args = p.parse_args()
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(ROOT), str(ROOT/'app'))),
               PYTHONUTF8='1', TERM='xterm', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    commands = [([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/contracts', '-v'], ROOT),
                (['node', '--check', 'zaaggenz_contracts/canonical.mjs'], ROOT)]
    if args.baseline:
        commands.extend([([sys.executable, '-m', 'py_compile', 'webapp.py', 'uh.py',
                            *[str(x.relative_to(ROOT/'app')) for x in sorted((ROOT/'app/uptempo_harmony').glob('*.py'))]], ROOT/'app'),
                         (['node', '--check', 'web/static/app.js'], ROOT/'app')])
        smoke = sorted((ROOT/'app/tests').glob('*_smoke.py'))
        if len(smoke) != 13:
            raise SystemExit('Expected all 13 recovered smoke scripts; materialize verified G0 first')
        commands.extend(([sys.executable,str(x.relative_to(ROOT/'app'))],ROOT/'app') for x in smoke)
    rows=[]
    for command, cwd in commands:
        print('RUN', ' '.join(command), flush=True)
        t=time.perf_counter()
        cp=subprocess.run(command,cwd=cwd,env=env,capture_output=True,text=True,encoding='utf-8',timeout=180)
        print(cp.stdout+cp.stderr,flush=True)
        rows.append(dict(command=[Path(command[0]).name,*command[1:]],cwd=str(cwd.relative_to(ROOT)),
                         returncode=cp.returncode,seconds=time.perf_counter()-t,output=cp.stdout+cp.stderr))
        if cp.returncode:
            break
    passed=all(row['returncode']==0 for row in rows) and len(rows)==len(commands)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(dict(passed=passed,python=sys.version,platform=platform.platform(),checks=rows),indent=2)+'\n',encoding='utf-8')
    raise SystemExit(0 if passed else 1)


if __name__=='__main__':main()
