"""Small, independent research utilities. Not production zaaggenz contracts."""
from __future__ import annotations
import csv, hashlib, json, math, pathlib
import numpy as np

METHOD = 'zg-preflight-2026-09-12-v1'
SEED = 20260912

def rms(x):
    x = np.asarray(x, dtype=np.float64)
    return float(np.sqrt(np.mean(x*x))) if x.size else 0.0

def db(x):
    return 20.0*math.log10(max(float(x), 1e-15))

def cents(ratio):
    a = np.asarray(ratio, float)
    if np.any(~np.isfinite(a)) or np.any(a <= 0):
        raise ValueError('ratios must be positive and finite')
    return 1200*np.log2(a)

def dump(path, obj):
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf-8')

def table(path, rows):
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError('cannot infer an empty table schema')
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

def sha(path):
    h = hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()

def mono(x):
    x = np.asarray(x, float)
    if x.ndim != 1 or not x.size or not np.isfinite(x).all():
        raise ValueError('nonempty finite mono vector required')
    return x
