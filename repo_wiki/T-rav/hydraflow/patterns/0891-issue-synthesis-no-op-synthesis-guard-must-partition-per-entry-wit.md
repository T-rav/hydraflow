---
id: 0891
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T14:29:08.561511+00:00
status: active
corroborations: 1
supersedes: 0836
---

# No-op synthesis guard must partition per-entry with multiset matching

Use multiset (Counter) matching when comparing compiled wiki bodies against actives, not set equality — duplicate bodies within a topic must preserve multiplicity.

Example: `partition_noop_synthesis(active_entries, compiled)` in `src/repo_wiki.py` returns `(write, supersede, carried)` index tuples. Two actives sharing a body, one compiled copy → exactly one active superseded. Whole-topic `synthesis_matches_active_bodies` delegates to this for backward compat.

**Why:** Set-based matching collapses duplicate siblings, so a single edit to one entry re-mints every byte-identical sibling and cascades superseded status across the topic.
