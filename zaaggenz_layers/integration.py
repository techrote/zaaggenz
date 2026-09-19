from __future__ import annotations

from copy import deepcopy
import hashlib

import numpy as np

from zaaggenz_contracts import Contract, validate
from zaaggenz_dsp.graph import GraphError, apply_output_policy

from .pockets import LayerPocketPlan, apply_layer_pockets
from .runtime import CoordinatedRenderResult, LayerRuntimeError, render_coordinated_layers


def _sha_audio(array):
    return hashlib.sha256(np.asarray(array, dtype="<f4").tobytes()).hexdigest()


def render_coordinated_pockets(base_recipe, progression, frame_beats, duration_beats, runtime_spec,
                               pocket_plan, *, state=None, section_transition=None, muted_roles=()):
    """Render ZG-029 layers, apply ZG-030 subtractive pockets, then execute one final master.

    The accepted ZG-029 runtime remains the authoritative source/persistent-layer renderer. Its
    provisional mastered mix is discarded whenever a pocket changes a persistent stem. Pocket
    deltas are applied only to independently additive BODY/AUX/SUB pre-master role stems; the
    processed source_bus and raw SYNTHLINE/exciter audition evidence are never decomposed or
    rewritten. The declared RenderRecipe output policy then executes exactly once for the returned
    modified mix. Empty and computed-zero pocket plans return accepted ZG-029 audio bit-for-bit unchanged.
    """
    if not isinstance(pocket_plan, LayerPocketPlan):
        raise TypeError("pocket_plan must be LayerPocketPlan")
    base = render_coordinated_layers(
        base_recipe, progression, frame_beats, duration_beats, runtime_spec,
        state=state, section_transition=section_transition, muted_roles=muted_roles,
    )
    contract = base_recipe if isinstance(base_recipe, Contract) else Contract(base_recipe)
    recipe = contract.to_dict()
    validate(recipe, "RenderRecipe")
    sample_rate_hz = recipe["time_map"]["sample_rate_hz"]
    pocket_inputs = {name: base.stems[name] for name in ("synthline", "exciter", "body", "aux", "sub")}
    processed, pocket_diagnostics = apply_layer_pockets(
        pocket_inputs, sample_rate_hz, pocket_plan, muted_roles=muted_roles,
    )

    diagnostics = deepcopy(base.diagnostics)
    diagnostics["pockets"] = deepcopy(pocket_diagnostics)
    diagnostics["pocket_plan_sha256"] = pocket_plan.sha256

    muted = frozenset(muted_roles)
    changed_roles = [
        role for role in ("body", "aux", "sub")
        if role not in muted and not np.array_equal(
            np.asarray(processed[role]), np.asarray(pocket_inputs[role])
        )
    ]
    if not changed_roles:
        diagnostics["pocket_master_path"] = "effect-identity bypass; accepted ZG-029 mix retained bit-for-bit"
        diagnostics["pocket_changed_roles"] = []
        return CoordinatedRenderResult(base.mix.copy(), deepcopy(base.stems), base.state, diagnostics)

    pre_master = np.asarray(base.stems["pre_master"], dtype=np.float64).copy()
    for role in changed_roles:
        before = np.asarray(base.stems[role], dtype=np.float64)
        after = np.asarray(processed[role], dtype=np.float64)
        pre_master += after - before

    try:
        mix, master_diagnostics = apply_output_policy(pre_master, recipe["output"])
    except GraphError as exc:
        raise LayerRuntimeError({
            "kind": "LayerRuntimeDiagnostic",
            "version": diagnostics.get("version", "1.0.0"),
            "runtime_id": diagnostics.get("runtime_id", "zaaggenz.layer-runtime"),
            "code": "final-master-failed",
            "message": "declared final output policy could not execute after ZG-030 pockets",
            "error": str(exc),
        }) from exc

    stems = deepcopy(base.stems)
    for role in changed_roles:
        stems[role] = np.asarray(processed[role], dtype=np.float32)
    stems["pre_master"] = np.asarray(pre_master, dtype=np.float32)
    mix = np.asarray(mix, dtype=np.float32)

    diagnostics["master"] = deepcopy(master_diagnostics)
    diagnostics["stem_sha256"] = {name: _sha_audio(audio) for name, audio in stems.items()}
    diagnostics["mix_sha256"] = _sha_audio(mix)
    diagnostics["pocket_changed_roles"] = changed_roles
    diagnostics["pocket_master_path"] = "ZG-029 source_bus + persistent pre-master role stems -> ZG-030 confined persistent-role deltas -> RenderRecipe.output once for returned modified mix"
    diagnostics["normalization"] = base.diagnostics.get("normalization", "none")
    diagnostics["final_master_owner"] = base.diagnostics.get("final_master_owner", "render-recipe.output")
    return CoordinatedRenderResult(mix, stems, base.state, diagnostics)
