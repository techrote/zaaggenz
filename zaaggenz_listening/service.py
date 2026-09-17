"""Local immutable listening material and bounded trial/result registry."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import secrets
import threading

from zaaggenz_contracts import digest
from zaaggenz_jobs import RenderArtifact, JobError

from .model import ListeningError, Stimulus, TrialManifest, TrialResult
from .stimulus import ListeningAudioStore
from .trial import (
    INSTRUCTIONS,
    make_participant_trial,
    make_result,
    make_trial,
    public_result,
    public_trial,
)


REGISTRY_ACCOUNTING_METHOD = "retained-listening-metadata-json-v1"
# A retained trial has two 64-byte identifiers stored in two opposite-direction
# lookup entries.  Counting 256 logical bytes is deliberately conservative for
# the identifier payload; cardinality limits separately bound Python container
# overhead, which is implementation-dependent rather than a portable contract.
TRIAL_INDEX_LOGICAL_BYTES = 256


@dataclass(frozen=True)
class ListeningRegistryLimits:
    """Executable envelope for the in-memory listening evidence registry.

    These are process-safety limits, not scientific sample-size guidance.  A
    future durable archive/store (#98) may support larger studies without
    retaining their complete evidence set in one process.
    """

    max_trials: int = 512
    max_results_per_trial: int = 4096
    max_total_results: int = 16384
    max_metadata_bytes: int = 64 * 1024 * 1024
    max_trial_result_bytes: int = 16 * 1024 * 1024
    max_export_bytes: int = 20 * 1024 * 1024

    def __post_init__(self):
        for name, value in asdict(self).items():
            if type(value) is not int or value <= 0:
                raise ListeningError(f"{name}: positive integer registry limit required")

    def to_dict(self):
        return asdict(self)


def _canonical_json_bytes(value) -> int:
    """Return canonical JSON byte length used by the registry budget contract."""

    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ListeningError(f"listening metadata is not strict JSON: {exc}") from exc
    return len(encoded)


class ListeningService:
    def __init__(self, timeline_service, *, registry_limits=None):
        self.timeline = timeline_service
        self.audio = ListeningAudioStore()
        self.registry_limits = (
            ListeningRegistryLimits()
            if registry_limits is None
            else registry_limits
        )
        if not isinstance(self.registry_limits, ListeningRegistryLimits):
            raise ListeningError("registry_limits must be ListeningRegistryLimits")

        self.trials = {}
        self.results = {}
        self._participant_to_trusted = {}
        self._trusted_to_participant = {}

        self._lock = threading.RLock()
        self._trial_bytes = {}
        self._result_bytes = {}
        self._trial_metadata_bytes = 0
        self._result_metadata_bytes = 0
        self._total_result_count = 0

    def freeze_job(self, job_id, name, start_frame=0, end_frame=None):
        try:
            artifact = self.timeline.artifact(job_id)
        except JobError as exc:
            raise ListeningError(str(exc)) from exc
        if not isinstance(artifact, RenderArtifact):
            raise ListeningError("completed render job required")
        stimulus = self.audio.add_artifact(
            name, artifact, start_frame=start_frame, end_frame=end_frame
        )
        return stimulus.to_dict()

    def match(self, stimulus_ids, target_rms_dbfs=None, peak_ceiling_dbfs=-3.0):
        return self.audio.match(
            stimulus_ids,
            target_rms_dbfs=target_rms_dbfs,
            peak_ceiling_dbfs=peak_ceiling_dbfs,
        )

    @staticmethod
    def _stimulus_metadata(stimuli):
        rows = {}
        for stimulus in stimuli:
            if not isinstance(stimulus, Stimulus):
                raise ListeningError(
                    "Stimulus required for result timing validation"
                )
            doc = stimulus.to_dict()
            rows[doc["id"]] = {
                "sample_rate_hz": doc["sample_rate_hz"],
                "frame_count": doc["frame_count"],
            }
        return rows

    def _trial_stimulus_metadata(self, trial):
        doc = trial.to_dict()
        return self._stimulus_metadata(
            [
                self.audio.stimulus(row["stimulus_id"])
                for row in doc["matched_stimuli"]
            ]
        )

    @staticmethod
    def _participant_id(value):
        if (
            type(value) is not str
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ListeningError(
                "participant trial ID must be lowercase SHA-256"
            )
        return value

    @staticmethod
    def _trial_cost(trial):
        return _canonical_json_bytes(trial.to_dict()) + TRIAL_INDEX_LOGICAL_BYTES

    @staticmethod
    def _result_cost(result):
        return _canonical_json_bytes(result.to_dict())

    def _metadata_bytes_locked(self):
        return self._trial_metadata_bytes + self._result_metadata_bytes

    def _check_admission_locked(
        self,
        trial_id,
        *,
        new_trial_cost=0,
        new_result_count=0,
        new_result_bytes=0,
    ):
        limits = self.registry_limits
        is_new_trial = trial_id not in self.trials
        if is_new_trial and len(self.trials) + 1 > limits.max_trials:
            raise ListeningError("listening trial registry limit exceeded")

        existing_count = len(self.results.get(trial_id, ()))
        if existing_count + new_result_count > limits.max_results_per_trial:
            raise ListeningError("listening per-trial result limit exceeded")
        if self._total_result_count + new_result_count > limits.max_total_results:
            raise ListeningError("listening total result limit exceeded")

        existing_result_bytes = self._result_bytes.get(trial_id, 0)
        if (
            existing_result_bytes + new_result_bytes
            > limits.max_trial_result_bytes
        ):
            raise ListeningError(
                "listening per-trial result-byte limit exceeded"
            )
        if (
            self._metadata_bytes_locked()
            + new_trial_cost
            + new_result_bytes
            > limits.max_metadata_bytes
        ):
            raise ListeningError(
                "listening registry metadata-byte limit exceeded"
            )

    def _new_participant_id_locked(self, participant_id=None):
        pid = (
            secrets.token_hex(32)
            if participant_id is None
            else participant_id
        )
        self._participant_id(pid)
        if pid in self._participant_to_trusted:
            raise ListeningError("participant trial ID collision")
        return pid

    def _install_trial_locked(self, trial, participant_id, trial_cost):
        tid = trial.to_dict()["id"]
        self.trials[tid] = trial
        self._participant_to_trusted[participant_id] = tid
        self._trusted_to_participant[tid] = participant_id
        self._trial_bytes[tid] = trial_cost
        self._result_bytes[tid] = 0
        self._trial_metadata_bytes += trial_cost

    def _register_trial(self, trial, participant_id=None):
        if not isinstance(trial, TrialManifest):
            raise ListeningError("TrialManifest required")
        tid = trial.to_dict()["id"]
        with self._lock:
            existing = self.trials.get(tid)
            if existing is not None:
                if existing.to_dict() != trial.to_dict():
                    raise ListeningError(
                        "trial identity collision with different manifest"
                    )
                pid = self._trusted_to_participant[tid]
                if participant_id is not None and participant_id != pid:
                    raise ListeningError(
                        "trial already has a different participant identity"
                    )
                return public_trial(existing, pid)

            trial_cost = self._trial_cost(trial)
            self._check_admission_locked(tid, new_trial_cost=trial_cost)
            pid = self._new_participant_id_locked(participant_id)
            public = public_trial(trial, pid)
            self._install_trial_locked(trial, pid, trial_cost)
            return public

    def create_trial(
        self,
        title,
        design,
        matched_stimuli,
        seed="0",
        endpoints=("liking", "sound_quality"),
        instruction_template=None,
    ):
        """Trusted/programmatic deterministic construction used by evidence/tests."""

        trial = make_trial(
            title,
            design,
            matched_stimuli,
            seed=seed,
            endpoints=endpoints,
            instruction_template=instruction_template,
        )
        return self._register_trial(trial)

    def create_participant_trial(
        self,
        title,
        design,
        matched_stimuli,
        seed="0",
        endpoints=("liking", "sound_quality"),
        instruction_template=None,
    ):
        """HTTP participant construction; ABX truth stays server-held."""

        hidden = None if design != "abx" else secrets.choice(("A", "B"))
        trial = make_participant_trial(
            title,
            design,
            matched_stimuli,
            seed=seed,
            endpoints=endpoints,
            instruction_template=instruction_template,
            hidden_abx_truth=hidden,
        )
        return self._register_trial(trial)

    def _trusted_id_locked(self, trial_id, *, participant_only=False):
        if trial_id in self._participant_to_trusted:
            return self._participant_to_trusted[trial_id]
        if not participant_only and trial_id in self.trials:
            return trial_id
        raise ListeningError("unknown trial")

    def _trusted_id(self, trial_id, *, participant_only=False):
        with self._lock:
            return self._trusted_id_locked(
                trial_id, participant_only=participant_only
            )

    def participant_manifest(self, participant_id):
        with self._lock:
            tid = self._trusted_id_locked(participant_id, participant_only=True)
            return self.trials[tid]

    def manifest(self, trial_id):
        with self._lock:
            return self.trials[self._trusted_id_locked(trial_id)]

    def _append_result_locked(self, tid, result):
        result_cost = self._result_cost(result)
        self._check_admission_locked(
            tid,
            new_result_count=1,
            new_result_bytes=result_cost,
        )
        self.results.setdefault(tid, []).append(result)
        self._result_bytes[tid] = self._result_bytes.get(tid, 0) + result_cost
        self._result_metadata_bytes += result_cost
        self._total_result_count += 1

    def submit(self, trial_id, payload):
        """Store one trusted result record.

        Bit-identical trusted submissions remain distinct records: the 1.0 result
        format has no respondent identity, so silently deduplicating them could
        discard legitimate repeated observations.  The bounded registry makes
        retry loops finite instead.  Participant submissions remain one-shot.
        """

        with self._lock:
            tid = self._trusted_id_locked(trial_id)
            trial = self.trials[tid]
            result = make_result(
                trial,
                stimulus_metadata=self._trial_stimulus_metadata(trial),
                **payload,
            )
            self._append_result_locked(tid, result)
            return {
                "result": result.to_dict(),
                "result_sha256": result.sha256,
            }

    def submit_participant(self, participant_id, payload):
        """One terminal participant response per public trial; retakes need a new trial."""

        with self._lock:
            tid = self._trusted_id_locked(
                participant_id, participant_only=True
            )
            trial = self.trials[tid]
            if self.results.get(tid):
                raise ListeningError(
                    "participant trial already has a terminal result; create a new trial for a retake"
                )
            result = make_result(
                trial,
                stimulus_metadata=self._trial_stimulus_metadata(trial),
                **payload,
            )
            self._append_result_locked(tid, result)
            view = public_result(result, participant_id)
            return {
                "result": view,
                "result_sha256": digest(
                    {
                        "domain": "zaaggenz.listening-participant-result-v1",
                        "result": view,
                    }
                ),
            }

    def registry_accounting(self):
        """Return the authoritative in-memory metadata admission accounting."""

        with self._lock:
            return {
                "method": REGISTRY_ACCOUNTING_METHOD,
                "limits": self.registry_limits.to_dict(),
                "trial_count": len(self.trials),
                "result_count": self._total_result_count,
                "trial_metadata_bytes": self._trial_metadata_bytes,
                "result_metadata_bytes": self._result_metadata_bytes,
                "metadata_bytes": self._metadata_bytes_locked(),
                "trial_index_logical_bytes_per_trial": TRIAL_INDEX_LOGICAL_BYTES,
            }

    def _trusted_export_size_locked(self, tid, stimuli, manifest, result_count):
        base = {
            "format": "zaaggenz-listening-bundle",
            "version": "1.0.0",
            "stimuli": stimuli,
            "manifest": manifest,
            "results": [],
        }
        # The base already contains the two bytes for [].  Replacing that empty
        # array with N canonical result objects therefore adds exactly the sum
        # of their canonical sizes plus N-1 commas.
        return (
            _canonical_json_bytes(base)
            + self._result_bytes.get(tid, 0)
            + max(0, result_count - 1)
        )

    def export_bundle(self, trial_id):
        """Trusted archival export. Never expose this through participant capability."""

        with self._lock:
            tid = self._trusted_id_locked(trial_id)
            trial = self.trials[tid]
            manifest = trial.to_dict()
            stimuli = [
                self.audio.stimulus(row["stimulus_id"]).to_dict()
                for row in manifest["matched_stimuli"]
            ]
            retained = tuple(self.results.get(tid, ()))
            export_bytes = self._trusted_export_size_locked(
                tid, stimuli, manifest, len(retained)
            )
            if export_bytes > self.registry_limits.max_export_bytes:
                raise ListeningError("listening export byte limit exceeded")
        return {
            "format": "zaaggenz-listening-bundle",
            "version": "1.0.0",
            "stimuli": stimuli,
            "manifest": manifest,
            "results": [result.to_dict() for result in retained],
        }

    def export_participant_bundle(self, participant_id):
        """Participant-safe export: no seed, trusted trial ID, truth or score oracle."""

        with self._lock:
            tid = self._trusted_id_locked(
                participant_id, participant_only=True
            )
            trial = self.trials[tid]
            manifest = trial.to_dict()
            stimuli = [
                self.audio.stimulus(row["stimulus_id"]).to_dict()
                for row in manifest["matched_stimuli"]
            ]
            retained = tuple(self.results.get(tid, ()))
            # Participant submission is terminal, so this list has at most one
            # element.  Materialising its safe projection cannot amplify with
            # study cardinality; still enforce the same export byte ceiling.
            public_results = [
                public_result(result, participant_id) for result in retained
            ]
            bundle = {
                "format": "zaaggenz-listening-participant-bundle",
                "version": "1.0.0",
                "role": "participant",
                "stimuli": stimuli,
                "trial": public_trial(trial, participant_id),
                "results": public_results,
            }
            if (
                _canonical_json_bytes(bundle)
                > self.registry_limits.max_export_bytes
            ):
                raise ListeningError("listening export byte limit exceeded")
            return bundle

    def reopen_bundle(self, bundle):
        """Validate then atomically install a trusted metadata-only 1.0 bundle.

        Version 1.0 still requires playback bytes to be resident; #98 owns the
        durable self-contained archive.  Reopen never overwrites or merges a
        different result sequence into an existing trial.
        """

        if (
            type(bundle) is not dict
            or set(bundle) != {"format", "version", "stimuli", "manifest", "results"}
            or bundle["format"] != "zaaggenz-listening-bundle"
            or bundle["version"] != "1.0.0"
        ):
            raise ListeningError("invalid trusted listening bundle")

        raw_results = bundle["results"]
        if type(raw_results) is not list:
            raise ListeningError("trusted listening bundle results must be a list")
        if len(raw_results) > self.registry_limits.max_results_per_trial:
            raise ListeningError("listening per-trial result limit exceeded")
        if len(raw_results) > self.registry_limits.max_total_results:
            raise ListeningError("listening total result limit exceeded")

        trial = TrialManifest(bundle["manifest"])
        stimuli = [Stimulus(row) for row in bundle["stimuli"]]
        trial_doc = trial.to_dict()
        if {stimulus.to_dict()["id"] for stimulus in stimuli} != {
            row["stimulus_id"] for row in trial_doc["matched_stimuli"]
        }:
            raise ListeningError(
                "bundle stimulus provenance does not match trial"
            )
        for row in trial_doc["matched_stimuli"]:
            if not self.audio.has_playback(row["playback_sha256"]):
                raise ListeningError(
                    "bundle playback bytes are missing; silent regeneration is forbidden"
                )

        metadata = self._stimulus_metadata(stimuli)
        results = []
        result_bytes = 0
        for row in raw_results:
            result = TrialResult(row, trial, stimulus_metadata=metadata)
            result_bytes += self._result_cost(result)
            if result_bytes > self.registry_limits.max_trial_result_bytes:
                raise ListeningError(
                    "listening per-trial result-byte limit exceeded"
                )
            if result_bytes > self.registry_limits.max_metadata_bytes:
                raise ListeningError(
                    "listening registry metadata-byte limit exceeded"
                )
            results.append(result)

        tid = trial_doc["id"]
        with self._lock:
            existing = self.trials.get(tid)
            if existing is not None:
                existing_results = self.results.get(tid, [])
                if existing.to_dict() != trial_doc or [
                    result.to_dict() for result in existing_results
                ] != [result.to_dict() for result in results]:
                    raise ListeningError(
                        "reopen conflicts with existing retained trial/results; existing evidence is unchanged"
                    )
                pid = self._trusted_to_participant[tid]
                return {
                    "trial": public_trial(existing, pid),
                    "results": [result.to_dict() for result in existing_results],
                }

            trial_cost = self._trial_cost(trial)
            self._check_admission_locked(
                tid,
                new_trial_cost=trial_cost,
                new_result_count=len(results),
                new_result_bytes=result_bytes,
            )
            pid = self._new_participant_id_locked()
            public = public_trial(trial, pid)

            # No mutation occurs until every object, playback identity and
            # resource limit above has succeeded.
            self._install_trial_locked(trial, pid, trial_cost)
            if results:
                self.results[tid] = list(results)
                self._result_bytes[tid] = result_bytes
                self._result_metadata_bytes += result_bytes
                self._total_result_count += len(results)
            return {
                "trial": public,
                "results": [result.to_dict() for result in results],
            }

    @property
    def templates(self):
        return deepcopy(INSTRUCTIONS)
