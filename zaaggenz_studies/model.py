from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import json
import math
import re

from zaaggenz_contracts import digest
from zaaggenz_contracts.model import check_json, loads, seed_value

VERSION = "1.0.0"
FAMILIES = (
    "reference-ablation",
    "chordness-tuning",
    "linked-return",
    "variation-meter-gesture",
    "vocal-participation",
    "grammar-learning",
)
MODES = ("confirmatory", "exploratory")
SCALES = ("bounded-continuous", "ordinal", "binary", "choice")
METHODS = (
    "crossed-row-column-conservative-v1",
    "paired-cell-randomisation-v1",
    "descriptive-only-v1",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class StudyError(ValueError):
    pass


def _exact(value, keys, name):
    if type(value) is not dict or set(value) != set(keys):
        raise StudyError(f"{name}: missing or unknown fields")


def _text(value, name, limit=2048):
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > limit
        or any(ord(ch) < 32 and ch not in "\n\t" for ch in value)
    ):
        raise StudyError(f"{name}: non-empty bounded text required")
    return value


def _identifier(value, name):
    if type(value) is not str or not IDENTIFIER.fullmatch(value):
        raise StudyError(f"{name}: canonical lowercase identifier required")
    return value


def _sha(value, name):
    if type(value) is not str or not HEX64.fullmatch(value):
        raise StudyError(f"{name}: lowercase SHA-256 required")
    return value


def _finite(value, lo, hi, name):
    if (
        type(value) not in (int, float)
        or type(value) is bool
        or not math.isfinite(float(value))
        or not lo <= float(value) <= hi
    ):
        raise StudyError(f"{name}: finite value in {lo}..{hi} required")
    return float(value)


def _integer(value, lo, hi, name):
    if type(value) is not int or type(value) is bool or not lo <= value <= hi:
        raise StudyError(f"{name}: integer {lo}..{hi} required")
    return value


def _seed(value):
    try:
        seed_value(value)
    except ValueError as exc:
        raise StudyError(str(exc)) from exc
    return value


def _strict_json(value, name):
    try:
        check_json(value)
    except (TypeError, ValueError) as exc:
        raise StudyError(f"{name}: strict bounded JSON required: {exc}") from exc
    return deepcopy(value)


def _validate_stimulus(row):
    _exact(
        row,
        {"id", "raw_pcm_sha256", "playback_sha256", "family", "condition"},
        "stimulus binding",
    )
    for key in ("id", "raw_pcm_sha256", "playback_sha256"):
        _sha(row[key], f"stimulus.{key}")
    _identifier(row["family"], "stimulus.family")
    _identifier(row["condition"], "stimulus.condition")


def _validate_endpoint(row):
    _exact(row, {"id", "scale", "minimum", "maximum"}, "endpoint")
    _identifier(row["id"], "endpoint.id")
    if row["scale"] not in SCALES:
        raise StudyError("endpoint.scale: unsupported scale")
    if row["scale"] in ("bounded-continuous", "ordinal"):
        lo = _finite(row["minimum"], -1e9, 1e9, "endpoint.minimum")
        hi = _finite(row["maximum"], -1e9, 1e9, "endpoint.maximum")
        if not lo < hi:
            raise StudyError("endpoint range must be increasing")
    elif row["minimum"] is not None or row["maximum"] is not None:
        raise StudyError("binary/choice endpoints do not use numeric range")


def _validate_contrast(row, endpoint_ids, conditions):
    _exact(
        row,
        {
            "id",
            "endpoint",
            "condition_a",
            "condition_b",
            "estimand",
            "method",
            "primary",
        },
        "contrast",
    )
    _identifier(row["id"], "contrast.id")
    if row["endpoint"] not in endpoint_ids:
        raise StudyError("contrast references unknown endpoint")
    for key in ("condition_a", "condition_b"):
        _identifier(row[key], f"contrast.{key}")
        if row[key] not in conditions:
            raise StudyError("contrast references unknown condition")
    if row["condition_a"] == row["condition_b"]:
        raise StudyError("contrast conditions must differ")
    if row["estimand"] not in ("mean-difference", "median-difference", "choice-proportion"):
        raise StudyError("unsupported contrast estimand")
    if row["method"] not in METHODS:
        raise StudyError("unsupported contrast method")
    if type(row["primary"]) is not bool:
        raise StudyError("contrast.primary must be boolean")


