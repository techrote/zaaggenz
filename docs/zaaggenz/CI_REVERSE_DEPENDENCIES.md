# Reverse-dependency CI coverage

Issue #96 closes a specific CI correctness gap: accepted feature workflows already run important upstream/shared regressions, but many `pull_request.paths` filters only name the feature's own files. A shared implementation change could therefore break a downstream accepted feature without starting that feature's workflow.

## Policy

The existing feature workflows remain authoritative for their exact tests, browser runs, evidence generation, platform matrix and artifacts. ZaagGenZ does **not** duplicate those commands in a second integration suite.

`.github/workflows/zg000-ci-impact.yml` performs a lightweight dependency-impact pass on pull requests that change implementation/shared-runtime paths. It:

1. validates the workflow/stable-ID audit map in `programme/ci_reverse_dependencies.json`;
2. derives direct implementation ownership from existing path-filtered workflows plus explicit ownership entries for cross-cutting/unfiltered surfaces;
3. resolves transitive hard prerequisites using `programme/dependency_graph.json`;
4. distinguishes workflows that GitHub will already start natively from downstream consumers whose path filters would otherwise miss the change;
5. dispatches **only those missing existing workflows** at the exact pull-request head and waits for their real result;
6. fails closed for an untrusted fork when required downstream workflow dispatch cannot safely be granted.

A workflow with `pull_request:` and no `paths` is intentionally treated as **always native**. ZG-002 currently has this policy. Such workflows are never redundantly dispatched, but their implementation source still has an explicit owner in the audit map so its changes propagate to downstream consumers.

This preserves the existing evidence contract while avoiding the opposite failure mode of running every workflow for every edit.

## Audit inventory

The authoritative machine-readable workflow inventory is `programme/ci_reverse_dependencies.json`. It currently accounts for every checked-in accepted feature workflow from ZG-001 through the implemented ZG-032 surface, including both serial ZG-024 workflows. `tools/ci_reverse_dependencies.py --audit` emits the current table of:

- workflow file;
- stable `ZG-*` owner;
- whether the pull-request trigger is unfiltered or path-filtered;
- implementation ownership paths;
- hard programme parents.

The validator fails when a new `zg*.yml` feature workflow appears without an owner mapping, when a mapped workflow disappears, when a mapped stable ID is unknown, when `workflow_dispatch` is absent, when a path-filtered workflow exposes no implementation path, when an always-native workflow has no explicit source owner, or when a checked-in `zaaggenz_*` implementation package has no workflow/source owner.

## Required impact examples

The regression suite freezes the defect classes that motivated #96:

- a `zaaggenz_tuning/**` change reaches spectral and inspector consumers even when their own path filters omit tuning;
- a `zaaggenz_spectral/**` change reaches inspector and inverse consumers;
- a `zaaggenz_jobs/**` change reaches timeline, listening, inspector and inverse consumers;
- a `zaaggenz_contracts/**` change treats the unfiltered ZG-002 workflow as already native while still reaching deep downstream consumers;
- a feature-local change still runs its owning workflow natively while only missing downstream consumers are dispatched;
- documentation-only changes do not invoke the global impact dispatcher;
- dependency-map / impact-map / validator / workflow-definition changes validate the selector itself without being misclassified as product-source changes.

## Cost and failure semantics

Direct feature workflows continue to use their existing trigger policy. The impact workflow dispatches only workflows that are both transitively affected **and** not already natively selected by the pull request. Parallel dispatch is capped at four workflows. Each dispatched workflow runs its original Windows/Ubuntu/browser/full-rate policy unchanged and its failure propagates back into the impact workflow.

Editing a workflow definition is **not** treated as changing that feature's product source: the ZG-000 impact workflow validates the mapping/selector, while the edited feature workflow follows its own existing self-trigger policy. This prevents CI metadata maintenance from fanning out through the product DAG.

This mechanism is deliberately conservative for cross-cutting tracked inputs:

- `baseline/recovered_source/**` is owned by ZG-001;
- `zaaggenz_contracts/**` and `requirements-contracts.txt` are owned by ZG-002;
- `requirements-jobs.txt` and `web/jobs_transport.mjs` are owned by ZG-004.

No product/audio behaviour, programme dependency edge, stable ID, test tolerance or evidence definition is changed by this CI layer.

## Maintenance

When adding or renaming an accepted `zg*.yml` workflow:

1. retain a `pull_request:` trigger and `workflow_dispatch:` entry;
2. if it is path-filtered, keep a literal `pull_request.paths` list containing its implementation surface;
3. if it is intentionally unfiltered, give its implementation surface an explicit owner in `programme/ci_reverse_dependencies.json`;
4. add the workflow's stable-ID owner to `programme/ci_reverse_dependencies.json`;
5. run `python tools/ci_reverse_dependencies.py --validate`;
6. run `python -m unittest discover -s tests/programme -p 'test_ci_reverse_dependencies.py' -v`;
7. inspect `python tools/ci_reverse_dependencies.py --audit` if dependencies or shared surfaces changed.

GitHub issue state does not define programme dependency satisfaction; this CI selector only consumes the existing stable-ID DAG.
