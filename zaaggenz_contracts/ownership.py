"""Authoritative layer/stem ownership policy for ZG-029 integration.

This is a narrow, versioned adapter around frozen ZG-002 RenderRecipe/PhrasePlan v1
contracts. It does not add an audible layer or change a frozen wire schema.
"""
from __future__ import annotations

from copy import deepcopy
import re

from .model import check_json, digest
from .validation import validate

POLICY_ID = "zaaggenz.layer-ownership"
POLICY_VERSION = "1.0.0"
CANONICAL_LAYER_ROLES = ("synthline", "exciter", "body", "aux", "sub")
_TRANSFORM_QUANTITIES = frozenset(("retune", "reweight"))
_PHASE_POLICIES = frozenset(("legacy-v1.2.1", "continuous-integrated", "reset-event", "source-derived"))
_BASS_ROLES = frozenset(("none", "pedal", "moving"))
_PERSISTENT_ROLES = frozenset(("body", "aux", "sub"))
_INSPECTION_STATES = frozenset(("requested", "applied", "abstained"))
_OWNER = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")

# Fields here describe authority, not implementation availability. Persistent
# BODY/AUX/SUB execution remains a ZG-029 concern; this policy prevents later
# integration from inventing ownership at whichever call path happens to win.
_BASE = {
    "synthline": {
        "stem": "synthline",
        "musical_role": "lead/source",
        "source_identity_owner": "protected-source",
        "source_policy": "source-derived-unless-explicit-target-note",
        "pitch_owner": "phrase-event",
        "adaptive_tuning": "explicit-exclusive-owner",
        "phase_owner": "render-recipe",
        "reset_scope": "declared-note-mode",
        "tail_owner": "render-recipe",
        "state_lifetime": "note-or-source-event",
        "gain_owner": "event-gesture-then-final-master",
        "nonlinear_owner": "synthline-pre-master-graph",
        "pocket_policy": "explicit-only-no-makeup",
        "audition_policy": "independent-pre-master-stem",
        "mute_scope": "role-stem-only",
        "transform_bypass": "identity-no-retune-or-reweight",
        "persistent": False,
    },
    "exciter": {
        "stem": "exciter",
        "musical_role": "exciter",
        "source_identity_owner": "synthline-event",
        "source_policy": "derived-transient-never-synthline-substitute",
        "pitch_owner": "synthline-event",
        "adaptive_tuning": "inherits-synthline-target",
        "phase_owner": "synthline-event",
        "reset_scope": "each-exciter-trigger",
        "tail_owner": "exciter-generator",
        "state_lifetime": "exciter-trigger",
        "gain_owner": "exciter-generator-then-final-master",
        "nonlinear_owner": "none-unless-explicit-stage",
        "pocket_policy": "explicit-only-no-makeup",
        "audition_policy": "independent-pre-master-stem",
        "mute_scope": "role-stem-only",
        "transform_bypass": "identity-no-retune-or-reweight",
        "persistent": False,
    },
    "body": {
        "stem": "body",
        "musical_role": "upper-sonority",
        "source_identity_owner": "layer-generator",
        "source_policy": "persistent-layer-not-source-replacement",
        "pitch_owner": "harmony-layer",
        "adaptive_tuning": "explicit-exclusive-owner",
        "phase_owner": "body-layer-state",
        "reset_scope": "explicit-section-policy",
        "tail_owner": "body-layer-state",
        "state_lifetime": "persistent-until-explicit-section-reset",
        "gain_owner": "body-layer-automation-then-final-master",
        "nonlinear_owner": "body-layer-explicit-stage",
        "pocket_policy": "explicit-only-no-makeup",
        "audition_policy": "independent-pre-master-stem",
        "mute_scope": "role-stem-only",
        "transform_bypass": "identity-no-retune-or-reweight",
        "persistent": True,
    },
    "aux": {
        "stem": "aux",
        "musical_role": "complementary-group",
        "source_identity_owner": "layer-generator",
        "source_policy": "persistent-layer-not-source-replacement",
        "pitch_owner": "harmony-layer",
        "adaptive_tuning": "explicit-exclusive-owner",
        "phase_owner": "aux-layer-state",
        "reset_scope": "explicit-section-policy",
        "tail_owner": "aux-layer-state",
        "state_lifetime": "persistent-until-explicit-section-reset",
        "gain_owner": "aux-layer-automation-then-final-master",
        "nonlinear_owner": "aux-layer-explicit-stage",
        "pocket_policy": "explicit-only-no-makeup",
        "audition_policy": "independent-pre-master-stem",
        "mute_scope": "role-stem-only",
        "transform_bypass": "identity-no-retune-or-reweight",
        "persistent": True,
    },
    "sub": {
        "stem": "sub",
        "musical_role": "pedal-or-moving-root",
        "source_identity_owner": "layer-generator",
        "source_policy": "persistent-foundation",
        "pitch_owner": "phrase-bass-role",
        "adaptive_tuning": "locked-from-upper-unless-explicitly-owned",
        "phase_owner": "sub-layer-state",
        "reset_scope": "explicit-section-policy",
        "tail_owner": "sub-layer-state",
        "state_lifetime": "persistent-until-explicit-section-reset",
        "gain_owner": "sub-layer-automation-then-final-master",
        "nonlinear_owner": "sub-layer-explicit-stage",
        "pocket_policy": "explicit-only-no-makeup",
        "audition_policy": "independent-pre-master-stem",
        "mute_scope": "role-stem-only",
        "transform_bypass": "identity-no-retune-or-reweight",
        "persistent": True,
    },
}