def validate_manifest(document):
    _strict_json(document, "study manifest")
    _exact(
        document,
        {
            "format",
            "version",
            "title",
            "family",
            "mode",
            "questions",
            "hypotheses",
            "stimuli",
            "matching",
            "randomisation",
            "endpoints",
            "contrasts",
            "exclusions",
            "missing_data",
            "stopping_rule",
            "analysis",
            "privacy",
        },
        "study manifest",
    )
    if document["format"] != "zaaggenz-study-manifest" or document["version"] != VERSION:
        raise StudyError("unsupported study manifest format/version")
    _text(document["title"], "title", 160)
    if document["family"] not in FAMILIES:
        raise StudyError("unsupported study family")
    if document["mode"] not in MODES:
        raise StudyError("study mode must be confirmatory or exploratory")

    questions = document["questions"]
    if type(questions) is not list or not 1 <= len(questions) <= 32:
        raise StudyError("1..32 study questions required")
    for value in questions:
        _text(value, "question", 1024)

    hypotheses = document["hypotheses"]
    if type(hypotheses) is not list or len(hypotheses) > 32:
        raise StudyError("hypotheses must be a list of at most 32 rows")
    hids = set()
    for row in hypotheses:
        _exact(row, {"id", "text", "direction"}, "hypothesis")
        hid = _identifier(row["id"], "hypothesis.id")
        if hid in hids:
            raise StudyError("duplicate hypothesis id")
        hids.add(hid)
        _text(row["text"], "hypothesis.text", 1024)
        if row["direction"] not in ("two-sided", "greater", "less"):
            raise StudyError("invalid hypothesis direction")

    stimuli = document["stimuli"]
    if type(stimuli) is not list or not 2 <= len(stimuli) <= 256:
        raise StudyError("2..256 immutable stimulus bindings required")
    stimulus_ids = set()
    for row in stimuli:
        _validate_stimulus(row)
        if row["id"] in stimulus_ids:
            raise StudyError("duplicate stimulus binding")
        stimulus_ids.add(row["id"])
    conditions = {row["condition"] for row in stimuli}
    if len(conditions) < 2:
        raise StudyError("study requires at least two stimulus conditions")

    matching = document["matching"]
    _exact(
        matching,
        {"method", "target_rms_dbfs", "peak_ceiling_dbfs", "true_peak_measured"},
        "matching",
    )
    if matching["method"] != "whole-file-rms-common-target-v1":
        raise StudyError("study must bind the accepted ZG-015 matching method")
    if matching["target_rms_dbfs"] is not None:
        _finite(matching["target_rms_dbfs"], -120, 0, "matching.target_rms_dbfs")
    _finite(matching["peak_ceiling_dbfs"], -60, 0, "matching.peak_ceiling_dbfs")
    if type(matching["true_peak_measured"]) is not bool:
        raise StudyError("matching.true_peak_measured must be boolean")

    randomisation = document["randomisation"]
    _exact(randomisation, {"method", "seed", "counterbalanced"}, "randomisation")
    if randomisation["method"] not in (
        "balanced-cyclic-v1",
        "within-cell-pair-v1",
        "fixed-order-exploratory-v1",
    ):
        raise StudyError("unsupported randomisation method")
    _seed(randomisation["seed"])
    if type(randomisation["counterbalanced"]) is not bool:
        raise StudyError("randomisation.counterbalanced must be boolean")
    if document["mode"] == "confirmatory" and randomisation["method"] == "fixed-order-exploratory-v1":
        raise StudyError("confirmatory study cannot use exploratory fixed ordering")

    endpoints = document["endpoints"]
    if type(endpoints) is not list or not 1 <= len(endpoints) <= 32:
        raise StudyError("1..32 endpoint definitions required")
    endpoint_ids = set()
    for row in endpoints:
        _validate_endpoint(row)
        if row["id"] in endpoint_ids:
            raise StudyError("duplicate endpoint id")
        endpoint_ids.add(row["id"])

    contrasts = document["contrasts"]
    if type(contrasts) is not list or not 1 <= len(contrasts) <= 64:
        raise StudyError("1..64 contrast definitions required")
    contrast_ids = set()
    for row in contrasts:
        _validate_contrast(row, endpoint_ids, conditions)
        if row["id"] in contrast_ids:
            raise StudyError("duplicate contrast id")
        contrast_ids.add(row["id"])
    primary = [row for row in contrasts if row["primary"]]
    if document["mode"] == "confirmatory" and not primary:
        raise StudyError("confirmatory study requires at least one primary contrast")

    exclusions = document["exclusions"]
    if type(exclusions) is not list or len(exclusions) > 32:
        raise StudyError("exclusions must be a list of at most 32 rules")
    exclusion_ids = set()
    for row in exclusions:
        _exact(row, {"id", "rule", "timing"}, "exclusion")
        eid = _identifier(row["id"], "exclusion.id")
        if eid in exclusion_ids:
            raise StudyError("duplicate exclusion id")
        exclusion_ids.add(eid)
        _text(row["rule"], "exclusion.rule", 1024)
        if row["timing"] != "pre-outcome":
            raise StudyError("confirmatory exclusion rules must be outcome-independent/pre-outcome")

    missing = document["missing_data"]
    _exact(missing, {"strategy", "max_fraction", "min_complete_pairs"}, "missing_data")
    if missing["strategy"] != "available-pairs-with-threshold-v1":
        raise StudyError("unsupported missing-data policy")
    _finite(missing["max_fraction"], 0, 1, "missing_data.max_fraction")
    _integer(missing["min_complete_pairs"], 2, 1000000, "missing_data.min_complete_pairs")

    stopping = document["stopping_rule"]
    _exact(
        stopping,
        {
            "kind",
            "min_participants",
            "max_participants",
            "target_ci_half_width",
            "endpoint",
        },
        "stopping_rule",
    )
    if stopping["kind"] not in ("fixed-complete-cases", "precision-target"):
        raise StudyError("unsupported stopping rule")
    lo = _integer(stopping["min_participants"], 2, 1000000, "stopping_rule.min_participants")
    hi = _integer(stopping["max_participants"], 2, 1000000, "stopping_rule.max_participants")
    if lo > hi:
        raise StudyError("stopping participant bounds reversed")
    if stopping["kind"] == "precision-target":
        _finite(stopping["target_ci_half_width"], 1e-12, 1e9, "stopping_rule.target_ci_half_width")
        if stopping["endpoint"] not in endpoint_ids:
            raise StudyError("precision stopping rule references unknown endpoint")
    elif stopping["target_ci_half_width"] is not None or stopping["endpoint"] is not None:
        raise StudyError("fixed stopping rule must not carry a precision target")

    analysis = document["analysis"]
    _exact(analysis, {"alpha", "multiplicity", "confirmatory_methods"}, "analysis")
    _finite(analysis["alpha"], 1e-6, 0.5, "analysis.alpha")
    if analysis["multiplicity"] not in ("holm-primary-v1", "none-exploratory-v1"):
        raise StudyError("unsupported multiplicity policy")
    methods = analysis["confirmatory_methods"]
    if type(methods) is not list or len(set(methods)) != len(methods) or any(m not in METHODS for m in methods):
        raise StudyError("analysis.confirmatory_methods must be unique supported methods")
    if any(row["primary"] and row["method"] not in methods for row in contrasts):
        raise StudyError("primary contrast method absent from confirmatory method declaration")
    if document["mode"] == "confirmatory" and analysis["multiplicity"] != "holm-primary-v1":
        raise StudyError("confirmatory study requires Holm primary multiplicity policy")

    privacy = document["privacy"]
    _exact(privacy, {"participant_id_policy", "notes"}, "privacy")
    if privacy["participant_id_policy"] != "pseudonymous-study-local-v1":
        raise StudyError("unsupported participant identity policy")
    _text(privacy["notes"], "privacy.notes", 1024)
    return deepcopy(document)


