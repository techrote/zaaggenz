"""Generate bounded ZG-043 structural/render/export evidence without retaining large WAV artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from zaaggenz_longform import (
    export_longform,
    render_longform,
    simple_note_export,
    stress_64bar_example,
    structured_90s_example,
)


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _run(label, document):
    result = render_longform(document)
    note_export = simple_note_export(document, result)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        manifest = export_longform(document, root, result=result)
        manifest_sha = _hash(root / "manifest.json")
        note_sha = _hash(root / "note-events.json")
        project_sha = _hash(root / "project.zglongform.json")
        wav_file_count = len(list(root.glob("*.wav")))
    return {
        "label": label,
        "document_sha256": document.sha256,
        "sample_rate_hz": result.sample_rate_hz,
        "frame_count": len(result.mix),
        "duration_seconds": len(result.mix) / result.sample_rate_hz,
        "section_count": len(result.section_ranges),
        "mix_sha256_f32le": result.diagnostics["mix_sha256"],
        "stem_sha256_f32le": result.diagnostics["stem_sha256"],
        "section_ranges": list(result.section_ranges),
        "note_event_count": len(result.note_events),
        "note_warning_codes": sorted({row["code"] for row in note_export["warnings"]}),
        "manifest_sha256": manifest_sha,
        "note_events_file_sha256": note_sha,
        "project_file_sha256": project_sha,
        "exported_wav_file_count": wav_file_count,
        "manifest_frame_count": manifest["frame_count"],
        "manifest_final_master_owner": manifest["final_master_owner"],
        "tail_latency_policy": manifest["tail_latency_policy"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sample-rate", type=int, default=12000)
    args = parser.parse_args()
    if not 8000 <= args.sample_rate <= 48000:
        parser.error("--sample-rate must be in 8000..48000 for this bounded evidence tool")

    structured = _run("structured-90s", structured_90s_example(args.sample_rate))
    stress = _run("stress-64bar", stress_64bar_example(args.sample_rate))

    if not 85.0 <= structured["duration_seconds"] <= 100.0:
        raise RuntimeError(
            "structured example no longer falls in the documented ~90-second envelope"
        )
    if structured["section_count"] != 12:
        raise RuntimeError("structured example section count changed")
    if not any(row["return_of_section_id"] is not None for row in structured["section_ranges"]):
        raise RuntimeError("structured example no longer proves motif-return reuse")
    if stress["section_count"] != 16:
        raise RuntimeError("64-bar stress section count changed")
    stress_document = stress_64bar_example(args.sample_rate).to_dict()
    if not all(
        section["repeats"] == 4
        and section["meter_segments"] == [{"beat": "0/1", "numerator": 4, "denominator": 4}]
        for section in stress_document["sections"]
    ):
        raise RuntimeError("64-bar stress fixture is no longer sixteen literal four-bar 4/4 sections")
    if "non-12tet-tuning" not in stress["note_warning_codes"]:
        raise RuntimeError("64-bar stress no longer exercises non-octave export warnings")
    for row in (structured, stress):
        if row["manifest_frame_count"] != row["frame_count"]:
            raise RuntimeError("export manifest frame count disagrees with rendered result")
        if row["manifest_final_master_owner"] != "render-recipe.output":
            raise RuntimeError("long-form evidence lost the single final master owner")
        if row["exported_wav_file_count"] < 6:
            raise RuntimeError("long-form export did not produce full mix + required stems")

    report = {
        "kind": "ZG043LongformEvidence",
        "version": "1.0.0",
        "scope": "deterministic generated engineering fixtures; no owner listening or preference claim",
        "sample_rate_hz": args.sample_rate,
        "examples": [structured, stress],
        "limitations": [
            "12 kHz CI evidence proves timing/state/export structure, not full-band listening quality",
            "simple note-event export is intentionally warning-bearing and never authority over richer tuning/spectral/layer intent",
            "large WAV bundles are generated and hashed during the run but are not retained as CI artifacts",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
