from __future__ import annotations

import hashlib
import json
import queue
import threading
import unittest
from unittest.mock import patch

import numpy as np

from zaaggenz_jobs import RenderArtifact
from zaaggenz_listening import (
    ListeningError,
    ListeningRegistryLimits,
    ListeningService,
    TrialResult,
)


A_VALUES = [0.25, -0.5, 0.375, -0.125, 0.2, -0.4, 0.3, -0.1]
B_VALUES = [0.4, -0.1, 0.2, -0.35, 0.1, -0.3, 0.45, -0.2]


def _artifact(label: str, values) -> RenderArtifact:
    pcm = np.asarray(values, dtype="<f4").tobytes()
    content_sha = hashlib.sha256(pcm).hexdigest()
    identity = hashlib.sha256(label.encode("utf-8")).hexdigest()
    recipe = hashlib.sha256((label + ":recipe").encode("utf-8")).hexdigest()
    cache = hashlib.sha256((label + ":cache").encode("utf-8")).hexdigest()
    return RenderArtifact(
        identity,
        recipe,
        "synth",
        cache,
        pcm,
        {
            "kind": "AudioAssetRef",
            "version": "1.0.0",
            "content_sha256": content_sha,
            "identity_domain": "pcm-f32le-interleaved-v1",
            "sample_rate_hz": 48000,
            "channels": 1,
            "channel_layout": "mono",
            "frame_count": len(values),
            "level_domain": "source",
            "sample_policy": "unclamped_float",
        },
        {},
    )


def _limits(**overrides):
    values = ListeningRegistryLimits().to_dict()
    values.update(overrides)
    return ListeningRegistryLimits(**values)


def _prepared_service(limits=None):
    service = ListeningService(object(), registry_limits=limits)
    a = service.audio.add_artifact("A", _artifact("registry-a", A_VALUES))
    b = service.audio.add_artifact("B", _artifact("registry-b", B_VALUES))
    matched = service.match(
        [a.to_dict()["id"], b.to_dict()["id"]], target_rms_dbfs=-60.0
    )
    return service, matched


def _trial(service, matched, *, title="Registry", seed="0"):
    return service.create_trial(
        title,
        "ab",
        matched,
        seed=seed,
        endpoints=("liking",),
        instruction_template="neutral-ab",
    )


def _payload(trial, *, note="", annotations=None):
    order = trial["presentation_order"]
    return {
        "status": "completed",
        "choice": order[0],
        "ratings": {"liking": 50},
        "confidence": 60,
        "effort": 20,
        "comfortable_level": 50,
        "replay_counts": {sid: 1 for sid in order},
        "x_replay_count": 0,
        "annotations": [] if annotations is None else annotations,
        "note": note,
    }


