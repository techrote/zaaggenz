from __future__ import annotations

import argparse
import base64
import hashlib
import io
import lzma
import pathlib
import tarfile

EXPECTED_SHA256 = "eaf5d3ab822dfa121cd3b795d62619af9e62c041fb02de19f8dbeafb0014c919"
PREFIX = "runtime_source.tar.xz.b64."
FULL_PART_CHARS = 7000
FINAL_PART_CHARS = 6608
PART_COUNT = 17


def _read_encoded(here: pathlib.Path) -> str:
    chunks: list[str] = []
    for i in range(PART_COUNT):
        path = here / f"{PREFIX}{i:02d}"
        if not path.is_file():
            raise RuntimeError(f"missing recovery payload part: {path.name}")
        text = "".join(path.read_text(encoding="ascii").split())
        expected = FULL_PART_CHARS if i < PART_COUNT - 1 else FINAL_PART_CHARS
        if len(text) < expected:
            raise RuntimeError(
                f"recovery payload part {i:02d} is truncated: {len(text)} < {expected}"
            )
        # Some GitHub transport attempts appended data after the intended chunk.
        # The original archive boundary is independently authenticated below,
        # so ignore any suffix rather than accepting it into the decoded stream.
        chunks.append(text[:expected])
    encoded = "".join(chunks)
    expected_total = FULL_PART_CHARS * (PART_COUNT - 1) + FINAL_PART_CHARS
    if len(encoded) != expected_total:
        raise RuntimeError("unexpected encoded recovery payload length")
    return encoded


def materialize(here: pathlib.Path, dest: pathlib.Path, replace: bool = False):
    encoded = _read_encoded(here)
    packed = base64.b64decode(encoded, validate=True)
    got = hashlib.sha256(packed).hexdigest()
    if got != EXPECTED_SHA256:
        raise RuntimeError(f"payload SHA-256 mismatch: {got}")

    raw = lzma.decompress(packed)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tf:
        members = tf.getmembers()
        for member in members:
            rel = pathlib.PurePosixPath(member.name)
            if member.issym() or member.islnk() or rel.is_absolute() or ".." in rel.parts:
                raise RuntimeError(f"unsafe tar member: {member.name}")
            if not (member.isfile() or member.isdir()):
                raise RuntimeError(f"unsupported tar member: {member.name}")

        dest.mkdir(parents=True, exist_ok=True)
        for member in members:
            target = dest / pathlib.PurePosixPath(member.name)
            if member.isfile() and target.exists() and not replace:
                raise RuntimeError(f"refusing existing file: {target}")

        tf.extractall(dest, filter="data")

    regular = [m for m in members if m.isfile()]
    return len(regular), got


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("."))
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    count, sha = materialize(pathlib.Path(__file__).resolve().parent, args.out, args.replace)
    print(f"verified {sha}; materialized {count} runtime files into {args.out}")
