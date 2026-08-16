---
id: 3676
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T13:50:49.097986+00:00
status: active
corroborations: 1
supersedes: 3531
---

# No-op synthesis guard must partition per-entry with multiset matching

Use multiset (Counter) matching when comparing compiled wiki bodies against actives, not set equality — duplicate bodies within a topic must preserve multiplicity.

Example: `partition_noop_synthesis(active_entries, compiled)` in `src/repo_wiki.py` returns `(write, supersede, carried)` tuples. Two actives sharing a body, one compiled copy → exactly one active superseded. See also: [patterns] — Guard wiki synthesis with a content-equivalence no-op check.

**Why:** Set-based matching collapses duplicate siblings, so a single edit to one entry re-mints every byte-identical sibling and cascades superseded status across the topic.
