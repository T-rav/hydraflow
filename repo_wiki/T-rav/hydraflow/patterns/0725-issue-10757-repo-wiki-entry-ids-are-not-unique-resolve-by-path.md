---
id: 0725
topic: patterns
source_issue: 10757
source_phase: plan
created_at: 2026-07-28T00:08:58.218745+00:00
status: active
corroborations: 1
---

# repo_wiki entry IDs are not unique — resolve by path, fan out successors

Rule: When resolving wiki entries in `repo_wiki/`, resolve predecessors by `path` but resolve successors across every file bearing the id — ids are not unique in the live corpus.

- A duplicated successor id counts as `represented` when any file bearing that id carries the lesson.
- Cycle-guard chain-following even though no cycles exist today; the corpus drifts.

**Why:** Assuming id uniqueness causes silent misses: the first file bearing an id may lack the lesson while a later file carries it, producing a false `orphaned` tier.
