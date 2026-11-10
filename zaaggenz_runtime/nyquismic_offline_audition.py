"""One-command, opt-in saved Compose project -> verified offline NYQ A/B HTML.

Uses the existing ordinary Compose, controlled-clock, 48-kHz A/B and verified
offline player pipeline unchanged. Only the finished HTML leaves the private
temporary working directory. This is not a registered Compose GUI/graph node.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from zaaggenz_runtime.nyquismic_offline_export import (
    DEFAULT_VIRTUAL_HZ,
    EVALUATION_RATES_HZ,
)
from zaaggenz_runtime.nyquismic_offline_ab48 import export_saved_compose_ab48
from zaaggenz_runtime.nyquismic_ab48_listen import publish_ab48_audition


def export_saved_compose_audition(
    project_path: str | Path,
    output_path: str | Path,
    *,
    virtual_rate_hz: str = DEFAULT_VIRTUAL_HZ,
    evaluation_rate_hz: int = 192000,
    wait_seconds: float = 120.,
    cancelled=None,
) -> dict:
    """Render one saved-project snapshot and publish exactly one portable HTML.

    The saved project is read by the existing #281 source-authenticated exporter,
    whose internal TimelineService owns the render/session/cancellation guards.
    Its temporary ZIP is finalized first; the independently verified #282
    publisher then atomically links the HTML without replacing user data.
    There is no claim of monitoring subsequent changes to the project file or
    of keeping a live TimelineService session after the ZIP is finalized.
    """
    if cancelled is not None and not callable(cancelled):
        raise ValueError("cancelled must be a callable or None")
    dest = Path(output_path).absolute()
    if dest.suffix.lower() != ".html" or not dest.parent.is_dir():
        raise ValueError("output must be a .html file in an existing directory")
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    if cancelled is not None and cancelled():
        raise RuntimeError("direct audition cancelled before render")

    # In particular, a failed render/verification never leaves a user-facing ZIP.
    # Restrict temporary output to this single owned directory; cleanup runs on
    # both Unix and Windows, including cancellation and competing-writer errors.
    with tempfile.TemporaryDirectory(prefix=".nyq-direct-audition-",
                                     dir=str(dest.parent)) as directory:
        staged_zip = Path(directory) / "source-ab48.zip"
        source = export_saved_compose_ab48(
            project_path, staged_zip,
            virtual_rate_hz=virtual_rate_hz,
            evaluation_rate_hz=evaluation_rate_hz,
            wait_seconds=wait_seconds,
            cancelled=cancelled,
        )
        if cancelled is not None and cancelled():
            raise RuntimeError("direct audition cancelled after source render")
        # Refuse an unexpected source/temporary-output mutation BEFORE publishing
        # final HTML. #282 separately verifies WAV and decoded PCM identities.
        source_bytes = staged_zip.read_bytes()
        actual_sha = hashlib.sha256(source_bytes).hexdigest()
        if actual_sha != source["archive_sha256"]:
            raise RuntimeError("NYQ temporary A/B bundle identity changed")
        published = publish_ab48_audition(staged_zip, dest, cancelled=cancelled)
        return {
            **published,
            "source_bundle_sha256": actual_sha,
            "project_file_sha256": source["manifest"]["project_file_sha256"],
            "source_revision_sha256": source["manifest"]["source_revision_sha256"],
            "compose_recipe_sha256": source["manifest"]["compose_recipe_sha256"],
            "packet_sha256": source["manifest"]["packet_sha256"],
            "dry_pcm_f32le_sha256": source["manifest"]["dry"]["pcm_f32le_sha256"],
            "wet_pcm_f32le_sha256": source["manifest"]["wet"]["pcm_f32le_sha256"],
            "virtual_rate_hz": virtual_rate_hz,
            "evaluation_rate_hz": evaluation_rate_hz,
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="One-command saved Compose project to local NYQ A/B HTML; "
                    "no source upload, default change, or overwrite.")
    parser.add_argument("--project", required=True,
                        help="Existing saved .zgtimeline.json project")
    parser.add_argument("--output", required=True,
                        help="New standalone .html; existing files preserved")
    parser.add_argument("--virtual-hz", default=DEFAULT_VIRTUAL_HZ)
    parser.add_argument("--evaluation-hz", type=int, choices=EVALUATION_RATES_HZ,
                        default=192000)
    args = parser.parse_args(argv)
    try:
        receipt = export_saved_compose_audition(
            args.project, args.output, virtual_rate_hz=args.virtual_hz,
            evaluation_rate_hz=args.evaluation_hz)
    except (Exception, KeyboardInterrupt) as exc:
        print("NYQ direct audition failed: " + str(exc), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
