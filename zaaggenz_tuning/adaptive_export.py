from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from .adaptive_engine import AdaptiveProposal
from .dissonance_model import DissonanceError


def _transition(proposal):
    return deepcopy(proposal.search.get("root_lock_transition", {}))


def candidate_tuning_set(proposal):
    if not isinstance(proposal, AdaptiveProposal):
        raise DissonanceError("AdaptiveProposal required")
    offsets = proposal.offset_mapping()
    transition = _transition(proposal)
    voices = []
    for voice in proposal.request.voices:
        offset = offsets.get(voice.id, 0.0)
        root_transition = bool(
            transition.get("active")
            and voice.id == proposal.request.root_voice_id
        )
        voices.append(
            {
                "id": voice.id,
                "role": voice.role,
                "nominal_cents": voice.nominal_cents,
                "offset_cents": offset,
                "adjusted_cents": voice.nominal_cents + offset,
                "locked": voice.locked
                or voice.role == "pedal"
                or (
                    proposal.request.root_lock
                    and voice.id == proposal.request.root_voice_id
                ),
                "lock_transition_active": root_transition,
            }
        )
    return {
        "kind": "AdaptiveCandidateTuningSet",
        "version": "1.0.0",
        "status": proposal.status,
        "voices": voices,
        "desired_tension": proposal.request.desired_tension,
        "predicted_tension": proposal.objective.get("predicted_tension"),
        "root_lock_transition": transition,
        "manual_review_required": True,
        "source_confidence": proposal.source_confidence,
        "interpretation": "candidate offsets only; requires explicit manual accept/reject",
    }


def ab_recipe(proposal):
    candidate = candidate_tuning_set(proposal)
    baseline = []
    previous = proposal.previous_state.mapping()
    for voice in proposal.request.voices:
        offset = float(previous.get(voice.id, 0.0))
        baseline.append(
            {
                "id": voice.id,
                "nominal_cents": voice.nominal_cents,
                "offset_cents": offset,
                "adjusted_cents": voice.nominal_cents + offset,
            }
        )
    payload = {
        "kind": "AdaptiveTuningABRecipe",
        "version": "1.0.0",
        "baseline": {"voices": baseline},
        "candidate": candidate,
        "request": proposal.request.to_dict(),
        "proposal_objective": proposal.objective,
        "root_lock_transition": _transition(proposal),
        "controls": {
            "same_timbres": True,
            "amplitudes_immutable": True,
            "manual_accept_reject": True,
        },
        "interpretation": "reproducible model A/B recipe; listening outcome is not predicted",
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    payload["recipe_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload
