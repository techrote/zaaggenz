# ZG-029 corrective runtime evidence

Status: executable evidence map for corrective issue #202  
Parent authority: `zaaggenz.layer-ownership/1.1.0` / `ZG029_LAYER_OWNERSHIP_ADR.md`  
Runtime implementation: `zaaggenz.layer-runtime/1.0.0`  
Pocket implementation: ZG-030 `zaaggenz_layers.pockets`

## Why this document exists

Issue #91 established the ownership policy before the persistent-layer renderer existed. Its policy tests were valid, but they could not prove PCM, state-persistence, pocket/master, or section-transition behavior. Corrective #202 therefore stayed open until ZG-029/#30 and ZG-030/#31 supplied real execution paths.

Those dependencies now exist. This document records which executable tests prove each behavioral claim and deliberately does not treat ownership-policy strings as runtime evidence.

No frozen ZG-002 wire contract is widened by this corrective. No source bytes, recovered provenance, accepted recipe meaning, tuning equation, DSP topology/order, master policy, or artistic default is changed.

## Executable acceptance map

| #91 / #202 behavior | Executable evidence |
| --- | --- |
| Full SYNTHLINE is present independently of exciter | `tests/layers/test_runtime.py::test_source_synthline_and_exciter_are_not_resynthesized_by_harmony` plus `test_corrective_202.py::test_source_stems_are_independent_pcm_and_remain_hash_bound_through_pockets`; both compare real raw float PCM. Source-role mutes alter assembly but leave both retained raw audition/null stems byte-identical. |
| Raw source stems versus processed pre-master bus are unambiguous | `test_corrective_202.py::test_linear_topology_exposes_raw_audition_stems_and_exact_processed_source_bus` proves a non-identity linear graph: raw SYNTHLINE/exciter remain exact while `source_bus` equals the accepted ZG-008 post-topology source contribution and reconstructs `pre_master` with BODY/AUX/SUB. |
| Shared nonlinear topology is not falsely decomposed | `test_corrective_202.py::test_nonlinear_topology_mutes_before_shared_bus_and_is_not_additively_decomposed` uses real `core.tanh.v1`, proves source mute/solo occurs before the shared graph, proves raw source evidence is unchanged, and explicitly demonstrates that solo processed buses do not add to the full processed bus. |
| Source-derived material is not silently resynthesized | Coordinated raw SYNTHLINE/exciter PCM is compared directly with `render_phrase()`; the unmuted `source_bus` is the accepted ZG-008 `pre_master` source contribution. `recipe_sha256` and float32 little-endian stem/bus SHA-256 values remain bound through a real BODY pocket. |
| Fixed SUB remains fixed while upper harmony moves | `test_runtime.py::test_fixed_pedal_stays_fixed_while_upper_sonority_moves`. |
| Moving-root SUB follows only declared harmony | `test_runtime.py::test_moving_sub_follows_declared_harmony_and_is_rejected_under_pedal_contract`. |
| Upper-only retune does not drag SUB | `test_runtime.py::test_upper_retune_is_layer_scoped_and_cannot_drag_locked_sub` checks exact SUB PCM and state identity. |
| Continue/save/reload preserves phase/tail state | `test_runtime.py::test_save_reload_continue_is_bit_identical_and_explicit_reset_changes_phase`; the corrective pocketed continuation test repeats the save/JSON/reload/continue path through ZG-030 and checks complete stem, mix and state equality. |
| Explicit reset is different from continue | `test_runtime.py::test_save_reload_continue_is_bit_identical_and_explicit_reset_changes_phase`. |
| Undeclared continuation fails closed | `test_runtime.py::test_continuing_nonempty_state_without_transition_fails_closed`. |
| Adaptive + spectral ownership cannot silently last-write-win | `test_runtime.py::test_competing_transform_owners_fail_closed_and_explicit_order_is_recorded` and the corrective adversarial test reject unordered competing owners with `competing-transform-owners`; explicit order is retained in the executable voice trace. Runtime v1 coordinates already-computed retune targets as ordered cumulative offsets; it does not claim to execute the estimator algorithms themselves. |
| Subtractive pocket is not silently made up | `tests/layers/test_pockets.py::test_static_pocket_changes_only_declared_persistent_role_and_survives_master` and the corrective pocketed continuation test assert lower BODY energy, `makeup_gain_db == 0.0`, and `normalization == none`. |
| One final master owns returned output | Runtime and pocket integration tests reconstruct the returned mix from `pre_master` and the declared `RenderRecipe.output` gain, and require `final_master_owner == render-recipe.output`. The pocket path explicitly discards the provisional base master when a stem changes and executes `RenderRecipe.output` once on the modified pre-master. |
| Identity/bypass preserves gain | `test_pockets.py::test_empty_plan_is_bit_exact_runtime_identity` and `test_pocket_integration_identity.py::test_zero_max_sidechain_is_bit_exact_through_full_render`. |
| Non-octave tuning uses real execution | `test_runtime.py::test_non_octave_tuning_runs_through_real_source_and_persistent_stems` executes the accepted synthetic 13-ED3 fixture through the source renderer, harmony solver and persistent stems. |
| Infeasible role/input is diagnostic, never silently dropped | `test_runtime.py::test_missing_generator_and_unowned_transform_are_structured_diagnostics` plus the corrective adversarial test require `missing-persistent-generator` with exact missing roles. Additional runtime validation covers tuning mismatch, moving pedal SUB, ambiguous authored persistent events and state tamper. |