@dataclass(frozen=True, init=False)
class StudyManifest:
    _json: str

    def __init__(self, document):
        valid = validate_manifest(document)
        object.__setattr__(
            self,
            "_json",
            json.dumps(valid, sort_keys=True, separators=(",", ":"), allow_nan=False),
        )

    def to_dict(self):
        return loads(self._json)

    @property
    def sha256(self):
        return digest({"domain": "zaaggenz-study-manifest-v1", "manifest": self.to_dict()})

    @classmethod
    def from_json(cls, text):
        return cls(loads(text))


@dataclass(frozen=True, init=False)
class FrozenStudy:
    _json: str

    def __init__(self, document):
        _strict_json(document, "frozen study")
        _exact(
            document,
            {"format", "version", "manifest", "manifest_sha256", "freeze_id"},
            "frozen study",
        )
        if document["format"] != "zaaggenz-study-freeze" or document["version"] != VERSION:
            raise StudyError("unsupported frozen study format/version")
        manifest = StudyManifest(document["manifest"])
        if document["manifest_sha256"] != manifest.sha256:
            raise StudyError("frozen manifest hash mismatch")
        expected = digest(
            {
                "domain": "zaaggenz-study-freeze-v1",
                "manifest_sha256": manifest.sha256,
            }
        )
        if document["freeze_id"] != expected:
            raise StudyError("study freeze identity mismatch")
        object.__setattr__(
            self,
            "_json",
            json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False),
        )

    def to_dict(self):
        return loads(self._json)

    @property
    def manifest(self):
        return StudyManifest(self.to_dict()["manifest"])

    @property
    def sha256(self):
        return self.to_dict()["freeze_id"]


