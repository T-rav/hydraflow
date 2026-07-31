---
id: 1545
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T19:46:33.825708+00:00
status: superseded
corroborations: 1
supersedes: 1459
superseded_by: 1627
---

# Provenance union in _flow_verify spans all actives, never narrowed

Keep _flow_verify provenance as a union over ALL active entries — do not narrow it to just the partitioned write/supersede subsets. Even when partition_noop_synthesis carries most entries untouched, their citations stay in the provenance union.

Example: src/wiki_compiler.py _flow_verify follows the #10590 over-approximate-never-drop rule.

**Why:** Narrowing provenance to only changed entries would drop citations from carried (byte-identical) siblings, silently degrading wiki source coverage.