class OwnershipConflict(ValueError):
    def __init__(self, diagnostic):
        self.diagnostic = deepcopy(diagnostic)
        super().__init__(self.diagnostic.get("message", "layer ownership conflict"))


def _conflict(code, message, **details):
    raise OwnershipConflict({
        "kind": "LayerOwnershipDiagnostic",
        "version": POLICY_VERSION,
        "policy_id": POLICY_ID,
        "code": code,
        "message": message,
        **deepcopy(details),
    })


def _strict_json(value, *, field):
    try:
        check_json(value)
    except Exception as exc:
        _conflict("invalid-inspection-target", f"{field} must be bounded strict JSON", field=field, error=str(exc))
    return deepcopy(value)


def role_policy(role, *, phase_policy="source-derived", bass_role="none"):
    """Resolve one canonical role without mutating or inventing render state."""
    if role not in _BASE:
        _conflict("unknown-layer-role", f"unknown layer role: {role!r}", layer=role)
    if phase_policy not in _PHASE_POLICIES:
        _conflict("unknown-phase-policy", f"unknown phase policy: {phase_policy!r}", layer=role)
    if bass_role not in _BASS_ROLES:
        _conflict("unknown-bass-role", f"unknown bass role: {bass_role!r}", layer=role)

    out = deepcopy(_BASE[role])
    out["role"] = role
    if role in ("synthline", "exciter"):
        out["phase_policy"] = phase_policy
    else:
        # Persistent layers need their own explicit state in ZG-029. Continuous
        # integration is the required persistent-state policy; an explicit
        # section reset is a state transition, not a silent alternate default.
        out["phase_policy"] = "continuous-integrated"

    if role == "sub":
        out["pitch_mode"] = {
            "none": "inactive",
            "pedal": "fixed-pedal",
            "moving": "follow-declared-root",
        }[bass_role]
    else:
        out["pitch_mode"] = "event-or-layer-target"
    return out


