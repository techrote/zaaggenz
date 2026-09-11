# Programme deployment status

**Repository:** `techrote/zaaggenz`  
**Stable programme:** `ZG-000`…`ZG-045`

## Published

- Overview epic: **ZG-000 → issue #1**.
- Implementation/research tasks: **ZG-001…ZG-045 → issues #2…#46**.
- Stable-ID map: `programme/issue_map.json`.
- Machine-readable task/dependency graph: `programme/tasks.json`, `programme/dependency_graph.json`.
- Master orchestration atlas: `docs/zaaggenz/OVERVIEW.md`.
- RAG/read-set index plus architecture, spectral, rhythm, experiment, validation, risk, workflow and source documentation.

## Deployment checks

- GitHub issue search returns all 46 stable-ID issues without duplication.
- Stable IDs, not issue numbers, are the dependency join key.
- The master atlas was reconciled with the actually deployed ZG-019…ZG-024 programme before this receipt was written.
- No supplied reference recording was uploaded to the repository.

## Current implementation gate

The repository was initially empty. **ZG-001 remains the first hard gate:** recover and provenance-check the actual v1.2.1 source/archive before implementation work assumes production paths, baseline hashes or test state.

The programme documentation may be improved in parallel, but implementation dependencies are not satisfied by this planning deployment alone.

## GitHub-native metadata

M0…M5 are programme milestone groups encoded in the issue bodies/master atlas. Native GitHub milestone objects and custom labels are not prerequisites for orchestration; `programme/tasks.json` is authoritative for group/dependency/lock data.