def _canonical_size(value):
    return len(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


class RegistryBudgetTests(unittest.TestCase):
    def test_accounting_is_explicit_and_normal_result_export_is_unchanged(self):
        service, matched = _prepared_service()
        trial = _trial(service, matched)
        receipt = service.submit(trial["id"], _payload(trial, note="kept"))
        accounting = service.registry_accounting()
        self.assertEqual(accounting["method"], "retained-listening-metadata-json-v1")
        self.assertEqual(accounting["trial_count"], 1)
        self.assertEqual(accounting["result_count"], 1)
        self.assertEqual(
            accounting["metadata_bytes"],
            accounting["trial_metadata_bytes"] + accounting["result_metadata_bytes"],
        )
        self.assertLessEqual(
            accounting["metadata_bytes"], accounting["limits"]["max_metadata_bytes"]
        )
        bundle = service.export_bundle(trial["id"])
        self.assertEqual(bundle["version"], "1.0.0")
        self.assertEqual(bundle["results"], [receipt["result"]])

    def test_trial_cardinality_accepts_exact_limit_and_limit_plus_one_is_nonmutating(self):
        service, matched = _prepared_service(_limits(max_trials=2))
        _trial(service, matched, title="one", seed="1")
        _trial(service, matched, title="two", seed="2")
        before = service.registry_accounting()
        participant_before = dict(service._participant_to_trusted)
        trusted_before = dict(service._trusted_to_participant)
        with self.assertRaisesRegex(ListeningError, "trial registry limit exceeded"):
            _trial(service, matched, title="three", seed="3")
        self.assertEqual(service.registry_accounting(), before)
        self.assertEqual(service._participant_to_trusted, participant_before)
        self.assertEqual(service._trusted_to_participant, trusted_before)

    def test_repeated_identical_trusted_results_are_intentionally_distinct_but_bounded(self):
        service, matched = _prepared_service(
            _limits(max_results_per_trial=3, max_total_results=3)
        )
        trial = _trial(service, matched)
        payload = _payload(trial, note="same observation bytes")
        hashes = [service.submit(trial["id"], payload)["result_sha256"] for _ in range(3)]
        self.assertEqual(len(set(hashes)), 1)
        self.assertEqual(service.registry_accounting()["result_count"], 3)
        self.assertEqual(len(service.export_bundle(trial["id"])["results"]), 3)
        before = service.registry_accounting()
        with self.assertRaisesRegex(ListeningError, "per-trial result limit exceeded"):
            service.submit(trial["id"], payload)
        self.assertEqual(service.registry_accounting(), before)

    def test_total_result_limit_is_shared_across_trials(self):
        service, matched = _prepared_service(
            _limits(max_results_per_trial=3, max_total_results=3)
        )
        first = _trial(service, matched, title="first", seed="1")
        second = _trial(service, matched, title="second", seed="2")
        service.submit(first["id"], _payload(first, note="1"))
        service.submit(first["id"], _payload(first, note="2"))
        service.submit(second["id"], _payload(second, note="3"))
        before = service.registry_accounting()
        with self.assertRaisesRegex(ListeningError, "total result limit exceeded"):
            service.submit(second["id"], _payload(second, note="4"))
        self.assertEqual(service.registry_accounting(), before)

    def test_result_and_total_metadata_byte_boundaries_are_exact_and_nonmutating(self):
        probe, matched = _prepared_service()
        probe_trial = _trial(probe, matched, title="byte-boundary", seed="11")
        probe.submit(probe_trial["id"], _payload(probe_trial, note="byte probe"))
        measured = probe.registry_accounting()
        trial_bytes = measured["trial_metadata_bytes"]
        result_bytes = measured["result_metadata_bytes"]

        exact, exact_matched = _prepared_service(
            _limits(
                max_trials=1,
                max_results_per_trial=1,
                max_total_results=1,
                max_metadata_bytes=trial_bytes + result_bytes,
                max_trial_result_bytes=result_bytes,
            )
        )
        exact_trial = _trial(exact, exact_matched, title="byte-boundary", seed="11")
        exact.submit(exact_trial["id"], _payload(exact_trial, note="byte probe"))
        self.assertEqual(
            exact.registry_accounting()["metadata_bytes"], trial_bytes + result_bytes
        )

        below, below_matched = _prepared_service(
            _limits(
                max_trials=1,
                max_results_per_trial=1,
                max_total_results=1,
                max_metadata_bytes=trial_bytes + result_bytes,
                max_trial_result_bytes=result_bytes - 1,
            )
        )
        below_trial = _trial(below, below_matched, title="byte-boundary", seed="11")
        before = below.registry_accounting()
        with self.assertRaisesRegex(ListeningError, "result-byte limit exceeded"):
            below.submit(below_trial["id"], _payload(below_trial, note="byte probe"))
        self.assertEqual(below.registry_accounting(), before)
        self.assertEqual(below.results.get(below._participant_to_trusted[below_trial["id"]]), None)

    def test_maximal_annotation_records_stop_at_byte_budget_without_partial_append(self):
        annotations = [
            {
                "stimulus_id": None,
                "time_seconds": 0.0,
                "label": "boundary",
                "note": "x" * 1000,
            }
            for _ in range(256)
        ]
        probe, matched = _prepared_service()
        probe_trial = _trial(probe, matched, title="annotations", seed="12")
        for row in annotations:
            row["stimulus_id"] = probe_trial["presentation_order"][0]
        probe.submit(
            probe_trial["id"],
            _payload(probe_trial, note="maximal", annotations=annotations),
        )
        one_result_bytes = probe.registry_accounting()["result_metadata_bytes"]

        service, matched = _prepared_service(
            _limits(max_trial_result_bytes=one_result_bytes * 2 - 1)
        )
        trial = _trial(service, matched, title="annotations", seed="12")
        annotations2 = [dict(row, stimulus_id=trial["presentation_order"][0]) for row in annotations]
        payload = _payload(trial, note="maximal", annotations=annotations2)
        service.submit(trial["id"], payload)
        before = service.registry_accounting()
        with self.assertRaisesRegex(ListeningError, "result-byte limit exceeded"):
            service.submit(trial["id"], payload)
        self.assertEqual(service.registry_accounting(), before)
        trusted = service._participant_to_trusted[trial["id"]]
        self.assertEqual(len(service.results[trusted]), 1)

    def test_export_limit_is_checked_before_result_materialisation(self):
        probe, matched = _prepared_service()
        probe_trial = _trial(probe, matched, title="export-boundary", seed="13")
        probe.submit(probe_trial["id"], _payload(probe_trial, note="export"))
        exact_bundle_size = _canonical_size(probe.export_bundle(probe_trial["id"]))

        service, matched = _prepared_service(
            _limits(max_export_bytes=exact_bundle_size - 1)
        )
        trial = _trial(service, matched, title="export-boundary", seed="13")
        service.submit(trial["id"], _payload(trial, note="export"))
        with patch.object(
            TrialResult,
            "to_dict",
            side_effect=AssertionError("result materialised before export preflight"),
        ):
            with self.assertRaisesRegex(ListeningError, "export byte limit exceeded"):
                service.export_bundle(trial["id"])

    def test_reopen_exact_limit_succeeds_and_over_limit_is_atomic(self):
        source, matched = _prepared_service()
        trial = _trial(source, matched, title="reopen", seed="14")
        source.submit(trial["id"], _payload(trial, note="one"))
        one_bundle = source.export_bundle(trial["id"])
        measured = source.registry_accounting()

        target, _ = _prepared_service(
            _limits(
                max_trials=1,
                max_results_per_trial=1,
                max_total_results=1,
                max_metadata_bytes=measured["metadata_bytes"],
                max_trial_result_bytes=measured["result_metadata_bytes"],
            )
        )
        reopened = target.reopen_bundle(one_bundle)
        self.assertEqual(reopened["results"], one_bundle["results"])
        self.assertEqual(target.registry_accounting()["result_count"], 1)

        source.submit(trial["id"], _payload(trial, note="two"))
        two_bundle = source.export_bundle(trial["id"])
        over, _ = _prepared_service(
            _limits(max_trials=1, max_results_per_trial=1, max_total_results=1)
        )
        before = over.registry_accounting()
        with self.assertRaisesRegex(ListeningError, "per-trial result limit exceeded"):
            over.reopen_bundle(two_bundle)
        self.assertEqual(over.registry_accounting(), before)
        self.assertEqual(over.trials, {})
        self.assertEqual(over.results, {})

    def test_reopen_cannot_overwrite_or_merge_existing_evidence(self):
        source, matched = _prepared_service()
        trial = _trial(source, matched, title="reopen-conflict", seed="15")
        source.submit(trial["id"], _payload(trial, note="one"))
        first = source.export_bundle(trial["id"])

        target, _ = _prepared_service()
        target.reopen_bundle(first)
        before = target.registry_accounting()
        source.submit(trial["id"], _payload(trial, note="two"))
        changed = source.export_bundle(trial["id"])
        with self.assertRaisesRegex(ListeningError, "existing evidence is unchanged"):
            target.reopen_bundle(changed)
        self.assertEqual(target.registry_accounting(), before)
        self.assertEqual(target.export_bundle(trial["id"]), first)

    def test_concurrent_trusted_submissions_share_one_locked_limit(self):
        service, matched = _prepared_service(
            _limits(max_results_per_trial=8, max_total_results=8)
        )
        trial = _trial(service, matched, title="concurrent", seed="16")
        payload = _payload(trial, note="parallel")
        barrier = threading.Barrier(16)
        outcomes = queue.Queue()

        def worker():
            barrier.wait(timeout=10)
            try:
                service.submit(trial["id"], payload)
                outcomes.put("ok")
            except ListeningError:
                outcomes.put("rejected")

        threads = [threading.Thread(target=worker) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())

        values = [outcomes.get_nowait() for _ in range(16)]
        self.assertEqual(values.count("ok"), 8)
        self.assertEqual(values.count("rejected"), 8)
        self.assertEqual(service.registry_accounting()["result_count"], 8)
        trusted = service._participant_to_trusted[trial["id"]]
        self.assertEqual(len(service.results[trusted]), 8)

    def test_invalid_limits_fail_before_service_state_exists(self):
        for name in ListeningRegistryLimits().to_dict():
            values = ListeningRegistryLimits().to_dict()
            values[name] = 0
            with self.subTest(name=name), self.assertRaisesRegex(
                ListeningError, "positive integer"
            ):
                ListeningRegistryLimits(**values)


if __name__ == "__main__":
    unittest.main(verbosity=2)