def resolve_transform_claims(claims=()):
    """Return a serializable ordered transform plan or fail on ambiguous ownership.

    A retune/reweight quantity has exactly one owner unless *every* competing
    claim carries a distinct non-negative integer ``order``. This deliberately
    provides no implicit precedence rule.
    """
    if claims is None:
        claims = ()
    if not isinstance(claims, (list, tuple)):
        _conflict("invalid-transform-claims", "transform claims must be a list/tuple")

    grouped = {}
    for raw in claims:
        if not isinstance(raw, dict):
            _conflict("invalid-transform-claim", "transform claim must be an object")
        claim = deepcopy(raw)
        role = claim.get("layer")
        quantity = claim.get("quantity")
        owner = claim.get("owner")
        order = claim.get("order", None)
        if role not in _BASE:
            _conflict("unknown-layer-role", f"unknown transform layer: {role!r}", layer=role)
        if quantity not in _TRANSFORM_QUANTITIES:
            _conflict("unknown-transform-quantity", f"unknown transform quantity: {quantity!r}",
                      layer=role, quantity=quantity)
        if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
            _conflict("invalid-transform-owner", "transform owner must be a canonical id",
                      layer=role, quantity=quantity, owner=owner)
        if order is not None and (type(order) is not int or order < 0):
            _conflict("invalid-transform-order", "transform order must be a non-negative integer or null",
                      layer=role, quantity=quantity, owner=owner, order=order)
        grouped.setdefault((role, quantity), []).append(
            {"layer": role, "quantity": quantity, "owner": owner, "order": order}
        )

    plan = []
    for key in sorted(grouped):
        rows = grouped[key]
        if len(rows) == 1:
            row = rows[0]
            plan.append({**row, "mode": "exclusive-owner"})
            continue
        orders = [row["order"] for row in rows]
        if any(order is None for order in orders) or len(set(orders)) != len(orders):
            _conflict(
                "competing-transform-owners",
                f"competing {key[1]} owners for {key[0]} require a complete, unique explicit order",
                layer=key[0], quantity=key[1], claims=rows,
            )
        for row in sorted(rows, key=lambda item: item["order"]):
            plan.append({**row, "mode": "ordered-chain"})
    return plan


def transform_inspection(*, layer, quantity, owner, stage, requested_target,
                         realised_target=None, state="requested", reason=None):
    """Create UI/provenance-ready evidence for a transform request or abstention.

    The ownership policy does not choose a target. It records who requested it,
    the stage that owns it, and what was actually realised (or why it abstained).
    """
    if layer not in _BASE:
        _conflict("unknown-layer-role", f"unknown inspection layer: {layer!r}", layer=layer)
    if quantity not in _TRANSFORM_QUANTITIES:
        _conflict("unknown-transform-quantity", f"unknown inspection quantity: {quantity!r}",
                  layer=layer, quantity=quantity)
    if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
        _conflict("invalid-transform-owner", "inspection owner must be a canonical id", owner=owner)
    if not isinstance(stage, str) or not _OWNER.fullmatch(stage):
        _conflict("invalid-transform-stage", "inspection stage must be a canonical id", stage=stage)
    if state not in _INSPECTION_STATES:
        _conflict("invalid-inspection-state", f"unknown inspection state: {state!r}", state=state)
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        _conflict("invalid-inspection-reason", "inspection reason must be a non-empty string or null")
    requested = _strict_json(requested_target, field="requested_target")
    realised = None if realised_target is None else _strict_json(realised_target, field="realised_target")
    if state == "applied" and realised_target is None:
        _conflict("missing-realised-target", "applied inspection requires realised_target",
                  layer=layer, quantity=quantity, owner=owner, stage=stage)
    if state == "abstained" and reason is None:
        _conflict("missing-abstention-reason", "abstained inspection requires a reason",
                  layer=layer, quantity=quantity, owner=owner, stage=stage)
    if state != "applied" and realised_target is not None:
        _conflict("unexpected-realised-target", "only applied inspection may carry realised_target",
                  layer=layer, quantity=quantity, owner=owner, stage=stage, state=state)
    out = {
        "kind": "LayerTransformInspection",
        "version": POLICY_VERSION,
        "policy_id": POLICY_ID,
        "layer": layer,
        "quantity": quantity,
        "owner": owner,
        "stage": stage,
        "state": state,
        "requested_target": requested,
        "realised_target": realised,
        "reason": reason,
    }
    out["sha256"] = digest(out)
    return out


