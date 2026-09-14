#!/usr/bin/env python3
"""Run applicable inherited regressions with their existing assertions intact."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SUITES = ('contracts', 'project', 'jobs', 'qc', 'analysis', 'components', 'descriptors', 'dsp', 'spectral', 'tuning')

def main():
    env = dict(os.environ, PYTHONUTF8='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    env['PYTHONPATH'] = str(ROOT/'app') + os.pathsep + str(ROOT)
    for suite in SUITES:
        subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', f'tests/{suite}', '-v'], cwd=ROOT, env=env, check=True)
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_recovery.py', '-v'], cwd=ROOT, env=env, check=True)
    env['PYTHONPATH'] = str(ROOT/'app') + os.pathsep + str(ROOT)
    for path in sorted((ROOT/'app/tests').glob('*smoke.py')):
        print('Recovered acceptance:', path.name, flush=True)
        subprocess.run([sys.executable, str(path)], cwd=ROOT, env=env, check=True)
    subprocess.run(['node', 'tests/jobs/browser_transport.mjs'], cwd=ROOT, env=env, check=True)

if __name__ == '__main__': main()
