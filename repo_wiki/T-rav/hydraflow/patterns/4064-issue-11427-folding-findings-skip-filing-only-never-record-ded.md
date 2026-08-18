---
id: 4064
topic: patterns
source_issue: 11427
source_phase: plan
created_at: 2026-08-18T04:40:50.671747+00:00
status: active
corroborations: 1
---

# Folding findings: skip filing only, never record dedup key

When a subject finding is folded into a spray finding (same template spraying this tick), the fold must skip filing **without** writing the subject's dedup key anywhere.

- If folding records the subject dedup key, a genuine subject finding is permanently suppressed even after the spray stops.
- Fold = skip `_file_findings` call only; dedup dict stays untouched.

**Why:** Recording a dedup key during fold creates a stale entry that blocks the subject finding from ever re-filing, even when it should.
