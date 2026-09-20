# Programme deployment status

**Repository:** `techrote/zaaggenz`  
**Stable programme:** `ZG-000`…`ZG-045`

## Published

- Overview epic: **ZG-000 → issue #1**.
- Implementation/research tasks: **ZG-001…ZG-045 → issues #2…#46**.
- Stable-ID map: `programme/issue_map.json`.
- Machine-readable planned task/dependency graph: `programme/tasks.json`, `programme/dependency_graph.json`.
- Live evidence-aware task/readiness state: `programme/task_state.json`.
- Master orchestration atlas: `docs/zaaggenz/OVERVIEW.md`.
- RAG/read-set index plus architecture, spectral, rhythm, experiment, validation, risk, workflow and source documentation.

## Deployment checks

- GitHub issue search returns all 46 stable-ID issues without duplication.
- Stable IDs, not issue numbers, are the dependency join key.
- The master atlas was reconciled with the actually deployed ZG-019…ZG-024 programme before this receipt was written.
- No supplied reference recording was uploaded to the repository.

## Current authority

The repository began as a planning/deployment shell, but that bootstrap state is historical. ZG-001/G0 recovery is accepted: the owner-supplied v1.2.1 archive and compact runtime payload are authenticated and materialisable from the repository.

Current authority is deliberately split by concern:

- `programme/task_state.json` owns live implementation/evidence/research/owner-gate state and the explicit `dependency_satisfied` decision;
- `programme/tasks.json` and `programme/dependency_graph.json` own the planned hard prerequisites, groups and shared locks;
- `programme/issue_map.json` owns stable-ID → GitHub issue navigation;
- GitHub issue open/closed state is informational and cannot independently satisfy or revoke a dependency.

This deployment receipt is not a second progress ledger. Agents must consume the live state rather than infer readiness from this file.

## GitHub-native metadata

M0…M5 are programme milestone groups encoded in the issue bodies/master atlas. Native GitHub milestone objects and custom labels are not prerequisites for orchestration; `programme/tasks.json` is authoritative for group/dependency/lock data.