@dataclass(frozen=True, init=False)
class StudyAmendment:
    _json: str

    def __init__(self, document):
        _strict_json(document, "study amendment")
        _exact(
            document,
            {
                "format",
                "version",
                "freeze_id",
                "from_manifest_sha256",
                "to_manifest_sha256",
                "phase",
                "reason",
                "changed_paths",
                "id",
            },
            "study amendment",
        )
        if document["format"] != "zaaggenz-study-amendment" or document["version"] != VERSION:
            raise StudyError("unsupported study amendment format/version")
        for key in ("freeze_id", "from_manifest_sha256", "to_manifest_sha256", "id"):
            _sha(document[key], f"amendment.{key}")
        if document["from_manifest_sha256"] == document["to_manifest_sha256"]:
            raise StudyError("amendment must change the manifest")
        if document["phase"] not in ("prospective-before-outcome", "after-outcome-access"):
            raise StudyError("unsupported amendment phase")
        _text(document["reason"], "amendment.reason", 2048)
        paths = document["changed_paths"]
        if type(paths) is not list or not paths or len(paths) > 256 or any(type(p) is not str or not p.startswith("/") or len(p) > 512 for p in paths):
            raise StudyError("amendment.changed_paths must be bounded JSON-pointer paths")
        payload = {k: deepcopy(v) for k, v in document.items() if k != "id"}
        if document["id"] != digest({"domain": "zaaggenz-study-amendment-v1", "amendment": payload}):
            raise StudyError("amendment identity mismatch")
        object.__setattr__(
            self,
            "_json",
            json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False),
        )

    def to_dict(self):
        return loads(self._json)

    @property
    def sha256(self):
        return self.to_dict()["id"]


@dataclass(frozen=True, init=False)
class StudyDeviation:
    _json: str

    def __init__(self, document):
        _strict_json(document, "study deviation")
        _exact(
            document,
            {"format", "version", "freeze_id", "category", "phase", "impact", "reason", "id"},
            "study deviation",
        )
        if document["format"] != "zaaggenz-study-deviation" or document["version"] != VERSION:
            raise StudyError("unsupported study deviation format/version")
        _sha(document["freeze_id"], "deviation.freeze_id")
        if document["category"] not in ("protocol", "stimulus", "analysis", "missingness", "technical"):
            raise StudyError("unsupported deviation category")
        if document["phase"] not in ("before-outcome-access", "after-outcome-access"):
            raise StudyError("unsupported deviation phase")
        if document["impact"] not in ("none", "exploratory-only", "confirmatory-invalidated"):
            raise StudyError("unsupported deviation impact")
        _text(document["reason"], "deviation.reason", 2048)
        payload = {k: deepcopy(v) for k, v in document.items() if k != "id"}
        if document["id"] != digest({"domain": "zaaggenz-study-deviation-v1", "deviation": payload}):
            raise StudyError("deviation identity mismatch")
        object.__setattr__(
            self,
            "_json",
            json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False),
        )

    def to_dict(self):
        return loads(self._json)

    @property
    def sha256(self):
        return self.to_dict()["id"]


