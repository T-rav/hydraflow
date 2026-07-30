---
id: 1459
topic: testing
source_issue: 10797
source_phase: plan
created_at: 2026-07-28T09:50:07.998826+00:00
status: superseded
corroborations: 1
superseded_by: 1545
---

# Provenance union in _flow_verify spans all actives, never narrowed

Keep `_flow_verify` provenance as a union over ALL active entries — do not narrow it to just the partitioned write/supersede subsets.

- `src/wiki_compiler.py` `_flow_verify` follows the #10590 over-approximate-never-drop rule.
- Even when `partition_noop_synthesis` carries most entries untouched, their citations stay in the provenance union.

**Why:** Narrowing provenance to only changed entries would drop citations from carried (byte-identical) siblings, silently degrading wiki source coverage.
