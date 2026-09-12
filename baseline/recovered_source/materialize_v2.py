"""Recover the exact, immutable v1.2.1 runtime; never repair a checksum in place."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import lzma
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile

EXPECTED_SHA256 = "eaf5d3ab822dfa121cd3b795d62619af9e62c041fb02de19f8dbeafb0014c919"
PREFIX = "runtime_source.tar.xz.b64."
FULL_PART_CHARS = 7000
FINAL_PART_CHARS = 6608
PART_COUNT = 17
MAX_TAR_BYTES = 2 * 1024 * 1024


def _read_encoded(here: Path) -> str:
    chunks = []
    for i in range(PART_COUNT):
        path = here / f"{PREFIX}{i:02d}"
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"missing or non-regular payload part: {path.name}")
        expected = FULL_PART_CHARS if i < PART_COUNT - 1 else FINAL_PART_CHARS
        if path.stat().st_size > expected + 256:
            raise RuntimeError(f"oversized payload part: {path.name}")
        text = "".join(path.read_text(encoding="ascii").split())
        if len(text) != expected:
            raise RuntimeError(f"payload part {i:02d}: expected {expected} characters, got {len(text)}")
        chunks.append(text)
    return "".join(chunks)


def _safe_ancestors(path: Path) -> None:
    # Do not resolve first: that would hide a symlink supplied as the output path.
    for p in (path, *path.parents):
        if p.is_symlink():
            raise RuntimeError(f"refusing symlink in output path: {p}")


def materialize(here: Path, dest: Path, replace: bool = False):
    packed = base64.b64decode(_read_encoded(here), validate=True)
    got = hashlib.sha256(packed).hexdigest()
    if got != EXPECTED_SHA256:
        raise RuntimeError(f"payload SHA-256 mismatch: {got}")
    decoder = lzma.LZMADecompressor(memlimit=256 * 1024 * 1024)
    raw = decoder.decompress(packed, max_length=MAX_TAR_BYTES + 1)
    if len(raw) > MAX_TAR_BYTES or not decoder.eof or decoder.unused_data:
        raise RuntimeError("invalid or oversized compressed payload")
    outputs = {}
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tf:
        for member in tf:
            name = member.name
            rel = PurePosixPath(name)
            if (not name or rel.is_absolute() or '..' in rel.parts or '\\' in name
                    or ':' in name or rel.parts[0] != 'app'
                    or name.rstrip('/') != rel.as_posix()):
                raise RuntimeError(f"unsafe archive path: {name}")
            key = rel.as_posix().casefold()
            if key in seen:
                raise RuntimeError(f"duplicate archive path: {name}")
            seen.add(key)
            if not (member.isfile() or member.isdir()):
                raise RuntimeError(f"unsupported archive member: {name}")
            if member.isfile():
                outputs[rel] = (tf.extractfile(member).read(), member.mode & 0o111)
    if len(outputs) != 34:
        raise RuntimeError("wrong number of recovered runtime files")
    dest = Path(os.path.abspath(dest))
    _safe_ancestors(dest)
    # Preflight every destination before creating or replacing any file.
    for rel, (data, _) in outputs.items():
        target = dest.joinpath(*rel.parts)
        _safe_ancestors(target)
        if target.exists() and (not target.is_file() or
                (not replace and target.read_bytes() != data)):
            raise RuntimeError(f"refusing existing different/non-regular file: {target}")
        for parent in target.parents:
            if parent.exists() and not parent.is_dir():
                raise RuntimeError(f"non-directory output ancestor: {parent}")
    for rel, (data, executable) in outputs.items():
        target = dest.joinpath(*rel.parts)
        if target.is_file() and target.read_bytes() == data:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix='.recovery-', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
            os.chmod(temp, 0o755 if executable else 0o644)
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return len(outputs), got


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('.'))
    parser.add_argument('--replace', action='store_true')
    args = parser.parse_args()
    count, sha = materialize(Path(__file__).resolve().parent, args.out, args.replace)
    print(f'verified {sha}; materialized {count} runtime files into {args.out}')


if __name__ == '__main__':
    main()
