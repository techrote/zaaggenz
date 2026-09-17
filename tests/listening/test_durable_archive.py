from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from zaaggenz_contracts.examples import examples
from zaaggenz_jobs import JobCancelled, RenderArtifact
from zaaggenz_listening import ListeningError, ListeningService
from zaaggenz_listening.archive import (
    ARCHIVE_FORMAT,
    ARCHIVE_VERSION,
    ListeningArchiveLimits,
    decode_archive,
    export_service_archive,
    publish_service_archive,
    reopen_service_archive,
)


def _sha(label):
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _artifact(label, *, channels, frames=256, sample_rate=12000, phase=0):
    base = np.where((np.arange(frames) + phase) % 2, np.float32(-0.1), np.float32(0.1))
    if channels == 1:
        x = base[:, None]
    else:
        other = np.roll(base, 1)[:, None]
        x = np.concatenate((base[:, None], other), axis=1)
    pcm = x.astype("<f4", copy=False).tobytes()
    asset = examples()["AudioAssetRef"]
    asset.update(
        content_sha256=hashlib.sha256(pcm).hexdigest(),
        identity_domain="pcm-f32le-interleaved-v1",
        sample_rate_hz=sample_rate,
        channels=channels,
        channel_layout="mono" if channels == 1 else "stereo-lr",
        frame_count=frames,
        level_domain="source",
        sample_policy="unclamped_float",
    )
    return RenderArtifact(
        _sha(label + ":revision"),
        _sha(label + ":recipe"),
        "synth",
        _sha(label + ":cache"),
        pcm,
        asset,
        {"region": {"start_sample": 0, "end_sample": frames}, "offset_sample": 0},
    )


def _ready_service(*, abx=False, hostile_name=False):
    service = ListeningService(object())
    a = service.audio.add_artifact(
        "../escape" if hostile_name else "mono-A", _artifact("a", channels=1, phase=0)
    )
    b = service.audio.add_artifact(
        "stereo-B", _artifact("b", channels=2, phase=1)
    )
    matched = service.match([a.to_dict()["id"], b.to_dict()["id"]])
    if abx:
        public = service.create_participant_trial(
            "Blind archive", "abx", matched, seed="17", endpoints=("liking",)
        )
    else:
        public = service.create_trial(
            "Durable archive", "ab", matched, seed="17", endpoints=("liking",)
        )
    return service, public, matched


def _submit_three(service, public):
    counts = {sid: 0 for sid in public["presentation_order"]}
    service.submit(
        public["id"],
        {
            "status": "completed",
            "choice": public["presentation_order"][0],
            "ratings": {"liking": 71},
            "confidence": 60,
            "effort": 25,
            "comfortable_level": 50,
            "replay_counts": counts,
            "x_replay_count": 0,
            "annotations": [],
            "note": "complete",
        },
    )
    service.submit(
        public["id"],
        {
            "status": "aborted",
            "choice": None,
            "ratings": {},
            "confidence": None,
            "effort": 80,
            "comfortable_level": None,
            "replay_counts": counts,
            "x_replay_count": 0,
            "annotations": [],
            "note": "stopped",
        },
    )
    service.submit(
        public["id"],
        {
            "status": "missing",
            "choice": None,
            "ratings": {},
            "confidence": None,
            "effort": None,
            "comfortable_level": None,
            "replay_counts": counts,
            "x_replay_count": 0,
            "annotations": [],
            "note": "not collected",
        },
    )


