# ZG-024d staged deterministic search — sealed result and decision

Status: **mixed/no-go; no production optimizer promotion**. This is the post-outcome completion record for issue #92. It does not amend the frozen protocol in `ZG024_STAGED_PROTOCOL_V2.md`.

## Design-freeze and disclosure boundary

The complete v2 design was frozen at commit `35e6f5ed6f905fa853d2eb58a683065b126c84b3` before the sealed confirmation catalogue was checked in. The confirmation module was disclosed later at commit `7a7a697a7238dd6b89aec842017063eff8ab7c34`. The earlier v1 draft is retained only as invalidated research history in `ZG024_STAGED_PROTOCOL_V1.md`; its outcomes are not used for selection.

The frozen v2 design digest is `fd3fd70f094987d62d2e5adfcaeb4c6e1a49249b4cd5ae68ec9bcff745b1ef62`. The research implementation is `ZG024dStagedResearchImplementation` version `2.0.0`, with strategy source SHA-256 `3ebc17c424fa41567f374aba6d2af442433b54229463e750100b511003c2ccd1` and accepted ZG-024b dependency SHA-256 `c71c430a250dbc417397836e4b7de5457aa80a6aa4324247fddab200d798cecd`.

## Frozen programme exercised

Three bounded staged allocations were compared under 24 unique logical candidate evaluations per normal case and seeds `41`, `211`, and `2027`: `zg024d.staged-balanced.v2`, `zg024d.staged-structure.v2`, and `zg024d.staged-texture.v2`. The flat comparators were the accepted `zg024b.uniform-splitmix.v1`, `zg024b.halton-shifted.v1`, and `zg024b.coordinate-refine.v1` methods at the same logical budget.

Stage A covers root/pitch/timing/envelope coordinates by shifted Halton coverage; Stage B covers harmonic/spectral coordinates around retained eligible parents; Stage C performs bounded local texture/nonlinearity refinement with the preregistered labelled Halton continuation only when duplicate/clipped coordinate probes would otherwise waste budget. Parent IDs, proposal method, consumed budget, eligible/Pareto promotion and exact-output equivalence groups are retained as evidence. Promotion and final ranking receive only fit capability; fixture truth and independent holdout capability remain outside the strategy API.

The development-only decision selected `zg024d.staged-structure.v2` for the untouched confirmation programme. Confirmation was not permitted to switch to a different staged variant.

## Sealed outcome

The frozen decision record is `mixed-or-no-go-no-production-promotion`:

- development: 4 staged cases beat/tied the best flat comparator, while 11 were worse by more than 10%; development support is false;
- sealed confirmation: 3 cases beat/tied the best flat comparator, while 6 were worse by more than 10%; confirmation support is false;
- exact logical-budget accounting is true, including explicit fail-closed early stops;
- promotion integrity is true: no ineligible candidate is promoted;
- sentinel integrity is true;
- holdout support is false;
- production candidacy is therefore false.

The selected staged method produced no eligible candidate for `confirm-structure-spectral` on any of the three frozen seeds. On `confirm-texture-mixed`, it beat/tied the best flat fit on one seed, had no eligible result on another, and was substantially worse on the third. On `confirm-equivalence`, it beat/tied the best flat fit on two seeds and had no eligible result on one.

Independent confirmation holdouts preserve the mixed result. `confirm-equivalence` improved relative to the best flat median (`0.2741540241` versus `0.5070454001`). `confirm-structure-spectral` has no selected eligible staged holdout result. `confirm-texture-mixed` regressed by about 17.37% (`0.9863051697` versus `0.8403197532`). Holdout evidence never fed proposal, promotion, ranking or stopping.

## Anti-degeneracy and fail-closed boundaries

The accepted safety policy remains unchanged. On the frozen sentinel seed, the selected staged method admits zero eligible candidates for all three deliberately unsafe families:

- transient sentinel: 10/24 evaluations consumed, then `stage-A-no-eligible-parent`; transient-loss rejection is present;
- silence sentinel: 10/24 consumed, then fail-closed; silence, energy, bandwidth, level and transient gates reject the candidates;
- clipping sentinel: 10/24 consumed, then fail-closed; destructive-output-clipping, hidden-level-handling, pathological-clipping and transient-loss gates reject the candidates.

Unspent budget after a stage has no eligible parent is explicit evidence; it is not silently reassigned and rejected candidates are never smuggled forward as adaptive parents.

## Determinism, replay, cache and portability

Adversarial tests cover method/design/request/environment divergence, exact verified-prefix replay, cancellation at completed-prefix boundaries, stage lineage, ineligible-parent exclusion, duplicate/logical-budget accounting, holdout/truth isolation, method-separated cache identity and fail-closed safety prefixes. ZG-024a and ZG-024b regressions remain in the same workflow.

Ubuntu and Windows run Python 3.13 with NumPy 2.3.5, SciPy 1.17.0, `PYTHONHASHSEED=0`, `OPENBLAS_NUM_THREADS=1` and `OMP_NUM_THREADS=1`. The CI portability job compares the complete portable projection recursively under the preregistered absolute `1e-7` / relative `1e-5` tolerance and passes. Environment-specific exact evidence identities remain distinct rather than being falsely collapsed.

At evidence head `17f48e7e082bca9c00df07c5bffd31bf67cf1af9`, the Ubuntu evidence SHA-256 was `1b51fb633e7d89e90e257cd70e7e0494593dd6ad315a2fe715884c5a294c31c8`; the Windows evidence SHA-256 was `b7e51ba856546073227fd7e322d77b1f42307faa36dd66f19cad7d8cde57fc82`. Their portable projections differ only within the declared numerical tolerance. GitHub Actions also passed ZG-024a, ZG-024b, ZG-002 and the ZG-000 reverse-dependency audit on that head.

## Decision and remaining ZG-024 blocker

No staged strategy is integrated into `zaaggenz_inverse`. The accepted flat methods remain the production/research baseline and no optimizer winner is claimed. Issue #92 can close on the explicitly permitted mixed/inconclusive path, but parent ZG-024 / #25 must remain open.

The evidence-based blocker for #25 is now narrower: the transparent three-stage factorization is mechanically trustworthy but does not provide sufficiently reliable **eligible candidate availability plus held-out improvement** across fresh structural/spectral and mixed-texture cases at the frozen budget. The next inverse-search work must explain or reduce that feasibility/generalization failure without using holdouts as feedback and without weakening transient/silence/clipping gates. A useful next experiment should isolate whether the loss comes from stage allocation, eligible-parent bottlenecks, or cross-family coupling/identifiability before considering a more opaque optimizer family.

## Protected semantics

This research pass changes no source PCM, renderer/DSP topology, tuning, objective weights, validation thresholds, normalization/clipping policy, private-reference handling, protected audio ownership, provenance ownership, `locked_bloom`, audible defaults, or fit/holdout capability boundary. No trained model or runtime service is introduced.