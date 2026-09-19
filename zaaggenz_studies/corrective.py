"""Corrective trust-boundary layer for the accepted ZG-040 study scaffold.

The original 1.0 scaffold deliberately kept statistics small and explicit, but
post-merge adversarial review found that its dataset hashes were labels rather
than evidence authentication, its planned-cell accounting could disappear
missing observations, iterable inputs were consumed more than once, and its
resampling allocations were not bounded by an executable resource envelope.

This module is the public ZG-040 analysis surface after that review.  It keeps
synthetic fixtures available for calibration, while real participant evidence
must be constructed from content-addressed ZG-015 TrialManifest/TrialResult
objects under a prospective, content-addressed evidence plan.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
from typing import Callable, Iterable, Mapping

import numpy as np
from scipy import stats

from zaaggenz_contracts import digest
from zaaggenz_contracts.model import check_json, loads
from zaaggenz_listening.model import TrialManifest, TrialResult, ListeningError

from . import model as _model
from . import analysis as _legacy_analysis
from . import design as _design


EVIDENCE_PLAN_FORMAT = "zaaggenz-study-evidence-plan"
EVIDENCE_PLAN_VERSION = "1.0.0"
DATASET_VERSION = "1.1.0"
MAX_DATASET_ROWS = 131_072
MAX_AUDIT_RECORDS = 256
MAX_ANALYSIS_PAIRS = 4_096
MAX_RESAMPLE_CELLS = 8_000_000
RESAMPLE_BATCH_ROWS = 256
MIN_MONTE_CARLO_DRAWS = 1_024
MAX_RANDOMISATION_DRAWS = 32_768
MAX_BOOTSTRAP_DRAWS = 4_096
MAX_COUNTERBALANCE_CELLS = 131_072


def _canonical(value):
    try:
        check_json(value)
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise _model.StudyError(f"strict bounded JSON required: {exc}") from exc


def _snapshot(values, cls, name, limit=MAX_AUDIT_RECORDS):
    """Own one bounded immutable copy of a caller iterable exactly once."""
    if isinstance(values, (str, bytes, bytearray)):
        raise _model.StudyError(f"{name} must be an iterable of {cls.__name__}")
    owned = []
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise _model.StudyError(f"{name} must be iterable") from exc
    for value in iterator:
        if len(owned) >= limit:
            raise _model.StudyError(f"{name} exceeds bounded limit {limit}")
        if not isinstance(value, cls):
            raise _model.StudyError(f"{name} requires {cls.__name__} values")
        owned.append(value)
    return tuple(owned)


def _manifest_maps(manifest):
    doc = manifest.to_dict()
    endpoints = {row["id"]: row for row in doc["endpoints"]}
    stimuli = {row["id"]: row for row in doc["stimuli"]}
    return doc, endpoints, stimuli


def _validate_corrective_manifest(manifest):
    if not isinstance(manifest, _model.StudyManifest):
        raise _model.StudyError("StudyManifest required")
    doc, endpoints, _ = _manifest_maps(manifest)

    # One physical playback identity cannot be counted as two statistical items.
    playback_owner = {}
    raw_families = {}
    family_condition = {}
    for row in doc["stimuli"]:
        playback = row["playback_sha256"]
        if playback in playback_owner and playback_owner[playback] != row["id"]:
            raise _model.StudyError(
                "duplicate playback identity cannot be relabelled as another stimulus/item"
            )
        playback_owner[playback] = row["id"]
        raw_families.setdefault(row["raw_pcm_sha256"], set()).add(row["family"])
        key = (row["family"], row["condition"])
        if key in family_condition:
            raise _model.StudyError(
                "each frozen item family may contain only one stimulus per condition"
            )
        family_condition[key] = row["id"]
    if any(len(families) > 1 for families in raw_families.values()):
        raise _model.StudyError(
            "one raw physical stimulus cannot be relabelled across statistical item families"
        )

    for contrast in doc["contrasts"]:
        endpoint = endpoints[contrast["endpoint"]]
        families_a = {
            row["family"] for row in doc["stimuli"]
            if row["condition"] == contrast["condition_a"]
        }
        families_b = {
            row["family"] for row in doc["stimuli"]
            if row["condition"] == contrast["condition_b"]
        }
        if not families_a or families_a != families_b:
            raise _model.StudyError(
                "contrast conditions must have the same frozen physical item families"
            )
        method = contrast["method"]
        estimand = contrast["estimand"]
        scale = endpoint["scale"]
        if method == "crossed-row-column-conservative-v1":
            if estimand != "mean-difference":
                raise _model.StudyError(
                    "crossed-row-column-conservative-v1 computes mean-difference only"
                )
            if scale not in ("bounded-continuous", "ordinal", "binary"):
                raise _model.StudyError(
                    "crossed mean-difference is unsupported for this endpoint scale"
                )
        elif method == "paired-cell-randomisation-v1":
            if estimand not in ("mean-difference", "median-difference"):
                raise _model.StudyError(
                    "paired-cell-randomisation-v1 supports mean/median difference only"
                )
            if scale not in ("bounded-continuous", "ordinal", "binary", "choice"):
                raise _model.StudyError("paired method is incompatible with endpoint scale")
            if doc["randomisation"]["method"] != "within-cell-pair-v1":
                raise _model.StudyError(
                    "paired analysis requires within-cell-pair-v1 assignment at freeze time"
                )
        elif method == "descriptive-only-v1":
            if contrast["primary"]:
                raise _model.StudyError(
                    "descriptive-only-v1 cannot be a confirmatory primary contrast"
                )
        else:
            raise _model.StudyError("unsupported contrast method")

    if doc["mode"] == "confirmatory":
        declared = set(doc["analysis"]["confirmatory_methods"])
        if "descriptive-only-v1" in declared:
            raise _model.StudyError(
                "descriptive-only-v1 cannot be declared as a confirmatory method"
            )
    return True


def freeze_manifest(manifest):
    """Freeze only manifests whose endpoint/estimand/method contract is executable."""
    _validate_corrective_manifest(manifest)
    return _model.freeze_manifest(manifest)


def _endpoint_source_name(endpoint_id):
    return endpoint_id.replace("-", "_")


def _extract_assignment_value(assignment, endpoint, trial, result):
    result_doc = result.to_dict()
    trial_doc = trial.to_dict()
    extraction = assignment["extraction"]
    if result_doc["status"] != "completed":
        return None, "missing"
    if extraction == "rating":
        source = _endpoint_source_name(assignment["endpoint"])
        if source not in result_doc["ratings"]:
            raise _model.StudyError(
                f"ZG-015 result does not contain frozen rating endpoint {source!r}"
            )
        if trial_doc["presentation_order"][0] != assignment["stimulus_id"]:
            raise _model.StudyError(
                "rating evidence requires the frozen focus stimulus first in presentation_order"
            )
        value = result_doc["ratings"][source]
    elif extraction == "choice-indicator":
        if trial_doc["design"] == "abx":
            raise _model.StudyError("choice-indicator does not reinterpret ABX A/B choice")
        value = 1.0 if result_doc["choice"] == assignment["stimulus_id"] else 0.0
    elif extraction == "abx-correct":
        if trial_doc["design"] != "abx" or result_doc["abx_correct"] is None:
            raise _model.StudyError("abx-correct extraction requires completed ZG-015 ABX evidence")
        value = 1.0 if result_doc["abx_correct"] else 0.0
    else:
        raise _model.StudyError("unsupported evidence extraction")
    return _legacy_analysis._endpoint_value(value, endpoint), "completed"


@dataclass(frozen=True, init=False)
class StudyEvidencePlan:
    """Prospective assignment/schedule binding between a freeze and ZG-015 trials."""

    _json: str

    def __init__(self, document):
        if type(document) is not dict or set(document) != {
            "format", "version", "freeze_id", "manifest_sha256", "trials",
            "assignments", "id",
        }:
            raise _model.StudyError("invalid study evidence plan envelope")
        if document["format"] != EVIDENCE_PLAN_FORMAT or document["version"] != EVIDENCE_PLAN_VERSION:
            raise _model.StudyError("unsupported study evidence plan format/version")
        _model._sha(document["freeze_id"], "evidence_plan.freeze_id")
        _model._sha(document["manifest_sha256"], "evidence_plan.manifest_sha256")
        _model._sha(document["id"], "evidence_plan.id")
        if type(document["trials"]) is not list or not document["trials"]:
            raise _model.StudyError("evidence plan requires ZG-015 trial manifests")
        trials = [TrialManifest(row) for row in document["trials"]]
        trial_ids = [trial.to_dict()["id"] for trial in trials]
        if trial_ids != sorted(trial_ids) or len(set(trial_ids)) != len(trial_ids):
            raise _model.StudyError("evidence plan trials must be unique and trial-id sorted")
        assignments = document["assignments"]
        if type(assignments) is not list or not assignments or len(assignments) > MAX_DATASET_ROWS:
            raise _model.StudyError("evidence plan assignment count is outside bounded envelope")
        keys = {
            "participant_index", "participant_id", "item_id", "condition",
            "stimulus_id", "trial_id", "endpoint", "extraction",
        }
        seen = set()
        for row in assignments:
            if type(row) is not dict or set(row) != keys:
                raise _model.StudyError("invalid evidence-plan assignment fields")
            _model._integer(row["participant_index"], 0, 1_000_000, "participant_index")
            _model._identifier(row["participant_id"], "participant_id")
            _model._identifier(row["item_id"], "item_id")
            _model._identifier(row["condition"], "condition")
            _model._sha(row["stimulus_id"], "stimulus_id")
            _model._sha(row["trial_id"], "trial_id")
            _model._identifier(row["endpoint"], "endpoint")
            if row["trial_id"] not in trial_ids:
                raise _model.StudyError("assignment references trial absent from evidence plan")
            if row["extraction"] not in ("rating", "choice-indicator", "abx-correct"):
                raise _model.StudyError("unsupported evidence extraction")
            key = (
                row["participant_index"], row["item_id"], row["condition"], row["endpoint"]
            )
            if key in seen:
                raise _model.StudyError("duplicate planned participant/item/condition/endpoint cell")
            seen.add(key)
        payload = {k: deepcopy(v) for k, v in document.items() if k != "id"}
        expected = digest({"domain": "zaaggenz-study-evidence-plan-v1", "plan": payload})
        if document["id"] != expected:
            raise _model.StudyError("study evidence plan identity mismatch")
        object.__setattr__(self, "_json", _canonical(document))

    def to_dict(self):
        return loads(self._json)

    @property
    def sha256(self):
        return self.to_dict()["id"]


def freeze_evidence_plan(frozen, assignments, trials):
    """Bind the complete max-sample assignment schedule before outcome analysis."""
    if not isinstance(frozen, _model.FrozenStudy):
        raise _model.StudyError("FrozenStudy required")
    manifest = frozen.manifest
    _validate_corrective_manifest(manifest)
    doc, endpoints, stimuli = _manifest_maps(manifest)

    trial_objects = tuple(trials)
    if not trial_objects or any(not isinstance(t, TrialManifest) for t in trial_objects):
        raise _model.StudyError("ZG-015 TrialManifest values required")
    trial_docs = sorted((t.to_dict() for t in trial_objects), key=lambda row: row["id"])
    trial_map = {row["id"]: TrialManifest(row) for row in trial_docs}
    if len(trial_map) != len(trial_docs):
        raise _model.StudyError("duplicate trial identity in evidence plan")

    owned = []
    for raw in assignments:
        if len(owned) >= MAX_DATASET_ROWS:
            raise _model.StudyError("evidence plan exceeds bounded assignment limit")
        if type(raw) is not dict:
            raise _model.StudyError("evidence assignment must be an object")
        row = deepcopy(raw)
        expected_keys = {
            "participant_index", "participant_id", "item_id", "condition",
            "stimulus_id", "trial_id", "endpoint", "extraction",
        }
        if set(row) != expected_keys:
            raise _model.StudyError("invalid evidence assignment fields")
        if row["stimulus_id"] not in stimuli:
            raise _model.StudyError("assignment references stimulus outside frozen manifest")
        stimulus = stimuli[row["stimulus_id"]]
        if row["item_id"] != stimulus["family"] or row["condition"] != stimulus["condition"]:
            raise _model.StudyError(
                "assignment item/condition must come from frozen stimulus identity"
            )
        if row["endpoint"] not in endpoints:
            raise _model.StudyError("assignment references endpoint outside frozen manifest")
        if row["trial_id"] not in trial_map:
            raise _model.StudyError("assignment references unknown ZG-015 trial")
        trial_doc = trial_map[row["trial_id"]].to_dict()
        presented = {entry["stimulus_id"] for entry in trial_doc["matched_stimuli"]}
        if row["stimulus_id"] not in presented:
            raise _model.StudyError("assigned stimulus is not present in referenced ZG-015 trial")
        if row["extraction"] == "rating":
            source = _endpoint_source_name(row["endpoint"])
            if source not in trial_doc["endpoints"]:
                raise _model.StudyError("trial does not predeclare the frozen rating endpoint")
            if trial_doc["presentation_order"][0] != row["stimulus_id"]:
                raise _model.StudyError("rating assignment must freeze focus stimulus first")
        elif row["extraction"] == "choice-indicator":
            if endpoints[row["endpoint"]]["scale"] not in ("binary", "choice"):
                raise _model.StudyError("choice extraction requires binary/choice study endpoint")
            if trial_doc["design"] == "abx":
                raise _model.StudyError("ABX evidence must use abx-correct extraction")
        elif row["extraction"] == "abx-correct":
            if endpoints[row["endpoint"]]["scale"] != "binary" or trial_doc["design"] != "abx":
                raise _model.StudyError("abx-correct requires a binary endpoint and ABX trial")
        else:
            raise _model.StudyError("unsupported evidence extraction")
        owned.append(row)

    participants = {}
    for row in owned:
        idx = row["participant_index"]
        existing = participants.setdefault(idx, row["participant_id"])
        if existing != row["participant_id"]:
            raise _model.StudyError("participant index has conflicting pseudonymous identities")
    expected_indices = list(range(doc["stopping_rule"]["max_participants"]))
    if sorted(participants) != expected_indices:
        raise _model.StudyError(
            "evidence plan must preallocate every participant slot through stopping_rule.max_participants"
        )

    # Every planned participant must have every frozen item/condition cell needed
    # by every contrast. This makes omitted rows observable as missing later.
    assignment_keys = {
        (r["participant_index"], r["item_id"], r["condition"], r["endpoint"])
        for r in owned
    }
    for contrast in doc["contrasts"]:
        families = sorted({
            row["family"] for row in doc["stimuli"]
            if row["condition"] == contrast["condition_a"]
        })
        for participant_index in expected_indices:
            for family in families:
                for condition in (contrast["condition_a"], contrast["condition_b"]):
                    key = (participant_index, family, condition, contrast["endpoint"])
                    if key not in assignment_keys:
                        raise _model.StudyError(
                            "evidence plan omits a frozen participant/item/condition/endpoint cell"
                        )

    owned.sort(key=lambda r: (
        r["participant_index"], r["item_id"], r["endpoint"], r["condition"], r["trial_id"]
    ))
    document = {
        "format": EVIDENCE_PLAN_FORMAT,
        "version": EVIDENCE_PLAN_VERSION,
        "freeze_id": frozen.sha256,
        "manifest_sha256": manifest.sha256,
        "trials": trial_docs,
        "assignments": owned,
    }
    document["id"] = digest({"domain": "zaaggenz-study-evidence-plan-v1", "plan": document})
    return StudyEvidencePlan(document)


class StudyDataset:
    """Immutable statistical dataset with explicit evidence authority.

    Direct construction is retained *only* as the synthetic-fixture path used by
    deterministic calibration. Real study evidence must use ``from_zg015``.
    The authority is machine-readable in both dataset identity and reports.
    """

    def __init__(self, document, manifest):
        self._initialise_synthetic(document, manifest)

    @classmethod
    def synthetic(cls, document, manifest):
        obj = cls.__new__(cls)
        obj._initialise_synthetic(document, manifest)
        return obj

    def _initialise_synthetic(self, document, manifest):
        _validate_corrective_manifest(manifest)
        payload = _normalise_rows(document, manifest, evidence_authority="synthetic-fixture")
        self._json = _canonical(payload)
        self._authority = "synthetic-fixture"
        self._evidence_plan_sha256 = None

    @classmethod
    def from_zg015(
        cls,
        manifest,
        plan,
        results,
        *,
        excluded_trials=None,
    ):
        _validate_corrective_manifest(manifest)
        if not isinstance(plan, StudyEvidencePlan):
            raise _model.StudyError("StudyEvidencePlan required")
        plan_doc = plan.to_dict()
        if plan_doc["manifest_sha256"] != manifest.sha256:
            raise _model.StudyError("evidence plan is not bound to this study manifest")
        trial_map = {row["id"]: TrialManifest(row) for row in plan_doc["trials"]}
        if type(results) is not dict:
            raise _model.StudyError("ZG-015 results must be a trial-id keyed object")
        excluded_trials = {} if excluded_trials is None else dict(excluded_trials)
        known_trial_ids = set(trial_map)
        if set(results) - known_trial_ids or set(excluded_trials) - known_trial_ids:
            raise _model.StudyError("result/exclusion references trial outside frozen evidence plan")

        verified = {}
        for trial_id, evidence in results.items():
            if type(evidence) is not dict or set(evidence) != {"result", "result_sha256"}:
                raise _model.StudyError(
                    "result evidence must contain exact result and result_sha256 fields"
                )
            result_value = evidence["result"]
            try:
                result = result_value if isinstance(result_value, TrialResult) else TrialResult(
                    result_value, trial_map[trial_id]
                )
                # Revalidate even an existing object against the exact frozen trial.
                result = TrialResult(result.to_dict(), trial_map[trial_id])
            except ListeningError as exc:
                raise _model.StudyError(f"invalid ZG-015 result evidence: {exc}") from exc
            if result.to_dict()["trial_id"] != trial_id:
                raise _model.StudyError("ZG-015 result/trial identity mismatch")
            if evidence["result_sha256"] != result.sha256:
                raise _model.StudyError(
                    "ZG-015 result SHA-256 does not authenticate supplied outcome content"
                )
            verified[trial_id] = result

        # Determine the attempted prefix. Later participants cannot be cherry-picked
        # while earlier planned slots disappear: any later result activates all prior
        # slots and their omitted trials become explicit missing observations.
        assignments = plan_doc["assignments"]
        active_indices = [
            row["participant_index"] for row in assignments if row["trial_id"] in verified
        ]
        cutoff = max(active_indices) if active_indices else -1
        endpoints = {row["id"]: row for row in manifest.to_dict()["endpoints"]}
        rows = []
        result_bindings = {}
        for assignment in assignments:
            if assignment["participant_index"] > cutoff:
                continue
            trial_id = assignment["trial_id"]
            result = verified.get(trial_id)
            exclusion_id = excluded_trials.get(trial_id)
            if exclusion_id is not None:
                allowed = {row["id"] for row in manifest.to_dict()["exclusions"]}
                if exclusion_id not in allowed:
                    raise _model.StudyError("trial exclusion is not predeclared in manifest")
                if result is not None and result.to_dict()["status"] == "completed":
                    raise _model.StudyError("completed trusted result cannot be post-hoc excluded")
                value, status = None, "excluded"
                result_sha = result.sha256 if result is not None else None
            elif result is None:
                value, status, result_sha = None, "missing", None
            else:
                value, status = _extract_assignment_value(
                    assignment,
                    endpoints[assignment["endpoint"]],
                    trial_map[trial_id],
                    result,
                )
                result_sha = result.sha256

            if result_sha is not None:
                binding = (
                    assignment["participant_id"], assignment["item_id"],
                    assignment["endpoint"], trial_id,
                )
                previous = result_bindings.setdefault(result_sha, binding)
                if previous != binding:
                    raise _model.StudyError(
                        "one physical ZG-015 result cannot be relabelled across participant/item inference units"
                    )

            rows.append({
                "participant_id": assignment["participant_id"],
                "participant_index": assignment["participant_index"],
                "item_id": assignment["item_id"],
                "stimulus_id": assignment["stimulus_id"],
                "trial_id": trial_id,
                "result_sha256": result_sha,
                "condition": assignment["condition"],
                "endpoint": assignment["endpoint"],
                "value": value,
                "status": status,
                "exclusion_id": exclusion_id,
                "familiarity": None,
            })
        payload = {
            "format": "zaaggenz-study-dataset",
            "version": DATASET_VERSION,
            "manifest_sha256": manifest.sha256,
            "evidence_authority": "zg015-content-verified",
            "evidence_plan_sha256": plan.sha256,
            "rows": rows,
        }
        obj = cls.__new__(cls)
        obj._json = _canonical(payload)
        obj._authority = "zg015-content-verified"
        obj._evidence_plan_sha256 = plan.sha256
        return obj

    def to_dict(self):
        return loads(self._json)

    @property
    def authority(self):
        return self._authority

    @property
    def evidence_plan_sha256(self):
        return self._evidence_plan_sha256

    @property
    def sha256(self):
        return digest({"domain": "zaaggenz-study-dataset-v1.1", "dataset": self.to_dict()})


def _normalise_rows(document, manifest, *, evidence_authority):
    if type(document) is not dict or set(document) != {
        "format", "version", "manifest_sha256", "rows"
    }:
        raise _model.StudyError("invalid synthetic study dataset envelope")
    if document["format"] != "zaaggenz-study-dataset" or document["version"] not in (
        _model.VERSION, DATASET_VERSION
    ):
        raise _model.StudyError("unsupported study dataset format/version")
    if document["manifest_sha256"] != manifest.sha256:
        raise _model.StudyError("dataset manifest binding mismatch")
    doc, endpoints, stimuli = _manifest_maps(manifest)
    exclusion_ids = {row["id"] for row in doc["exclusions"]}
    rows = document["rows"]
    if type(rows) is not list or not 1 <= len(rows) <= MAX_DATASET_ROWS:
        raise _model.StudyError(
            f"dataset rows must contain 1..{MAX_DATASET_ROWS} bounded observations"
        )
    normalised = []
    seen = set()
    participant_indices = {}
    for serial, raw in enumerate(rows):
        expected = {
            "participant_id", "item_id", "stimulus_id", "trial_id",
            "result_sha256", "condition", "endpoint", "value", "status",
            "exclusion_id", "familiarity",
        }
        if type(raw) is not dict or set(raw) != expected:
            raise _model.StudyError("dataset row has missing or unknown fields")
        participant = _legacy_analysis._id(raw["participant_id"], "participant_id")
        item = _legacy_analysis._id(raw["item_id"], "item_id")
        stimulus = _legacy_analysis._sha(raw["stimulus_id"], "stimulus_id")
        endpoint_id = _legacy_analysis._id(raw["endpoint"], "endpoint")
        condition = _legacy_analysis._id(raw["condition"], "condition")
        if stimulus not in stimuli:
            raise _model.StudyError("dataset row references stimulus outside manifest")
        binding = stimuli[stimulus]
        if item != binding["family"]:
            raise _model.StudyError(
                "dataset item_id is authoritative frozen stimulus.family; relabelling is rejected"
            )
        if condition != binding["condition"]:
            raise _model.StudyError("dataset condition disagrees with frozen stimulus binding")
        if endpoint_id not in endpoints:
            raise _model.StudyError("dataset row references endpoint outside manifest")
        if raw["status"] not in ("completed", "missing", "excluded"):
            raise _model.StudyError("invalid dataset observation status")
        value = raw["value"]
        exclusion_id = raw["exclusion_id"]
        if raw["status"] == "completed":
            if exclusion_id is not None:
                raise _model.StudyError("completed observation cannot carry exclusion_id")
            value = _legacy_analysis._endpoint_value(value, endpoints[endpoint_id])
        else:
            if value is not None:
                raise _model.StudyError("missing/excluded observation must have null value")
            if raw["status"] == "excluded" and exclusion_id not in exclusion_ids:
                raise _model.StudyError("excluded observation requires predeclared exclusion_id")
            if raw["status"] == "missing" and exclusion_id is not None:
                raise _model.StudyError("missing observation cannot carry exclusion_id")
        familiarity = raw["familiarity"]
        if familiarity is not None:
            familiarity = _legacy_analysis._finite(familiarity, 0, 100, "familiarity")
        key = (participant, item, endpoint_id, condition)
        if key in seen:
            raise _model.StudyError("duplicate participant/item/endpoint/condition observation")
        seen.add(key)
        participant_indices.setdefault(participant, len(participant_indices))
        normalised.append({
            **deepcopy(raw),
            "participant_id": participant,
            "participant_index": participant_indices[participant],
            "item_id": item,
            "stimulus_id": stimulus,
            "trial_id": raw["trial_id"],
            "result_sha256": raw["result_sha256"],
            "condition": condition,
            "endpoint": endpoint_id,
            "value": value,
            "exclusion_id": exclusion_id,
            "familiarity": familiarity,
        })
    return {
        "format": "zaaggenz-study-dataset",
        "version": DATASET_VERSION,
        "manifest_sha256": manifest.sha256,
        "evidence_authority": evidence_authority,
        "evidence_plan_sha256": None,
        "rows": normalised,
    }


def _contrast_expected(manifest, dataset, contrast):
    rows = dataset.to_dict()["rows"]
    endpoint = contrast["endpoint"]
    a, b = contrast["condition_a"], contrast["condition_b"]
    families = sorted({
        row["family"] for row in manifest["stimuli"] if row["condition"] == a
    })
    participants = sorted({
        (row["participant_index"], row["participant_id"])
        for row in rows if row["endpoint"] == endpoint
    })
    cells = {}
    for row in rows:
        if row["endpoint"] != endpoint or row["condition"] not in (a, b):
            continue
        cells[(row["participant_id"], row["item_id"], row["condition"])] = row
    diffs = []
    missing = 0
    for _, participant in participants:
        for item in families:
            left = cells.get((participant, item, a))
            right = cells.get((participant, item, b))
            if left is None or right is None or left["status"] != "completed" or right["status"] != "completed":
                missing += 1
                continue
            diffs.append((participant, item, float(right["value"]) - float(left["value"])))
    planned = len(participants) * len(families)
    missing_fraction = 1.0 if planned == 0 else missing / planned
    return diffs, planned, missing_fraction, participants, families


def _resampling_plan(n):
    if type(n) is not int or not 1 <= n <= MAX_ANALYSIS_PAIRS:
        raise _model.StudyError(
            f"paired analysis requires 1..{MAX_ANALYSIS_PAIRS} complete pairs"
        )
    exact = n <= 16
    randomisation_draws = (1 << n) if exact else min(
        MAX_RANDOMISATION_DRAWS,
        MAX_RESAMPLE_CELLS // n,
    )
    bootstrap_draws = min(MAX_BOOTSTRAP_DRAWS, MAX_RESAMPLE_CELLS // n)
    if randomisation_draws < MIN_MONTE_CARLO_DRAWS or bootstrap_draws < MIN_MONTE_CARLO_DRAWS:
        raise _model.StudyError(
            "resampling work exceeds authoritative bounded work envelope"
        )
    batch = min(RESAMPLE_BATCH_ROWS, randomisation_draws, bootstrap_draws)
    max_batch_bytes = batch * n * 8 + batch * n * 4 + batch * 16
    return {
        "pair_count": n,
        "exact_randomisation": exact,
        "randomisation_draws": randomisation_draws,
        "bootstrap_draws": bootstrap_draws,
        "batch_rows": batch,
        "max_resample_cells": MAX_RESAMPLE_CELLS,
        "max_batch_bytes_estimate": max_batch_bytes,
        "randomisation_work_cells": randomisation_draws * n,
        "bootstrap_work_cells": bootstrap_draws * n,
    }


def _cancelled(cancel):
    return cancel is not None and bool(cancel())


def _emit_progress(progress, phase, done, total):
    if progress is not None:
        progress({"phase": phase, "completed": int(done), "total": int(total)})


def _paired_bounded(diffs, alpha, direction, estimand, seed, *, cancel=None, progress=None):
    values = np.asarray([v for _, _, v in diffs], dtype=np.float64)
    n = len(values)
    if n < 2:
        return {"state": "inconclusive", "reason": "paired method requires at least two complete pairs"}
    plan = _resampling_plan(n)
    observed = _legacy_analysis._statistic(values, estimand)
    rng = np.random.default_rng(seed)
    total = plan["randomisation_draws"]
    extreme = 0
    done = 0
    if plan["exact_randomisation"]:
        # Enumerate sign masks in bounded batches without materialising 2**n × n.
        while done < total:
            if _cancelled(cancel):
                raise _model.StudyError("analysis cancelled during randomisation")
            count = min(plan["batch_rows"], total - done)
            masks = np.arange(done, done + count, dtype=np.uint64)[:, None]
            bits = (masks >> np.arange(n, dtype=np.uint64)[None, :]) & 1
            signs = np.where(bits, 1.0, -1.0)
            if estimand == "mean-difference":
                stats_rows = np.mean(signs * values, axis=1)
            else:
                stats_rows = np.median(signs * values, axis=1)
            if direction == "greater":
                extreme += int(np.count_nonzero(stats_rows >= observed - 1e-15))
            elif direction == "less":
                extreme += int(np.count_nonzero(stats_rows <= observed + 1e-15))
            else:
                extreme += int(np.count_nonzero(np.abs(stats_rows) >= abs(observed) - 1e-15))
            done += count
            _emit_progress(progress, "randomisation", done, total)
    else:
        while done < total:
            if _cancelled(cancel):
                raise _model.StudyError("analysis cancelled during randomisation")
            count = min(plan["batch_rows"], total - done)
            signs = rng.choice(np.asarray((-1.0, 1.0)), size=(count, n))
            if estimand == "mean-difference":
                stats_rows = np.mean(signs * values, axis=1)
            else:
                stats_rows = np.median(signs * values, axis=1)
            if direction == "greater":
                extreme += int(np.count_nonzero(stats_rows >= observed - 1e-15))
            elif direction == "less":
                extreme += int(np.count_nonzero(stats_rows <= observed + 1e-15))
            else:
                extreme += int(np.count_nonzero(np.abs(stats_rows) >= abs(observed) - 1e-15))
            done += count
            _emit_progress(progress, "randomisation", done, total)
    p_value = float((extreme + 1) / (total + 1))

    draws = plan["bootstrap_draws"]
    boot = np.empty(draws, dtype=np.float64)
    done = 0
    while done < draws:
        if _cancelled(cancel):
            raise _model.StudyError("analysis cancelled during bootstrap")
        count = min(plan["batch_rows"], draws - done)
        indices = rng.integers(0, n, size=(count, n), dtype=np.int32)
        sampled = values[indices]
        if estimand == "mean-difference":
            boot[done:done + count] = np.mean(sampled, axis=1)
        else:
            boot[done:done + count] = np.median(sampled, axis=1)
        done += count
        _emit_progress(progress, "bootstrap", done, draws)
    lo, hi = np.quantile(boot, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {
        "state": "analysed",
        "effect": observed,
        "standard_error": float(np.std(boot, ddof=1)),
        "ci_low": float(lo),
        "ci_high": float(hi),
        "confidence_level": 1.0 - alpha,
        "p_value": p_value,
        "df": None,
        "participants": len({p for p, _, _ in diffs}),
        "items": len({i for _, i, _ in diffs}),
        "complete_pairs": n,
        "uncertainty_method": f"paired-cell-bootstrap-{draws}-bounded-v1",
        "test_method": "paired-cell-sign-randomisation-bounded-v1",
        "resampling": plan,
    }


def _descriptive_bounded(diffs, alpha, estimand, seed, *, cancel=None, progress=None):
    values = np.asarray([v for _, _, v in diffs], dtype=np.float64)
    if not len(values):
        return {"state": "inconclusive", "reason": "no complete pairs"}
    effect = _legacy_analysis._statistic(values, estimand)
    if len(values) == 1:
        return {
            "state": "analysed", "effect": effect, "standard_error": None,
            "ci_low": None, "ci_high": None, "confidence_level": None,
            "p_value": None, "df": None, "participants": 1, "items": 1,
            "complete_pairs": 1, "uncertainty_method": "descriptive-only-v1",
        }
    plan = _resampling_plan(len(values))
    draws = plan["bootstrap_draws"]
    rng = np.random.default_rng(seed)
    boot = np.empty(draws, dtype=np.float64)
    done = 0
    while done < draws:
        if _cancelled(cancel):
            raise _model.StudyError("analysis cancelled during descriptive bootstrap")
        count = min(plan["batch_rows"], draws - done)
        idx = rng.integers(0, len(values), size=(count, len(values)), dtype=np.int32)
        sampled = values[idx]
        if estimand == "mean-difference":
            boot[done:done + count] = np.mean(sampled, axis=1)
        else:
            boot[done:done + count] = np.median(sampled, axis=1)
        done += count
        _emit_progress(progress, "descriptive-bootstrap", done, draws)
    lo, hi = np.quantile(boot, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {
        "state": "analysed", "effect": effect,
        "standard_error": float(np.std(boot, ddof=1)),
        "ci_low": float(lo), "ci_high": float(hi),
        "confidence_level": 1.0 - alpha, "p_value": None, "df": None,
        "participants": len({p for p, _, _ in diffs}),
        "items": len({i for _, i, _ in diffs}), "complete_pairs": len(values),
        "uncertainty_method": f"descriptive-paired-bootstrap-{draws}-bounded-v1",
        "resampling": plan,
    }


def _stopping_status(manifest, dataset, rows):
    rule = manifest["stopping_rule"]
    ds_rows = dataset.to_dict()["rows"]
    participants = sorted({row["participant_id"] for row in ds_rows})
    participant_count = len(participants)
    if participant_count > rule["max_participants"]:
        raise _model.StudyError("dataset exceeds frozen stopping_rule.max_participants")
    if rule["kind"] == "fixed-complete-cases":
        target = rule["max_participants"]
        if participant_count < target:
            return False, f"fixed-complete-cases requires {target} planned participants; observed prefix has {participant_count}"
        # Fixed complete cases means each primary planned cell must be complete.
        primary = [row for row in rows if row["primary"]]
        if any(row["missing_fraction"] > 0 for row in primary):
            return False, "fixed-complete-cases stopping rule has incomplete planned primary cells"
        return True, "fixed complete-case target reached"
    if participant_count < rule["min_participants"]:
        return False, "precision stopping rule has not reached minimum participants"
    target_endpoint = rule["endpoint"]
    endpoint_rows = [row for row in rows if row["endpoint"] == target_endpoint and row.get("state") == "analysed"]
    reached = any(
        row.get("ci_low") is not None and row.get("ci_high") is not None
        and (row["ci_high"] - row["ci_low"]) / 2.0 <= rule["target_ci_half_width"]
        for row in endpoint_rows
    )
    if reached:
        return True, "precision target reached after frozen minimum participants"
    if participant_count >= rule["max_participants"]:
        return True, "frozen maximum participants reached without optional precision target"
    return False, "precision target not yet reached and maximum participants not yet attempted"


def analyse_study(
    frozen,
    current_manifest,
    dataset,
    *,
    amendments=(),
    deviations=(),
    cancel: Callable[[], bool] | None = None,
    progress: Callable[[dict], None] | None = None,
):
    if not isinstance(frozen, _model.FrozenStudy) or not isinstance(current_manifest, _model.StudyManifest):
        raise _model.StudyError("FrozenStudy and StudyManifest required")
    _validate_corrective_manifest(current_manifest)
    if not isinstance(dataset, StudyDataset):
        raise _model.StudyError("corrected StudyDataset required")
    amendment_snapshot = _snapshot(amendments, _model.StudyAmendment, "amendments")
    deviation_snapshot = _snapshot(deviations, _model.StudyDeviation, "deviations")
    _model.verify_amendment_chain(frozen, amendment_snapshot, current_manifest)
    ds = dataset.to_dict()
    if ds["manifest_sha256"] != current_manifest.sha256:
        raise _model.StudyError("dataset is not bound to current authorised study manifest")
    for deviation in deviation_snapshot:
        if deviation.to_dict()["freeze_id"] != frozen.sha256:
            raise _model.StudyError("deviation does not belong to frozen study")

    manifest = current_manifest.to_dict()
    alpha = float(manifest["analysis"]["alpha"])
    seed_base = int(manifest["randomisation"]["seed"])
    after_outcome_amendment = any(
        row.to_dict()["phase"] == "after-outcome-access" for row in amendment_snapshot
    )
    confirmatory_invalid = after_outcome_amendment or any(
        row.to_dict()["impact"] == "confirmatory-invalidated" for row in deviation_snapshot
    )

    rows = []
    for index, contrast in enumerate(manifest["contrasts"]):
        if _cancelled(cancel):
            raise _model.StudyError("analysis cancelled before contrast execution")
        diffs, planned_cells, missing_fraction, participants, families = _contrast_expected(
            manifest, dataset, contrast
        )
        result = {
            "contrast_id": contrast["id"], "endpoint": contrast["endpoint"],
            "condition_a": contrast["condition_a"], "condition_b": contrast["condition_b"],
            "estimand": contrast["estimand"], "method": contrast["method"],
            "primary": contrast["primary"], "planned_cells": planned_cells,
            "planned_participants": len(participants), "planned_items": len(families),
            "missing_fraction": missing_fraction,
        }
        if missing_fraction > manifest["missing_data"]["max_fraction"]:
            result.update(state="inconclusive", reason="predeclared missing-data threshold exceeded", complete_pairs=len(diffs))
        elif len(diffs) < manifest["missing_data"]["min_complete_pairs"]:
            result.update(state="inconclusive", reason="predeclared minimum complete pairs not reached", complete_pairs=len(diffs))
        else:
            direction = _legacy_analysis._contrast_direction(manifest, contrast["id"])
            method = contrast["method"]
            if method == "crossed-row-column-conservative-v1":
                result.update(_legacy_analysis._crossed_conservative(diffs, alpha, direction))
            elif method == "paired-cell-randomisation-v1":
                result.update(_paired_bounded(
                    diffs, alpha, direction, contrast["estimand"],
                    seed_base + index * 104729, cancel=cancel, progress=progress,
                ))
            elif method == "descriptive-only-v1":
                result.update(_descriptive_bounded(
                    diffs, alpha, contrast["estimand"], seed_base + index * 104729,
                    cancel=cancel, progress=progress,
                ))
            else:
                raise _model.StudyError("unsupported contrast method")
        rows.append(result)

    stopping_met, stopping_reason = _stopping_status(manifest, dataset, rows)
    confirmatory = [row for row in rows if row["primary"]]
    exploratory = [row for row in rows if not row["primary"]]
    if manifest["mode"] == "confirmatory" and not confirmatory_invalid:
        confirmatory = _legacy_analysis._holm(confirmatory)
    else:
        exploratory = deepcopy(confirmatory) + exploratory
        for row in exploratory:
            row["analysis_status"] = "exploratory"
        confirmatory = []

    if manifest["mode"] == "exploratory":
        completion = {"status": "complete-exploratory", "reason": "study was explicitly exploratory; no confirmatory claim is produced"}
    elif confirmatory_invalid:
        completion = {"status": "inconclusive", "reason": "confirmatory interpretation invalidated by post-outcome amendment/deviation; results retained as exploratory"}
    elif not stopping_met:
        completion = {"status": "inconclusive", "reason": stopping_reason}
    elif any(row.get("state") != "analysed" or row.get("p_value") is None for row in confirmatory):
        completion = {"status": "inconclusive", "reason": "at least one primary contrast lacks executable frozen confirmatory inference"}
    else:
        detected = any(row.get("p_adjusted", row["p_value"]) <= alpha for row in confirmatory)
        completion = {
            "status": "complete-difference-detected" if detected else "complete-null-compatible",
            "reason": (
                "at least one primary contrast crossed the frozen multiplicity-adjusted alpha"
                if detected else
                "planned primary evidence is compatible with zero at the frozen alpha; this does not prove equality"
            ),
        }

    report = {
        "format": "zaaggenz-study-report", "version": _model.VERSION,
        "freeze_id": frozen.sha256, "manifest_sha256": current_manifest.sha256,
        "dataset_sha256": dataset.sha256,
        "evidence_authority": dataset.authority,
        "evidence_plan_sha256": dataset.evidence_plan_sha256,
        "claim_scope": (
            "zg015-verified-participant-evidence"
            if dataset.authority == "zg015-content-verified"
            else "synthetic-fixture-only-no-participant-claim"
        ),
        "stopping_rule": {"met": stopping_met, "reason": stopping_reason},
        "confirmatory": confirmatory, "exploratory": exploratory,
        "amendments": [row.to_dict() for row in amendment_snapshot],
        "deviations": [row.to_dict() for row in deviation_snapshot],
        "completion": completion,
    }
    try:
        check_json(report)
    except (TypeError, ValueError) as exc:
        raise _model.StudyError(f"analysis report is not strict JSON: {exc}") from exc
    report["report_sha256"] = digest({"domain": "zaaggenz-study-report-v1-corrective", "report": report})
    return report


def balanced_cyclic_orders(conditions, participant_count, *, seed="0"):
    conditions = tuple(conditions)
    if type(participant_count) is not int or type(participant_count) is bool:
        raise _model.StudyError("participant_count must be an integer")
    cells = participant_count * len(conditions)
    if cells > MAX_COUNTERBALANCE_CELLS:
        raise _model.StudyError(
            f"counterbalance work exceeds bounded {MAX_COUNTERBALANCE_CELLS}-cell envelope"
        )
    return _design.balanced_cyclic_orders(conditions, participant_count, seed=seed)


# Re-export unchanged design helpers through the corrective public surface.
SimulationAssumptions = _design.SimulationAssumptions
simulate_crossed_design = _design.simulate_crossed_design
plan_precision = _design.plan_precision