## Source and artifact identity boundary

The canonical evidence is float32 PCM plus content hashes, not a listening copy and not a metadata label. `render_coordinated_layers()` records `recipe_sha256`, `progression_sha256`, runtime-state identity, per-stem float32 SHA-256 and final-mix SHA-256. The ZG-029 owner-audition fixture report carries those identities into its deterministic evidence artifact.

The corrective tests additionally recompute SYNTHLINE and exciter hashes from actual arrays, require those hashes to remain identical after a real ZG-030 BODY pocket, and require `source_bus` to remain unchanged by persistent-role pocketing. Thus downstream layer coordination cannot claim source preservation merely because a field still says `synthline`.

The evidence domains are intentionally separate:

- `synthline` / `exciter`: raw source-owned audition/null PCM;
- `source_bus`: processed post-topology source contribution used in assembly;
- `body` / `aux` / `sub`: independently additive persistent pre-master role PCM;
- `pre_master`: assembled `source_bus` plus unmuted persistent roles.

Policy 1.0.0's old label `independent-pre-master-stem` for the raw source arrays is retired by policy 1.1.0. Historical 1.0.0 policy evidence is not rewritten; old section-transition policy documents must be regenerated from unchanged PhrasePlan/reset intent before binding to 1.1.0.

## Transform ordering scope

Ownership policy permits multiple owners of one layer/quantity only when every owner supplies a unique explicit order. Runtime v1 consumes already-authorised scalar retune/reweight targets. It records the ordered owner sequence and applies those target values deterministically; unordered competition fails before rendering.

This is intentionally narrower than claiming that ZG-017 spectral estimation or ZG-020 adaptive-tuning estimation is itself executed inside the layer runtime. Those systems remain separate target producers. The corrective evidence proves the ownership boundary and deterministic consumption path without inventing a new integration or audible default.

## Inherited regression gate

The ZG-029 workflow runs on both Ubuntu and Windows. For corrective #202 it includes:

- ZG-008 melody/source renderer regressions;
- ZG-010 harmony regressions;
- ZG-016/ZG-019/ZG-021 DSP regressions;
- ZG-017/ZG-018/ZG-019/ZG-021 spectral regressions;
- ZG-020 tuning/adaptive regressions;
- ZG-025 phrase regressions;
- ZG-027 gesture regressions;
- ownership contract regressions; and
- the complete `tests/layers` runtime/pocket/corrective suite.

The repository-wide reverse-dependency impact workflow remains authoritative for transitive CI selection. The corrective does not close merely because the focused tests pass: final-head automated checks must all succeed before merge.

## Protected semantics

This corrective changes ownership metadata and exposes the already-existing processed source contribution as an explicit runtime `source_bus`; it adds no sound-generating default and changes no DSP algorithm. The normal unmuted source path remains the accepted ZG-008 output. It does not alter:

- authenticated recovered source bytes or provenance;
- frozen ZG-002 contract versions;
- ZG-008 source-note derivation or accepted SYNTHLINE topology;
- ZG-010 harmony targets;
- ZG-016 effect-delta/filter identity;
- ZG-017–ZG-021 target-estimation semantics;
- ZG-025/ZG-027 source-preserving compilation;
- tuning equations, phase/tail rules, clipping or final-master policy;
- listening/inverse/reference evidence; or
- artistic preference/default decisions.

The corrective closes the original evidence gap only after the runtime paths introduced by #30 and #31 are exercised together on the final PR head and the cross-platform/inherited gates remain green.