def freeze_manifest(manifest):
    if not isinstance(manifest, StudyManifest):
        raise StudyError("StudyManifest required")
    document = {
        "format": "zaaggenz-study-freeze",
        "version": VERSION,
        "manifest": manifest.to_dict(),
        "manifest_sha256": manifest.sha256,
        "freeze_id": digest(
            {
                "domain": "zaaggenz-study-freeze-v1",
                "manifest_sha256": manifest.sha256,
            }
        ),
    }
    return FrozenStudy(document)


def verify_frozen_manifest(frozen, candidate):
    if not isinstance(frozen, FrozenStudy) or not isinstance(candidate, StudyManifest):
        raise StudyError("FrozenStudy and StudyManifest required")
    expected = frozen.to_dict()["manifest_sha256"]
    if candidate.sha256 != expected:
        raise StudyError("candidate manifest differs from frozen preregistration; explicit amendment required")
    return True


def _pointer_escape(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def changed_paths(before, after, path=""):
    if type(before) is not type(after):
        return [path or "/"]
    if isinstance(before, dict):
        out = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}/{_pointer_escape(key)}"
            if key not in before or key not in after:
                out.append(child)
            else:
                out.extend(changed_paths(before[key], after[key], child))
        return out
    if isinstance(before, list):
        if len(before) != len(after):
            return [path or "/"]
        out = []
        for index, (left, right) in enumerate(zip(before, after)):
            out.extend(changed_paths(left, right, f"{path}/{index}"))
        return out
    return [] if before == after else [path or "/"]


def make_amendment(frozen, from_manifest, to_manifest, *, phase, reason):
    if not isinstance(frozen, FrozenStudy):
        raise StudyError("FrozenStudy required")
    if not isinstance(from_manifest, StudyManifest) or not isinstance(to_manifest, StudyManifest):
        raise StudyError("StudyManifest values required")
    paths = changed_paths(from_manifest.to_dict(), to_manifest.to_dict())
    if not paths:
        raise StudyError("amendment must change the manifest")
    document = {
        "format": "zaaggenz-study-amendment",
        "version": VERSION,
        "freeze_id": frozen.sha256,
        "from_manifest_sha256": from_manifest.sha256,
        "to_manifest_sha256": to_manifest.sha256,
        "phase": phase,
        "reason": _text(reason, "amendment.reason", 2048),
        "changed_paths": paths,
    }
    document["id"] = digest({"domain": "zaaggenz-study-amendment-v1", "amendment": document})
    return StudyAmendment(document)


def verify_amendment_chain(frozen, amendments, current_manifest):
    if not isinstance(frozen, FrozenStudy) or not isinstance(current_manifest, StudyManifest):
        raise StudyError("FrozenStudy and current StudyManifest required")
    expected = frozen.to_dict()["manifest_sha256"]
    for amendment in amendments:
        if not isinstance(amendment, StudyAmendment):
            raise StudyError("StudyAmendment required")
        row = amendment.to_dict()
        if row["freeze_id"] != frozen.sha256 or row["from_manifest_sha256"] != expected:
            raise StudyError("broken study amendment lineage")
        expected = row["to_manifest_sha256"]
    if current_manifest.sha256 != expected:
        raise StudyError("current manifest is not authorised by freeze/amendment chain")
    return True


def make_deviation(frozen, *, category, phase, impact, reason):
    if not isinstance(frozen, FrozenStudy):
        raise StudyError("FrozenStudy required")
    document = {
        "format": "zaaggenz-study-deviation",
        "version": VERSION,
        "freeze_id": frozen.sha256,
        "category": category,
        "phase": phase,
        "impact": impact,
        "reason": _text(reason, "deviation.reason", 2048),
    }
    document["id"] = digest({"domain": "zaaggenz-study-deviation-v1", "deviation": document})
    return StudyDeviation(document)
