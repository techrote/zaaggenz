from __future__ import annotations

import math
import re
from pathlib import Path

from zaaggenz_contracts import loads


ANNOTATION_TIMING_VERSION = "1.0.0"
ANNOTATION_COORDINATE_DOMAIN = "decoded-native-rate-pcm-v1"
_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANNOTATION_TIMING_PATH = _REPO_ROOT / "references" / "annotation_timing_v1.json"
DEFAULT_REGISTRY_PATH = _REPO_ROOT / "references" / "private_registry_v1.json"


class AnnotationError(ValueError):
    pass


def _r(condition, message):
    if not condition:
        raise AnnotationError(message)


def _sha_text(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_timing_shape(data):
    _r(
        type(data) is dict
        and set(data) == {"version", "coordinate_domain", "assets"},
        "invalid annotation timing root",
    )
    _r(data["version"] == ANNOTATION_TIMING_VERSION, "unsupported annotation timing version")
    _r(
        data["coordinate_domain"] == ANNOTATION_COORDINATE_DOMAIN,
        "unsupported annotation coordinate domain",
    )
    _r(type(data["assets"]) is list and len(data["assets"]) <= 256, "invalid annotation timing assets")
    rows = {}
    required = {"id", "source_sha256", "sample_rate_hz", "channels", "frame_count"}
    for row in data["assets"]:
        _r(type(row) is dict and set(row) == required, "invalid annotation timing asset")
        _r(type(row["id"]) is str and re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", row["id"]) is not None, "invalid annotation timing asset id")
        _r(row["id"] not in rows, "duplicate annotation timing asset")
        _r(_sha_text(row["source_sha256"]), "invalid annotation timing source identity")
        _r(type(row["sample_rate_hz"]) is int and 8000 <= row["sample_rate_hz"] <= 192000, "invalid annotation timing sample rate")
        _r(row["channels"] in (1, 2), "invalid annotation timing channels")
        _r(type(row["frame_count"]) is int and type(row["frame_count"]) is not bool and row["frame_count"] > 0, "invalid annotation timing frame count")
        rows[row["id"]] = row
    return rows


def load_annotation_timing(path, registry):
    """Load exact, portable annotation timing and bind it to registry content identity.

    Annotation coordinates are half-open frame intervals in decoded PCM at the
    asset's native sample rate. The timing catalogue deliberately contains no
    local locator/path; each timing row is bound to the registry's content SHA.
    """

    data = loads(Path(path).read_bytes())
    rows = _validate_timing_shape(data)
    _r(type(registry) is dict and type(registry.get("assets")) is list, "invalid reference registry for annotation timing")
    registry_rows = {row.get("id"): row for row in registry["assets"] if type(row) is dict}
    _r(set(rows) == set(registry_rows), "annotation timing/registry asset set mismatch")
    for asset_id, timing in rows.items():
        source = registry_rows[asset_id]
        _r(source.get("sha256") == timing["source_sha256"], f"annotation timing content identity mismatch: {asset_id}")
        native = source.get("native")
        _r(type(native) is dict, f"annotation timing native metadata missing: {asset_id}")
        _r(native.get("sample_rate_hz") == timing["sample_rate_hz"], f"annotation timing sample-rate mismatch: {asset_id}")
        _r(native.get("channels") == timing["channels"], f"annotation timing channel mismatch: {asset_id}")
        planning = source.get("planning")
        _r(type(planning) is dict, f"annotation timing planning metadata missing: {asset_id}")
        duration = planning.get("decoded_24k_duration_s")
        _r(type(duration) in (int, float) and type(duration) is not bool and math.isfinite(float(duration)) and duration > 0, f"annotation timing duration evidence invalid: {asset_id}")
        expected_frames = float(duration) * timing["sample_rate_hz"]
        _r(abs(expected_frames - timing["frame_count"]) <= 1e-6, f"annotation timing frame-count mismatch: {asset_id}")
    return data


def _canonical_timing_for_ids(asset_ids):
    # Backwards-compatible shorthand for the original ``set`` call surface.
    # It is no longer an ID-only validation path: IDs are resolved through the
    # checked-in exact content/timing catalogue before any annotation is accepted.
    from .registry import load_registry

    _r(type(asset_ids) in (set, frozenset), "annotation asset timing metadata required")
    registry = load_registry(DEFAULT_REGISTRY_PATH)
    timing = load_annotation_timing(DEFAULT_ANNOTATION_TIMING_PATH, registry)
    rows = _validate_timing_shape(timing)
    _r(asset_ids <= set(rows), "unknown annotated asset")
    return rows, set(asset_ids)


def _timing_context(assets):
    if type(assets) in (set, frozenset):
        return _canonical_timing_for_ids(assets)
    rows = _validate_timing_shape(assets)
    return rows, set(rows)


def validate_annotation(data, assets):
    """Validate annotation structure and exact source-domain sample extents.

    ``assets`` is normally a catalogue returned by ``load_annotation_timing``.
    For compatibility, a set/frozenset of canonical registry IDs is accepted,
    but it is resolved through the checked-in timing catalogue rather than being
    treated as sufficient evidence by itself.
    """

    timing_rows, allowed_ids = _timing_context(assets)
    _r(type(data) is dict and set(data) == {"version", "segments", "relations"}, "invalid annotation root")
    _r(data["version"] == "1.0.0", "unsupported annotation version")
    segids = set()
    for segment in data["segments"]:
        required = {
            "id",
            "asset_id",
            "start_sample",
            "end_sample",
            "section_function",
            "label",
            "confidence",
            "source",
            "meter_candidates",
            "correspondence_group",
        }
        _r(type(segment) is dict and set(segment) == required, "invalid segment")
        _r(segment["id"] not in segids, "duplicate segment")
        segids.add(segment["id"])
        asset_id = segment["asset_id"]
        _r(asset_id in allowed_ids and asset_id in timing_rows, "unknown annotated asset")
        timing = timing_rows[asset_id]
        _r(
            type(segment["start_sample"]) is int
            and type(segment["end_sample"]) is int
            and 0 <= segment["start_sample"] < segment["end_sample"] <= timing["frame_count"],
            "invalid segment span",
        )
        _r(segment["section_function"] in ("unknown", "establish", "build", "drop", "variation", "break", "return", "outro"), "invalid section function")
        _r(type(segment["confidence"]) in (int, float) and 0 <= segment["confidence"] <= 1, "invalid confidence")
        _r(segment["source"] in ("manual", "automatic-suggestion"), "invalid annotation source")
        _r(segment["correspondence_group"] is None or type(segment["correspondence_group"]) is str, "invalid correspondence group")
        _r(type(segment["meter_candidates"]) is list and len(segment["meter_candidates"]) <= 8, "invalid metre candidates")
        total = 0
        for meter in segment["meter_candidates"]:
            _r(type(meter) is dict and set(meter) == {"numerator", "denominator", "pulse_divisor", "confidence"}, "invalid metre candidate")
            _r(meter["numerator"] > 0 and meter["denominator"] in (1, 2, 4, 8, 16, 32) and meter["pulse_divisor"] in (1, 2, 4, 8), "invalid metre")
            _r(0 <= meter["confidence"] <= 1, "invalid metre confidence")
            total += meter["confidence"]
        _r(total <= 1.000001, "metre confidence mass > 1")
    relids = set()
    for relation in data["relations"]:
        _r(type(relation) is dict and set(relation) == {"id", "left_segment", "right_segment", "relation", "confidence", "source"}, "invalid relation")
        _r(relation["id"] not in relids, "duplicate relation")
        relids.add(relation["id"])
        _r(relation["left_segment"] in segids and relation["right_segment"] in segids and relation["left_segment"] != relation["right_segment"], "relation references invalid segments")
        _r(relation["relation"] in ("corresponding", "unrelated", "uncertain"), "invalid relation")
        _r(0 <= relation["confidence"] <= 1, "invalid relation confidence")
        _r(relation["source"] in ("manual", "automatic-suggestion"), "invalid relation source")
    return data
