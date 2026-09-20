"""Aligned long-form bundle export with explicit note-representation fidelity warnings."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile

import numpy as np
from scipy.io import wavfile

from zaaggenz_tuning import tuning_from_spec

from .model import LongformDocument, LongformError, save_longform
from .render import LongformRenderResult, render_longform


def _canonical_bytes(value):
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_bytes(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _wav_bytes(sample_rate_hz, audio):
    buffer = io.BytesIO()
    wavfile.write(
        buffer,
        int(sample_rate_hz),
        np.asarray(audio, dtype=np.float32),
    )
    return buffer.getvalue()


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _is_12edo(spec):
    ratios = spec["degree_ratios"]
    if len(ratios) != 12 or not math.isclose(
        float(spec["period_ratio"]), 2.0, rel_tol=0, abs_tol=1e-12
    ):
        return False
    return all(
        math.isclose(
            float(value),
            2.0 ** (index / 12.0),
            rel_tol=1e-10,
            abs_tol=1e-12,
        )
        for index, value in enumerate(ratios)
    )


def simple_note_export(document, result):
    if not isinstance(document, LongformDocument):
        raise LongformError("LongformDocument required")
    if not isinstance(result, LongformRenderResult):
        raise LongformError("LongformRenderResult required")

    data = document.to_dict()
    tunings = {row["id"]: row for row in data["tunings"]}
    sections = {row["id"]: row for row in data["sections"]}
    warnings = []

    def warn(code, message, *, section_id=None, event_id=None):
        row = {"code": code, "message": message}
        if section_id is not None:
            row["section_id"] = section_id
        if event_id is not None:
            row["event_id"] = event_id
        warnings.append(row)

    for section in data["sections"]:
        tuning = tunings[section["tuning_id"]]
        if not _is_12edo(tuning):
            warn(
                "non-12tet-tuning",
                "simple integer note export cannot faithfully encode this non-12-TET tuning; exact TuningSpec is retained separately",
                section_id=section["id"],
            )
        for intent in section["deferred_intent"]:
            code = {
                "continuous-spectral-retuning": "continuous-spectral-retuning-not-note-exportable",
                "adaptive-tuning": "adaptive-tuning-not-note-exportable",
                "timbral-gesture": "timbral-gesture-not-note-exportable",
            }[intent]
            warn(
                code,
                f"{intent} is retained as long-form deferred intent and is not collapsed into simple note pitches",
                section_id=section["id"],
            )
        if section["automation"]:
            warn(
                "pre-master-automation-not-note-exportable",
                "source/persistent contribution gain automation is retained in the long-form project/manifest, not encoded as note pitch events",
                section_id=section["id"],
            )
        if section["pocket_plan"] is not None:
            warn(
                "layer-pockets-not-note-exportable",
                "ZG-030 pocket intent is retained in the long-form project/manifest and cannot be represented by simple note events",
                section_id=section["id"],
            )

    for target in data["layer_runtime"]["transform_targets"]:
        if target["quantity"] == "retune":
            warn(
                "persistent-layer-retune-not-note-exportable",
                "persistent-layer retune ownership/target is retained in layer metadata, not converted into synthline note events",
            )

    events = []
    for row in result.note_events:
        event = deepcopy(row)
        section = sections[event["section_id"]]
        if not event["rest"]:
            if abs(float(event["detune_cents"])) > 1e-12:
                warn(
                    "microtonal-static-offset",
                    "static microtonal detune is preserved numerically but may not round-trip through integer-note formats",
                    section_id=event["section_id"],
                    event_id=event["event_id"],
                )
            if event["pitch_curve_cents"]:
                warn(
                    "microtonal-bend-not-note-exportable",
                    "continuous pitch curve is preserved in long-form event metadata but cannot be represented by a single simple note pitch",
                    section_id=event["section_id"],
                    event_id=event["event_id"],
                )
            if event["midi_note_12tet"] is None:
                warn(
                    "no-exact-midi-note",
                    "event has no exact integer 12-TET MIDI-note identity; frequency/tuning coordinate is authoritative",
                    section_id=event["section_id"],
                    event_id=event["event_id"],
                )
        events.append(event)

    # Stable de-duplication without erasing per-event/section context.
    seen = set()
    unique_warnings = []
    for row in warnings:
        key = json.dumps(row, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            unique_warnings.append(row)

    return {
        "kind": "ZG043SimpleNoteEventExport",
        "version": "1.0.0",
        "source_document_sha256": document.sha256,
        "sample_rate_hz": result.sample_rate_hz,
        "representation": {
            "events": "absolute sample/time plus tuning degree, detune, exact frequency and optional exact integer 12-TET MIDI note",
            "midi_note_12tet": "present only when exact under the persisted tuning and no continuous pitch curve/static detune is required",
            "fidelity_policy": "warnings are mandatory; richer tuning/spectral/adaptive/timbral/layer intent is retained separately and never silently collapsed",
        },
        "layer_ownership": {
            "synthline": "raw source-owned audition/provenance stem",
            "exciter": "raw source-owned audition/provenance stem",
            "source_bus": "processed shared source contribution after preserved source topology",
            "body": "persistent pre-master BODY owner",
            "aux": "persistent pre-master AUX owner",
            "sub": "persistent pre-master SUB owner",
            "pre_master": "source_bus + automated/pocketed BODY/AUX/SUB",
            "mix": "single final RenderRecipe.output owner",
        },
        "sections": [
            {
                "id": row["id"],
                "motif_id": row["motif_id"],
                "tuning_id": row["tuning_id"],
                "tempo_segments": deepcopy(row["tempo_segments"]),
                "meter_segments": deepcopy(row["meter_segments"]),
                "harmony_frames": deepcopy(row["harmony_frames"]),
                "deferred_intent": list(row["deferred_intent"]),
            }
            for row in data["sections"]
        ],
        "events": events,
        "warnings": unique_warnings,
    }


def export_longform(document, directory, *, result=None):
    if not isinstance(document, LongformDocument):
        raise LongformError("LongformDocument required")
    if result is None:
        result = render_longform(document)
    if not isinstance(result, LongformRenderResult):
        raise LongformError("LongformRenderResult required")
    if any(len(audio) != len(result.mix) for audio in result.stems.values()):
        raise LongformError("aligned export requires every stem to match mix frame count")

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    files = {}

    def publish(name, payload):
        _atomic_bytes(directory / name, payload)
        files[name] = {
            "sha256": _sha(payload),
            "bytes": len(payload),
        }

    publish("mix.wav", _wav_bytes(result.sample_rate_hz, result.mix))
    required_stems = ("synthline", "exciter", "body", "aux", "sub")
    for role in required_stems:
        publish(
            f"stem-{role}.wav",
            _wav_bytes(result.sample_rate_hz, result.stems[role]),
        )
    if document.to_dict()["export_policy"]["include_source_bus"]:
        publish(
            "stem-source_bus.wav",
            _wav_bytes(result.sample_rate_hz, result.stems["source_bus"]),
        )
    if document.to_dict()["export_policy"]["include_pre_master"]:
        publish(
            "stem-pre_master.wav",
            _wav_bytes(result.sample_rate_hz, result.stems["pre_master"]),
        )

    # Persist the canonical authoring wrapper as the project-level authority.
    project_payload = (document._json + "\n").encode("utf-8")
    publish("project.zglongform.json", project_payload)

    data = document.to_dict()
    publish(
        "tunings.json",
        _canonical_bytes(
            {
                "kind": "ZG043TuningExport",
                "version": "1.0.0",
                "source_document_sha256": document.sha256,
                "tunings": deepcopy(data["tunings"]),
            }
        ),
    )
    publish(
        "grammars.json",
        _canonical_bytes(
            {
                "kind": "ZG043GrammarExport",
                "version": "1.0.0",
                "source_document_sha256": document.sha256,
                "grammar_sources": deepcopy(data["grammar_sources"]),
                "motif_origins": [
                    {"motif_id": motif["id"], "origin": deepcopy(motif["origin"])}
                    for motif in data["motifs"]
                ],
            }
        ),
    )
    note_export = simple_note_export(document, result)
    publish("note-events.json", _canonical_bytes(note_export))

    manifest = {
        "kind": "ZG043LongformExportManifest",
        "version": "1.0.0",
        "source_document_sha256": document.sha256,
        "sample_rate_hz": result.sample_rate_hz,
        "frame_count": len(result.mix),
        "duration_seconds": len(result.mix) / result.sample_rate_hz,
        "section_ranges": [deepcopy(row) for row in result.section_ranges],
        "tail_latency_policy": deepcopy(
            result.diagnostics["tail_latency_policy"]
        ),
        "automation_stage": result.diagnostics["automation_stage"],
        "layer_ownership": note_export["layer_ownership"],
        "final_master_owner": result.diagnostics["final_master_owner"],
        "normalization": result.diagnostics["normalization"],
        "mix_sha256_f32le": result.diagnostics["mix_sha256"],
        "stem_sha256_f32le": deepcopy(result.diagnostics["stem_sha256"]),
        "note_export_warnings": deepcopy(note_export["warnings"]),
        "final_runtime_state": deepcopy(result.final_runtime_state),
        "files": deepcopy(files),
    }
    publish("manifest.json", _canonical_bytes(manifest))
    return manifest
