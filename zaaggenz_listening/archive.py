"""Bounded self-contained transport for exact ZG-015 listening material."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
import struct

from zaaggenz_jobs import atomic_publish_bytes

from .model import ListeningError, Stimulus, TrialManifest

ARCHIVE_FORMAT = "zaaggenz-listening-archive"
ARCHIVE_VERSION = "1.0.0"
ARCHIVE_MIME = "application/vnd.zaaggenz-listening-archive"
ARCHIVE_MAGIC = b"ZG-LISTEN-ARCHIVE\x00\x01"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ListeningArchiveLimits:
    """Executable envelope for a self-contained listening archive.

    Audio bytes are bounded separately from metadata.  The default PCM budget
    mirrors ``ListeningAudioStore`` so a default store can always reject before
    installation rather than silently spilling or truncating material.
    """

    max_blob_count: int = 16
    max_pcm_bytes: int = 256 * 1024 * 1024
    max_manifest_bytes: int = 20 * 1024 * 1024
    max_archive_bytes: int = 320 * 1024 * 1024

    def __post_init__(self):
        for name, value in asdict(self).items():
            if type(value) is not int or value <= 0:
                raise ListeningError(f"{name}: positive integer archive limit required")
        if self.max_archive_bytes <= len(ARCHIVE_MAGIC) + 4:
            raise ListeningError("archive byte limit is too small for framing")

    def to_dict(self):
        return asdict(self)


def _canonical(value):
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ListeningError(f"archive metadata is not strict JSON: {exc}") from exc


def _sha(value, name="sha256"):
    if type(value) is not str or not HEX64.fullmatch(value):
        raise ListeningError(f"{name}: lowercase SHA-256 required")
    return value


def _positive_int(value, name):
    if type(value) is not int or value <= 0:
        raise ListeningError(f"{name}: positive integer required")
    return value


def _material_row(row, *, kind):
    keys = {
        "stimulus_id",
        "sha256",
        "byte_length",
        "sample_rate_hz",
        "channels",
        "frame_count",
    }
    if type(row) is not dict or set(row) != keys:
        raise ListeningError(f"archive {kind} material row has invalid fields")
    _sha(row["stimulus_id"], f"archive {kind} stimulus_id")
    _sha(row["sha256"], f"archive {kind} sha256")
    _positive_int(row["byte_length"], f"archive {kind} byte_length")
    sr = _positive_int(row["sample_rate_hz"], f"archive {kind} sample_rate_hz")
    ch = _positive_int(row["channels"], f"archive {kind} channels")
    frames = _positive_int(row["frame_count"], f"archive {kind} frame_count")
    if not 8000 <= sr <= 384000 or not 1 <= ch <= 8:
        raise ListeningError(f"archive {kind} material shape is out of bounds")
    if row["byte_length"] != frames * ch * 4:
        raise ListeningError(f"archive {kind} byte length disagrees with float32 shape")
    return dict(row)


def _blob_row(row):
    if type(row) is not dict or set(row) != {"sha256", "byte_length"}:
        raise ListeningError("archive blob row has invalid fields")
    return {
        "sha256": _sha(row["sha256"], "archive blob sha256"),
        "byte_length": _positive_int(row["byte_length"], "archive blob byte_length"),
    }


def _manifest_digest(doc):
    payload = {k: v for k, v in doc.items() if k != "manifest_sha256"}
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _validate_manifest(doc, limits):
    keys = {
        "format",
        "version",
        "role",
        "bundle",
        "raw_material",
        "playback_material",
        "blobs",
        "storage_accounting",
        "manifest_sha256",
    }
    if type(doc) is not dict or set(doc) != keys:
        raise ListeningError("invalid listening archive manifest fields")
    if doc["format"] != ARCHIVE_FORMAT or doc["version"] != ARCHIVE_VERSION:
        raise ListeningError("unsupported listening archive format/version")
    if doc["role"] not in ("trusted", "participant"):
        raise ListeningError("listening archive role must be trusted or participant")
    if type(doc["bundle"]) is not dict:
        raise ListeningError("listening archive bundle must be an object")
    if type(doc["raw_material"]) is not list or type(doc["playback_material"]) is not list:
        raise ListeningError("listening archive material indexes must be lists")
    if not 2 <= len(doc["raw_material"]) <= 8 or not 2 <= len(doc["playback_material"]) <= 8:
        raise ListeningError("listening archive requires 2..8 raw and playback material rows")

    raw = [_material_row(row, kind="raw") for row in doc["raw_material"]]
    playback = [_material_row(row, kind="playback") for row in doc["playback_material"]]
    if len({row["stimulus_id"] for row in raw}) != len(raw):
        raise ListeningError("archive raw material contains duplicate stimulus IDs")
    if len({row["stimulus_id"] for row in playback}) != len(playback):
        raise ListeningError("archive playback material contains duplicate stimulus IDs")
    if {row["stimulus_id"] for row in raw} != {row["stimulus_id"] for row in playback}:
        raise ListeningError("archive raw/playback stimulus sets disagree")

    if type(doc["blobs"]) is not list:
        raise ListeningError("listening archive blobs must be a list")
    if len(doc["blobs"]) > limits.max_blob_count:
        raise ListeningError("listening archive blob-count limit exceeded")
    blobs = [_blob_row(row) for row in doc["blobs"]]
    hashes = [row["sha256"] for row in blobs]
    if hashes != sorted(hashes) or len(set(hashes)) != len(hashes):
        raise ListeningError("archive blob index must be unique and SHA-sorted")
    blob_lengths = {row["sha256"]: row["byte_length"] for row in blobs}
    refs = {row["sha256"] for row in raw + playback}
    if refs != set(blob_lengths):
        raise ListeningError("archive blob index must exactly cover referenced audio")
    for row in raw + playback:
        if blob_lengths[row["sha256"]] != row["byte_length"]:
            raise ListeningError("archive material/blob byte lengths disagree")

    restored_pcm_bytes = sum(row["byte_length"] for row in raw)
    playback_seen = set()
    for row in playback:
        if row["sha256"] not in playback_seen:
            restored_pcm_bytes += row["byte_length"]
            playback_seen.add(row["sha256"])
    unique_blob_bytes = sum(blob_lengths.values())
    if restored_pcm_bytes > limits.max_pcm_bytes:
        raise ListeningError("listening archive restored-PCM limit exceeded")

    accounting = doc["storage_accounting"]
    if type(accounting) is not dict or set(accounting) != {
        "method",
        "raw_entries",
        "playback_entries",
        "unique_blob_count",
        "restored_pcm_bytes",
        "archive_unique_blob_bytes",
    }:
        raise ListeningError("invalid listening archive storage accounting")
    expected_accounting = {
        "method": "retained-pcm-physical-bytes-v1",
        "raw_entries": len(raw),
        "playback_entries": len({row["sha256"] for row in playback}),
        "unique_blob_count": len(blobs),
        "restored_pcm_bytes": restored_pcm_bytes,
        "archive_unique_blob_bytes": unique_blob_bytes,
    }
    if accounting != expected_accounting:
        raise ListeningError("listening archive storage accounting mismatch")
    _sha(doc["manifest_sha256"], "archive manifest_sha256")
    if doc["manifest_sha256"] != _manifest_digest(doc):
        raise ListeningError("listening archive manifest digest mismatch")
    return raw, playback, blobs


def encode_archive(*, role, bundle, raw_material, playback_material, blobs, limits=None):
    """Build one deterministic bounded archive from already-validated material."""
    limits = ListeningArchiveLimits() if limits is None else limits
    if not isinstance(limits, ListeningArchiveLimits):
        raise ListeningError("archive limits must be ListeningArchiveLimits")
    if type(blobs) is not dict:
        raise ListeningError("archive blobs must be a SHA-to-bytes mapping")
    clean_blobs = {}
    for sha, payload in blobs.items():
        _sha(sha, "archive blob key")
        if not isinstance(payload, bytes):
            raise ListeningError("archive blob payloads must be immutable bytes")
        if not payload:
            raise ListeningError("archive blob payloads must not be empty")
        if hashlib.sha256(payload).hexdigest() != sha:
            raise ListeningError("archive blob payload does not match its SHA-256")
        clean_blobs[sha] = payload
    blob_rows = [
        {"sha256": sha, "byte_length": len(clean_blobs[sha])}
        for sha in sorted(clean_blobs)
    ]

    raw_rows = [dict(row) for row in raw_material]
    playback_rows = [dict(row) for row in playback_material]
    provisional = {
        "format": ARCHIVE_FORMAT,
        "version": ARCHIVE_VERSION,
        "role": role,
        "bundle": bundle,
        "raw_material": raw_rows,
        "playback_material": playback_rows,
        "blobs": blob_rows,
        "storage_accounting": {},
        "manifest_sha256": "0" * 64,
    }
    raw_checked = [_material_row(row, kind="raw") for row in raw_rows]
    playback_checked = [_material_row(row, kind="playback") for row in playback_rows]
    restored = sum(row["byte_length"] for row in raw_checked)
    seen = set()
    for row in playback_checked:
        if row["sha256"] not in seen:
            restored += row["byte_length"]
            seen.add(row["sha256"])
    provisional["storage_accounting"] = {
        "method": "retained-pcm-physical-bytes-v1",
        "raw_entries": len(raw_checked),
        "playback_entries": len(seen),
        "unique_blob_count": len(blob_rows),
        "restored_pcm_bytes": restored,
        "archive_unique_blob_bytes": sum(row["byte_length"] for row in blob_rows),
    }
    provisional["manifest_sha256"] = _manifest_digest(provisional)
    _validate_manifest(provisional, limits)
    manifest = _canonical(provisional)
    if len(manifest) > limits.max_manifest_bytes:
        raise ListeningError("listening archive manifest-byte limit exceeded")

    exact_size = len(ARCHIVE_MAGIC) + 4 + len(manifest)
    exact_size += sum(40 + row["byte_length"] for row in blob_rows)
    if exact_size > limits.max_archive_bytes:
        raise ListeningError("listening archive byte limit exceeded")

    parts = [ARCHIVE_MAGIC, struct.pack(">I", len(manifest)), manifest]
    for row in blob_rows:
        sha = row["sha256"]
        payload = clean_blobs[sha]
        parts.extend((bytes.fromhex(sha), struct.pack(">Q", len(payload)), payload))
    archive = b"".join(parts)
    if len(archive) != exact_size:
        raise ListeningError("internal listening archive framing error")
    return archive


def decode_archive(payload, *, limits=None):
    """Strictly parse and verify a complete archive without filesystem extraction."""
    limits = ListeningArchiveLimits() if limits is None else limits
    if not isinstance(limits, ListeningArchiveLimits):
        raise ListeningError("archive limits must be ListeningArchiveLimits")
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ListeningError("listening archive must be bytes")
    view = memoryview(payload)
    if len(view) > limits.max_archive_bytes:
        raise ListeningError("listening archive byte limit exceeded")
    prefix = len(ARCHIVE_MAGIC)
    if len(view) < prefix + 4 or bytes(view[:prefix]) != ARCHIVE_MAGIC:
        raise ListeningError("invalid listening archive framing")
    manifest_len = struct.unpack(">I", view[prefix : prefix + 4])[0]
    if manifest_len <= 0 or manifest_len > limits.max_manifest_bytes:
        raise ListeningError("listening archive manifest-byte limit exceeded")
    pos = prefix + 4
    end_manifest = pos + manifest_len
    if end_manifest > len(view):
        raise ListeningError("truncated listening archive manifest")
    try:
        manifest = json.loads(bytes(view[pos:end_manifest]).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ListeningError("invalid listening archive manifest JSON") from exc
    _, _, blob_rows = _validate_manifest(manifest, limits)
    pos = end_manifest
    blobs = {}
    for expected in blob_rows:
        if pos + 40 > len(view):
            raise ListeningError("truncated listening archive blob header")
        sha = bytes(view[pos : pos + 32]).hex()
        length = struct.unpack(">Q", view[pos + 32 : pos + 40])[0]
        pos += 40
        if sha != expected["sha256"] or length != expected["byte_length"]:
            raise ListeningError("listening archive blob framing/index mismatch")
        if pos + length > len(view):
            raise ListeningError("truncated listening archive blob")
        data = bytes(view[pos : pos + length])
        pos += length
        if hashlib.sha256(data).hexdigest() != sha:
            raise ListeningError("listening archive blob SHA-256 mismatch")
        blobs[sha] = data
    if pos != len(view):
        raise ListeningError("listening archive has trailing bytes")
    return {"manifest": manifest, "blobs": blobs}


def _trusted_bundle_objects(bundle):
    """Parse the immutable objects needed to bind archive bytes to one trial."""
    if (
        type(bundle) is not dict
        or set(bundle) != {"format", "version", "stimuli", "manifest", "results"}
        or bundle.get("format") != "zaaggenz-listening-bundle"
        or bundle.get("version") != "1.0.0"
    ):
        raise ListeningError(
            "trusted archive requires zaaggenz-listening-bundle/1.0.0 metadata"
        )
    trial = TrialManifest(bundle["manifest"])
    if type(bundle["stimuli"]) is not list:
        raise ListeningError("trusted archive stimuli must be a list")
    stimuli = [Stimulus(row) for row in bundle["stimuli"]]
    trial_doc = trial.to_dict()
    if {stimulus.to_dict()["id"] for stimulus in stimuli} != {
        row["stimulus_id"] for row in trial_doc["matched_stimuli"]
    }:
        raise ListeningError("archive stimulus provenance does not match trial")
    return trial, stimuli


def export_service_archive(service, trial_id, *, role="trusted", limits=None):
    """Export exact listening bytes plus one existing role-appropriate bundle."""
    limits = ListeningArchiveLimits() if limits is None else limits
    if role == "trusted":
        bundle = service.export_bundle(trial_id)
        trial, stimuli = _trusted_bundle_objects(bundle)
    elif role == "participant":
        bundle = service.export_participant_bundle(trial_id)
        trusted = service.participant_manifest(trial_id)
        trial = trusted
        if type(bundle.get("stimuli")) is not list:
            raise ListeningError("participant archive stimuli must be a list")
        stimuli = [Stimulus(row) for row in bundle["stimuli"]]
        if {stimulus.to_dict()["id"] for stimulus in stimuli} != {
            row["stimulus_id"] for row in trial.to_dict()["matched_stimuli"]
        }:
            raise ListeningError("participant archive stimulus provenance mismatch")
    else:
        raise ListeningError("listening archive role must be trusted or participant")
    material = service.audio.archive_material(
        stimuli, trial.to_dict()["matched_stimuli"]
    )
    return encode_archive(role=role, bundle=bundle, limits=limits, **material)


def publish_service_archive(service, trial_id, path, *, token=None, limits=None):
    """Atomically publish one trusted archive without ever exposing a partial file."""
    payload = export_service_archive(service, trial_id, role="trusted", limits=limits)
    return atomic_publish_bytes(path, payload, token=token)


def reopen_service_archive(service, payload, *, limits=None):
    """Verify exact PCM, restore it transactionally, then reopen trusted metadata."""
    decoded = decode_archive(payload, limits=limits)
    manifest = decoded["manifest"]
    if manifest["role"] != "trusted":
        raise ListeningError(
            "participant-safe listening archives cannot be reopened as trusted evidence"
        )
    bundle = manifest["bundle"]
    trial, stimuli = _trusted_bundle_objects(bundle)
    receipt = service.audio.install_archive_material(
        stimuli,
        trial.to_dict()["matched_stimuli"],
        manifest["raw_material"],
        manifest["playback_material"],
        decoded["blobs"],
    )
    try:
        return service.reopen_bundle(bundle)
    except Exception:
        service.audio.rollback_archive_material(receipt)
        raise
