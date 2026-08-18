---
id: 2731
topic: testing
source_issue: 11407
source_phase: plan
created_at: 2026-08-18T02:53:10.561499+00:00
status: stale
corroborations: 1
stale_reason: source issue #11407 closed
---

# Assert roster invariants, not exact body equality, in regression pins

Regression tests under `tests/regressions/` should assert the invariant they protect (roster length, call counts, site list membership) rather than `body == exact_string`. The #11328 pin over-specified with `body == legacy_body` and `update_calls == 0`, which a legitimate bind fix necessarily violated.

Rewrite to: roster length stays 1, `comment_calls == 0`, exactly one update call, site list reads `["src/branch_gc_scan.py:39"]`.

**Why:** Exact-body pins break on any legitimate roster-line rewrite, blocking fixes that preserve the protected invariant.
