"""Restore original 3A/3B packets from preserved bytes; never run research code.
Use --repository for a clone containing the pinned base, or --base-source-zip
for a complete tracked-source ZIP with exactly the pinned tree. Output must not
exist. Python stdlib only. Exact ZIP reconstruction was verified with zlib 1.3.1.
"""
from pathlib import Path, PurePosixPath
import argparse, base64, hashlib, io, json, lzma, stat, subprocess, zipfile, zlib


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git_oid(kind, raw):
    return hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def safe(name):
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name:
        raise ValueError('Unsafe path: '+name)
    return name


def inventory(files):
    rows = []
    tree = {}
    for name, (mode, raw) in sorted(files.items()):
        safe(name)
        blob = git_oid('blob', raw)
        rows.append(dict(path=name, mode=mode, git_blob=blob,
                         sha256=digest(raw), bytes=len(raw)))
        node = tree
        parts = name.split('/')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = (mode, blob)
    def walk(node):
        raw = b''
        for name, value in sorted(node.items(), key=lambda x:
                (x[0]+('/' if isinstance(x[1], dict) else '')).encode()):
            mode, sha = ('40000', walk(value)) if isinstance(value, dict) else value
            raw += mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(sha)
        return git_oid('tree', raw)
    return rows, walk(tree)


def load_base(args, base):
    if args.base_source_zip:
        with zipfile.ZipFile(args.base_source_zip) as z:
            if z.testzip() is not None:
                raise ValueError('Base source ZIP CRC failure')
            files = {}
            for i in z.infolist():
                if i.is_dir():
                    continue
                mode_bits = i.external_attr >> 16
                mode = '120000' if stat.S_ISLNK(mode_bits) else (
                    '100755' if mode_bits & 0o111 else '100644')
                if i.filename in files:
                    raise ValueError('Duplicate base ZIP path')
                files[safe(i.filename)] = (mode, z.read(i))
            return files
    repo = str(args.repository)
    raw = subprocess.run(['git', '-C', repo, 'ls-tree', '-rz', base],
        check=True, capture_output=True, timeout=30).stdout
    entries = []
    for record in raw.split(b'\0'):
        if not record:
            continue
        head, name = record.split(b'\t', 1)
        mode, kind, sha = head.decode().split()
        if kind != 'blob':
            raise ValueError('Unsupported non-blob base entry')
        entries.append((safe(name.decode()), mode, sha))
    req = ''.join(sha+'\n' for _, _, sha in entries).encode()
    stream = io.BytesIO(subprocess.run(['git', '-C', repo, 'cat-file', '--batch'],
        input=req, check=True, capture_output=True, timeout=30).stdout)
    files = {}
    for name, mode, expected in entries:
        sha, kind, size = stream.readline().decode().strip().split()
        if sha != expected or kind != 'blob':
            raise ValueError('Git batch binding mismatch')
        data = stream.read(int(size))
        if stream.read(1) != b'\n' or git_oid('blob', data) != expected:
            raise ValueError('Git blob integrity failure')
        files[name] = (mode, data)
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--saved-directory', type=Path, default=Path(__file__).parent)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--repository', type=Path)
    group.add_argument('--base-source-zip', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists():
        raise FileExistsError('Output must not exist; no overwrite is permitted')
    root = args.saved_directory
    manifest = json.loads((root/'CAPSULE-MANIFEST.json').read_text())
    parts = []
    for part in manifest['parts']:
        raw = (root/safe(part['path'])).read_bytes()
        assert len(raw) == part['bytes'] and digest(raw) == part['sha256']
        assert git_oid('blob', raw) == part['git_blob']
        parts.append(raw)
    packed = b''.join(parts)
    assert len(packed) == manifest['capsule_bytes']
    assert digest(packed) == manifest['capsule_sha256']
    decoded = lzma.decompress(packed)
    assert len(decoded) == manifest['decompressed_bytes']
    assert digest(decoded) == manifest['decompressed_sha256']
    cap = json.loads(decoded)
    assert cap['base_commit'] == manifest['base_commit']
    files = load_base(args, cap['base_commit'])
    rows, actual_tree = inventory(files)
    assert actual_tree == cap['base_tree'] == manifest['base_tree']
    inv = (json.dumps(rows, indent=2)+'\n').encode()
    assert digest(inv) == cap['inventory_sha256']
    assert len(inv) == cap['inventory_bytes']
    objects = {h: text.encode('utf-8') for h, text in cap['objects_utf8'].items()}
    assert all(digest(raw) == h for h, raw in objects.items())
    archives = {}
    counts = {}
    for label in ['3A', '3B']:
        recipe = cap['zip_recipes'][label]
        restored = {}
        target = args.output/recipe['prefix'].rstrip('/')
        for name, entry in cap['files'][label].items():
            safe(name)
            if 'archive' in entry:
                raw = archives[entry['archive']]
            elif 'derived' in entry:
                assert entry['derived'] == 'base-inventory-v1'
                raw = inv
            elif 'base_path' in entry:
                raw = files[entry['base_path']][1]
                assert git_oid('blob', raw) == entry['git_blob']
            else:
                raw = objects[entry['sha256']]
            assert digest(raw) == entry['sha256'] and len(raw) == entry['bytes']
            restored[name] = raw
        # Verify original checksums, including the nested archive, without running
        # either packet's verifier (which may perform numerical checks).
        sums = {}
        for line in restored['SHA256SUMS'].decode().splitlines():
            h, name = line.split('  ', 1)
            name = name.removeprefix('./')
            assert digest(restored[name]) == h
            sums[name] = h
        assert set(sums) == set(restored)-{'SHA256SUMS'}
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED,
                             compresslevel=recipe['compression_level']) as z:
            z.comment = base64.b64decode(recipe['comment_b64'])
            for entry in recipe['entries']:
                zi = zipfile.ZipInfo(entry['filename'], tuple(entry['date_time']))
                for key, value in entry.items():
                    if key not in ['filename', 'date_time', 'comment_b64', 'extra_b64']:
                        setattr(zi, key, value)
                zi.comment = base64.b64decode(entry['comment_b64'])
                zi.extra = base64.b64decode(entry['extra_b64'])
                name = entry['filename'][len(recipe['prefix']):]
                z.writestr(zi, restored[name], compress_type=zi.compress_type,
                           compresslevel=recipe['compression_level'])
        raw_archive = out.getvalue()
        assert digest(raw_archive) == recipe['sha256'], (
            'Archive encoding mismatch; use pinned zlib 1.3.1, not new fixtures')
        assert len(raw_archive) == recipe['bytes']
        archives[label] = raw_archive
        for name, raw in restored.items():
            p = target/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)
        (args.output/f'zaaggenz_{label}_packet.zip').write_bytes(raw_archive)
        counts[label] = len(restored)
    result = dict(passed=True, operation='byte restoration and hashes only; no tests',
                  base_commit=cap['base_commit'], base_tree=actual_tree,
                  base_files=len(files), original_member_counts=counts,
                  archives_sha256={k:digest(v) for k,v in archives.items()},
                  zlib=zlib.ZLIB_RUNTIME_VERSION)
    (args.output/'RESTORATION-VERIFIED.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
