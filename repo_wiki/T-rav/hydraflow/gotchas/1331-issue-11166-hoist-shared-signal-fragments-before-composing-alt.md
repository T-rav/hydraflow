---
id: 1331
topic: gotchas
source_issue: 11166
source_phase: plan
created_at: 2026-08-14T19:18:14.572498+00:00
status: active
corroborations: 1
---

# Hoist shared signal fragments before composing alternation

When two alternation branches hand-copy the same signal, define each fragment once and compose the alternation from named constants.

In `scripts/hydraflow_audit/checks/p8_superpowers.py`, `_P87_REVIEW_EVERY_PR_RE` had two branches each spelling `review` independently — a future anchor edit could land on one branch only. Hoisting a review fragment and an every/each-PR cadence fragment makes divergence impossible.

**Why:** Duplicated literals across alternation branches let fixes apply inconsistently, reintroducing the original false-PASS bug in one branch.
