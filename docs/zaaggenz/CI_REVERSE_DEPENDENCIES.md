# Reverse-dependency CI coverage

Issue #96 closes a specific CI correctness gap: accepted feature workflows already run important upstream/shared regressions, but many `pull_request.paths` filters only name the feature's own files. A shared implementation change could therefore break a downstream accepted feature without starting that feature's workflow.

## Policy

The existing feature workflows remain authoritative for their exact tests, browser runs, evidence generation, platform matrix and artifacts. ZaagGenZ does **not** duplicate those commands in a second integration suite.

`.github/workflows/zg000-ci-impact.yml` performs a lightweight dependency-impact pass on pull requests that change implementation/shared-runtime paths. It:

1. validates the workflow/stable-ID and source-owner map in `programme/ci_reverse_dependencies.json`;
2. determines changed implementation ownership only from the explicit `source_path_owners` map;
3. resolves transitive hard prerequisites using `programme/dependency_graph.json`;
4. reads each workflow's existing pull-request trigger only to determine whether GitHub will already start that workflow natively;
5. dispatches **only missing downstream existing workflows** at the exact pull-request head and waits for their real result;
6. fails closed for an untrusted fork when required downstream dispatch cannot safely be granted.

Native trigger coverage and implementation ownership are intentionally separate. For example, ZG-024a's broad `zaaggenz_*/**` pull-request filter means that its accepted regression suite runs on many package changes; it does **not** mean ZG-024 owns every ZaagGenZ package.

A workflow with `pull_request:` and no `paths` is treated as **always native**. ZG-002 currently has this policy. It is never redundantly dispatched, while `zaaggenz_contracts/**` remains explicitly owned by ZG-002 so contract changes propagate to downstream consumers.

This preserves the existing evidence contract while avoiding the opposite failure mode of running every workflow for every edit.

## Audit inventory

The authoritative machine-readable inventory is `programme/ci_reverse_dependencies.json`. It accounts for every checked-in accepted feature workflow from ZG-001 through the implemented ZG-032 surface, including both serial ZG-024 workflows, and every checked-in `zaaggenz_*` package.

`tools/ci_reverse_dependencies.py --audit` emits the current table of:

- workflow file;
- stable `ZG-*` owner;
- whether the pull-request trigger is unfiltered or path-filtered;
- explicitly owned implementation paths;
- hard programme parents.

The validator fails when a new `zg*.yml` feature workflow appears without an owner mapping, a mapped workflow disappears, a mapped stable ID is unknown, `workflow_dispatch` is absent, a workflow owner has no implementation surface, or a checked-in `zaaggenz_*` package has no explicit source owner.

Six previously path-filtered workflows lacked a manual dispatch entrypoint: ZG-003, ZG-005, ZG-006, ZG-007, ZG-012 and ZG-016. #96 adds `workflow_dispatch` to those files without changing their jobs, PR filters, matrices, test commands, artifacts or evidence semantics. All accepted workflows in the current inventory can therefore be invoked by the dependency dispatcher after this repair lands.

## Required impact examples

The regression suite freezes the defect classes that motivated #96:

- a `zaaggenz_tuning/**` change reaches spectral and inspector consumers even when their own path filters omit tuning;
- a `zaaggenz_spectral/**` change reaches inspector and inverse consumers;
- a `zaaggenz_jobs/**` change reaches timeline, listening, inspector and inverse consumers;
- a `zaaggenz_contracts/**` change treats the unfiltered ZG-002 workflow as already native while still reaching deep downstream consumers;
- a broad consumer filter cannot claim implementation ownership merely because it mentions a package;
- a feature-local change still runs its owning workflow natively while only missing downstream consumers are dispatched;
- documentation-only changes do not invoke the global impact dispatcher;
- dependency-map / impact-map / validator / workflow-definition changes validate the selector itself without being misclassified as product-source changes.

## Cost and failure semantics

Direct feature workflows continue to use their existing trigger policy. The impact workflow dispatches only workflows that are both transitively affected **and** not already natively selected by the pull request. Parallel dispatch is capped at four workflows. Each dispatched workflow runs its original Windows/Ubuntu/browser/full-rate policy unchanged and its failure propagates back into the impact workflow.

Editing a workflow definition is **not** treated as changing that feature's product source: the ZG-000 impact workflow validates the mapping/selector, while the edited feature workflow follows its own existing self-trigger policy. This prevents CI metadata maintenance from fanning out through the product DAG.

Co-owned implementation packages are explicit. At current granularity:

- `zaaggenz_tuning/**` belongs to ZG-007 and ZG-020;
- `zaaggenz_dsp/**` belongs to ZG-016, ZG-019 and ZG-021;
- `zaaggenz_spectral/**` belongs to ZG-017, ZG-018, ZG-019 and ZG-021.

The map may be split into narrower file patterns later if profiling shows a worthwhile CI-cost reduction, but ownership may not be inferred from a consumer workflow's regression paths.

No product/audio behaviour, programme dependency edge, stable ID, test tolerance or evidence definition is changed by this CI layer.

## Maintenance

When adding or renaming an accepted `zg*.yml` workflow:

1. retain a `pull_request:` trigger and `workflow_dispatch:` entry;
2. add the workflow's stable-ID owner to `workflow_owners`;
3. add or verify its implementation ownership under `source_path_owners` independently of its regression trigger paths;
4. run `python tools/ci_reverse_dependencies.py --validate`;
5. run `python -m unittest discover -s tests/programme -p 'test_ci_reverse_dependencies.py' -v`;
6. inspect `python tools/ci_reverse_dependencies.py --audit` if dependencies or shared surfaces changed.

GitHub issue state does not define programme dependency satisfaction; this CI selector only consumes the existing stable-ID DAG.
