"""Fail if known private recordings or obvious private media are Git-tracked."""
import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
reg=json.loads((ROOT/'references/private_registry_v1.json').read_text(encoding='utf-8'));known={a['sha256'] for a in reg['assets']}
raw=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT);paths=[Path(x.decode('utf-8')) for x in raw.split(b'\0') if x]
bad=[]
for rel in paths:
    p=ROOT/rel
    if rel.suffix.lower() in {'.mp3','.webm','.flac','.m4a','.ogg','.aac'}:bad.append((str(rel),'tracked compressed audio'))
    if p.is_file() and p.stat().st_size<=64*1024*1024:
        h=hashlib.sha256(p.read_bytes()).hexdigest()
        if h in known:bad.append((str(rel),'matches registered private reference hash'))
if bad:
    print(json.dumps({'safe':False,'violations':bad},indent=2));sys.exit(2)
print(json.dumps({'safe':True,'tracked_files_checked':len(paths),'registered_private_hashes':len(known)}))
