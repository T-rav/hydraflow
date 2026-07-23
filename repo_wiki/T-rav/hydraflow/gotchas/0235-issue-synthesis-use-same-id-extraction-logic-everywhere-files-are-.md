---
id: 0235
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.800422+00:00
status: superseded
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
superseded_by: 0248
---

# Use same ID extraction logic everywhere files are keyed by issue

Define ID prefix lengths as named constants and centralize extraction so every site that keys files by issue uses identical logic.

Example: define `DISCOVER_PREFIX_LEN = 9`; use it in both the writer and the reader rather than hardcoding `fname[9:]` in each.

**Why:** Inconsistent ID logic causes silent lookup failures — a plan is written under key A but read back under key B, producing phantom missing plans.
