from __future__ import annotations
import argparse, base64, hashlib, lzma, pathlib, tarfile, io

EXPECTED_SHA256='eaf5d3ab822dfa121cd3b795d62619af9e62c041fb02de19f8dbeafb0014c919'
PREFIX='runtime_source.tar.xz.b64.'

def materialize(here: pathlib.Path, dest: pathlib.Path, replace=False):
    parts=sorted(here.glob(PREFIX+'[0-9][0-9]'))
    if [p.name for p in parts] != [f'{PREFIX}{i:02d}' for i in range(17)]:
        raise RuntimeError('expected exactly runtime source parts 00..16')
    encoded=''.join(''.join(p.read_text(encoding='ascii').split()) for p in parts)
    packed=base64.b64decode(encoded, validate=True)
    got=hashlib.sha256(packed).hexdigest()
    if got != EXPECTED_SHA256:
        raise RuntimeError(f'payload SHA-256 mismatch: {got}')
    raw=lzma.decompress(packed)
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as tf:
        members=tf.getmembers()
        for m in members:
            q=pathlib.PurePosixPath(m.name)
            if m.issym() or m.islnk() or q.is_absolute() or '..' in q.parts:
                raise RuntimeError(f'unsafe tar member: {m.name}')
            if not (m.isfile() or m.isdir()):
                raise RuntimeError(f'unsupported tar member: {m.name}')
        dest.mkdir(parents=True, exist_ok=True)
        for m in members:
            target=dest/pathlib.PurePosixPath(m.name)
            if m.isfile() and target.exists() and not replace:
                raise RuntimeError(f'refusing existing file: {target}')
        tf.extractall(dest, filter='data')
    return len([m for m in members if m.isfile()]), got

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',type=pathlib.Path,default=pathlib.Path('.'))
    ap.add_argument('--replace',action='store_true')
    a=ap.parse_args()
    count,sha=materialize(pathlib.Path(__file__).resolve().parent,a.out,a.replace)
    print(f'verified {sha}; materialized {count} runtime files into {a.out}')
