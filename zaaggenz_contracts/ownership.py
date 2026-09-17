"""Authoritative layer/stem ownership policy for ZG-029 integration.

This is a narrow, versioned adapter around frozen ZG-002 RenderRecipe/PhrasePlan v1
contracts.  It does not add an audible layer or change a frozen wire schema.
"""
from __future__ import annotations

from copy import deepcopy
import re

from .model import digest

POLICY_ID = "zaaggenz.layer-ownership"
POLICY_VERSION = "1.0.0"
CANONICAL_LAYER_ROLES = ("synthline", "exciter", "body", "aux", "sub")
_TRANSFORM_QUANTITIES = frozenset(("retune", "reweight"))
_PHASE_POLICIES = frozenset(("legacy-v1.2.1", "continuous-integrated", "reset-event", "source-derived"))
_BASS_ROLES = frozenset(("none", "pedal", "moving"))
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
        "gain_owner": "event-gesture-then-final-master",
        "nonlinear_owner": "synthline-pre-master-graph",
        "pocket_policy": "explicit-only-no-makeup",
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
        "gain_owner": "exciter-generator-then-final-master",
        "nonlinear_owner": "none-unless-explicit-stage",
        "pocket_policy": "explicit-only-no-makeup",
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
        "gain_owner": "body-layer-automation-then-final-master",
        "nonlinear_owner": "body-layer-explicit-stage",
        "pocket_policy": "explicit-only-no-makeup",
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
        "gain_owner": "aux-layer-automation-then-final-master",
        "nonlinear_owner": "aux-layer-explicit-stage",
        "pocket_policy": "explicit-only-no-makeup",
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
        "gain_owner": "sub-layer-automation-then-final-master",
        "nonlinear_owner": "sub-layer-explicit-stage",
        "pocket_policy": "explicit-only-no-makeup",
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

    authored = sorted({event.get("layer_role") for event in data.get("events", [])})
    for role in authored:
        if role not in _BASE:
            _conflict("unknown-layer-role", f"unknown authored layer role: {role!r}", layer=role)

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