def ownership_manifest(phrase, *, phase_policy="source-derived", transform_claims=()):
    """Create the deterministic versioned ownership section for a PhrasePlan.

    ``phrase`` may be a Contract or a plain PhrasePlan dictionary. The manifest
    is deliberately external to the frozen RenderRecipe v1 shape; its digest can
    be bound by ZG-029 without changing existing recipe/audio identity.
    """
    data = phrase.to_dict() if hasattr(phrase, "to_dict") else deepcopy(phrase)
    if not isinstance(data, dict) or data.get("kind") != "PhrasePlan":
        _conflict("invalid-phrase", "PhrasePlan ownership requires a PhrasePlan object")
    bass_role = data.get("bass_role")
    if bass_role not in _BASS_ROLES:
        _conflict("unknown-bass-role", f"unknown bass role: {bass_role!r}")

    events = data.get("events", [])
    if not isinstance(events, list):
        _conflict("invalid-phrase", "PhrasePlan events must be a list")
    authored_set = {event.get("layer_role") if isinstance(event, dict) else None for event in events}
    for role in authored_set:
        if role not in _BASE:
            _conflict("unknown-layer-role", f"unknown authored layer role: {role!r}", layer=role)
    try:
        validate(data, "PhrasePlan")
    except Exception as exc:
        _conflict("invalid-phrase", "PhrasePlan ownership requires a semantically valid PhrasePlan",
                  error=str(exc))
    authored = sorted(authored_set)

    roles = [role_policy(role, phase_policy=phase_policy, bass_role=bass_role)
             for role in CANONICAL_LAYER_ROLES]
    manifest = {
        "kind": "LayerOwnershipManifest",
        "version": POLICY_VERSION,
        "policy_id": POLICY_ID,
        "phrase_sha256": digest(data),
        "authored_roles": authored,
        "bass_role": bass_role,
        "roles": roles,
        "transform_plan": resolve_transform_claims(transform_claims),
        "master": {
            "owner": "render-recipe.output",
            "position": "single-final-stage",
            "normalization": "none",
            "subtractive_makeup": "prohibited-unless-explicit-stage",
        },
        "legacy_projection": {
            "click": "exciter",
            "body": "body",
            "sub": "sub",
            "synthline": "synthline",
            "aux": "aux",
        },
        "body_subcomponents": {
            "low": "body",
            "upper": "body",
            "independently_addressable_in_renderrecipe_v1": False,
        },
    }
    manifest["sha256"] = digest(manifest)
    return manifest