class DurableArchiveTests(unittest.TestCase):
    def test_fresh_service_reopen_is_bit_exact_without_rematch_or_rerender(self):
        source, public, matched = _ready_service()
        _submit_three(source, public)
        before = {row["playback_sha256"]: source.audio.playback_pcm(row["playback_sha256"]) for row in matched}
        archive = export_service_archive(source, public["id"])
        decoded = decode_archive(archive)
        self.assertEqual(decoded["manifest"]["format"], ARCHIVE_FORMAT)
        self.assertEqual(decoded["manifest"]["version"], ARCHIVE_VERSION)
        self.assertEqual(decoded["manifest"]["role"], "trusted")

        fresh = ListeningService(object())
        reopened = reopen_service_archive(fresh, archive)
        self.assertEqual([r["status"] for r in reopened["results"]], ["completed", "aborted", "missing"])
        for psha, pcm in before.items():
            self.assertEqual(hashlib.sha256(pcm).hexdigest(), psha)
            self.assertEqual(fresh.audio.playback_pcm(psha), pcm)
        self.assertEqual(fresh.audio.accounting()["total_pcm_bytes"], source.audio.accounting()["total_pcm_bytes"])

    def test_archive_deduplicates_transport_but_restores_audio_store_accounting(self):
        source, public, matched = _ready_service()
        archive = export_service_archive(source, public["id"])
        doc = decode_archive(archive)["manifest"]
        self.assertEqual(len(doc["raw_material"]), 2)
        self.assertEqual(len(doc["playback_material"]), 2)
        self.assertEqual(doc["storage_accounting"]["unique_blob_count"], 2)
        self.assertEqual(doc["storage_accounting"]["playback_entries"], 2)
        self.assertEqual(
            {r["sha256"] for r in doc["raw_material"]},
            {r["sha256"] for r in doc["playback_material"]},
        )
        fresh = ListeningService(object())
        reopen_service_archive(fresh, archive)
        self.assertEqual(fresh.audio.accounting()["method"], "retained-pcm-physical-bytes-v1")
        self.assertEqual(fresh.audio.accounting()["total_pcm_bytes"], doc["storage_accounting"]["restored_pcm_bytes"])

    def test_corrupt_truncated_and_oversized_archives_fail_before_state_install(self):
        source, public, _ = _ready_service()
        archive = export_service_archive(source, public["id"])
        for damaged in (archive[:-1], archive[:-1] + bytes([archive[-1] ^ 1])):
            fresh = ListeningService(object())
            with self.assertRaises(ListeningError):
                reopen_service_archive(fresh, damaged)
            self.assertEqual(fresh.audio.accounting()["total_pcm_bytes"], 0)
            self.assertEqual(fresh.registry_accounting()["trial_count"], 0)
        with self.assertRaisesRegex(ListeningError, "blob-count"):
            export_service_archive(
                source,
                public["id"],
                limits=ListeningArchiveLimits(max_blob_count=1),
            )
        with self.assertRaisesRegex(ListeningError, "byte limit"):
            decode_archive(
                archive,
                limits=ListeningArchiveLimits(max_archive_bytes=len(archive) - 1),
            )

    def test_participant_archive_is_blind_and_cannot_be_reopened_as_trusted(self):
        source, public, _ = _ready_service(abx=True)
        trusted_id = source.participant_manifest(public["id"]).to_dict()["id"]
        archive = export_service_archive(source, public["id"], role="participant")
        manifest = decode_archive(archive)["manifest"]
        self.assertEqual(manifest["role"], "participant")
        encoded = json.dumps(manifest["bundle"], sort_keys=True)
        self.assertEqual(manifest["bundle"]["format"], "zaaggenz-listening-participant-bundle")
        self.assertNotIn("seed", manifest["bundle"]["trial"])
        self.assertIsNone(manifest["bundle"]["trial"]["abx_truth"])
        self.assertNotIn(trusted_id, encoded)
        with self.assertRaisesRegex(ListeningError, "cannot be reopened as trusted"):
            reopen_service_archive(ListeningService(object()), archive)

    def test_archive_has_no_filesystem_paths_and_hostile_stimulus_names_are_inert(self):
        source, public, _ = _ready_service(hostile_name=True)
        archive = export_service_archive(source, public["id"])
        manifest = decode_archive(archive)["manifest"]
        self.assertIn("../escape", {s["name"] for s in manifest["bundle"]["stimuli"]})
        for row in manifest["raw_material"] + manifest["playback_material"] + manifest["blobs"]:
            self.assertFalse(set(row) & {"path", "filename", "name"})
        fresh = ListeningService(object())
        reopen_service_archive(fresh, archive)
        self.assertEqual(fresh.registry_accounting()["trial_count"], 1)

    def test_atomic_publish_cancellation_preserves_existing_destination(self):
        source, public, _ = _ready_service()
        class Cancelled:
            def check(self):
                raise JobCancelled("cancelled archive publication")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "study.zgla"
            path.write_bytes(b"existing-complete-archive")
            with self.assertRaises(JobCancelled):
                publish_service_archive(source, public["id"], path, token=Cancelled())
            self.assertEqual(path.read_bytes(), b"existing-complete-archive")
            self.assertEqual([p.name for p in path.parent.iterdir()], ["study.zgla"])

    def test_legacy_metadata_bundle_still_fails_closed_in_fresh_runtime(self):
        source, public, _ = _ready_service()
        legacy = source.export_bundle(public["id"])
        with self.assertRaisesRegex(ListeningError, "missing.*regeneration is forbidden"):
            ListeningService(object()).reopen_bundle(legacy)


if __name__ == "__main__":
    unittest.main()