def section_transition_manifest(ownership, *, boundary_id, reset_roles=()):
    """Serialize one explicit section-boundary continue/reset decision.

    This records policy state for save/reload and later persistent-layer runtime.
    It does not fabricate oscillator state or make a persistent layer audible.
    """
    if not isinstance(ownership, dict) or ownership.get("kind") != "LayerOwnershipManifest":
        _conflict("invalid-ownership-manifest", "section transition requires a LayerOwnershipManifest")
    if ownership.get("policy_id") != POLICY_ID or ownership.get("version") != POLICY_VERSION:
        _conflict("invalid-ownership-manifest", "section transition policy/version mismatch")
    supplied_sha = ownership.get("sha256")
    payload = {k: deepcopy(v) for k, v in ownership.items() if k != "sha256"}
    if not isinstance(supplied_sha, str) or supplied_sha != digest(payload):
        _conflict("invalid-ownership-manifest", "section transition ownership digest mismatch")
    if not isinstance(boundary_id, str) or not _OWNER.fullmatch(boundary_id):
        _conflict("invalid-section-boundary", "section boundary id must be a canonical id", boundary_id=boundary_id)
    if not isinstance(reset_roles, (list, tuple, set, frozenset)):
        _conflict("invalid-section-reset-set", "reset_roles must be a role collection")
    reset = list(reset_roles)
    if len(reset) != len(set(reset)):
        _conflict("duplicate-section-reset-role", "reset_roles may not contain duplicates", reset_roles=reset)
    for role in reset:
        if role not in _BASE:
            _conflict("unknown-layer-role", f"unknown section-reset layer: {role!r}", layer=role)
        if role not in _PERSISTENT_ROLES:
            _conflict("nonpersistent-section-reset", f"{role} reset is owned by its event policy, not persistent section state",
                      layer=role, boundary_id=boundary_id)

    rows = []
    for role in CANONICAL_LAYER_ROLES:
        if role in _PERSISTENT_ROLES:
            is_reset = role in reset
            rows.append({
                "role": role,
                "action": "reset" if is_reset else "continue",
                "phase_state": "reset-to-declared-origin" if is_reset else "continue-integrated-state",
                "tail_state": "reset-with-layer" if is_reset else "preserve",
            })
        else:
            rows.append({
                "role": role,
                "action": "event-owned",
                "phase_state": "unchanged-by-section-policy",
                "tail_state": "event-owned",
            })
    out = {
        "kind": "LayerSectionTransition",
        "version": POLICY_VERSION,
        "policy_id": POLICY_ID,
        "ownership_sha256": supplied_sha,
        "boundary_id": boundary_id,
        "reset_roles": sorted(reset),
        "roles": rows,
    }
    out["sha256"] = digest(out)
    return out


def validate_section_transition(document, *, ownership=None):
    """Validate a saved section transition and optionally bind it to ownership."""
    try:
        check_json(document)
    except Exception as exc:
        _conflict("invalid-section-transition", "section transition must be bounded strict JSON", error=str(exc))
    if not isinstance(document, dict) or document.get("kind") != "LayerSectionTransition":
        _conflict("invalid-section-transition", "expected LayerSectionTransition document")
    supplied = document.get("sha256")
    payload = {k: deepcopy(v) for k, v in document.items() if k != "sha256"}
    if not isinstance(supplied, str) or supplied != digest(payload):
        _conflict("invalid-section-transition", "section transition digest mismatch")
    if document.get("policy_id") != POLICY_ID or document.get("version") != POLICY_VERSION:
        _conflict("invalid-section-transition", "section transition policy/version mismatch")
    if ownership is not None:
        expected = section_transition_manifest(
            ownership,
            boundary_id=document.get("boundary_id"),
            reset_roles=document.get("reset_roles", ()),
        )
        if document != expected:
            _conflict("invalid-section-transition", "section transition fields disagree with authoritative policy")
    return deepcopy(document)


def require_renderer_roles(phrase, allowed_roles, *, owner, phase_policy="source-derived"):
    """Fail closed if a renderer is asked to consume a role it does not own."""
    if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
        _conflict("invalid-renderer-owner", "renderer owner must be a canonical id", owner=owner)
    allowed = frozenset(allowed_roles)
    if not allowed or not allowed <= frozenset(CANONICAL_LAYER_ROLES):
        _conflict("invalid-renderer-role-set", "renderer role set contains an unknown role",
                  owner=owner, allowed=sorted(allowed))
    manifest = ownership_manifest(phrase, phase_policy=phase_policy)
    rejected = sorted(set(manifest["authored_roles"]) - allowed)
    if rejected:
        _conflict(
            "role-not-owned-by-renderer",
            f"{owner} does not own authored layer role(s): {', '.join(rejected)}",
            owner=owner, rejected_roles=rejected, allowed_roles=sorted(allowed),
        )
    return manifest
