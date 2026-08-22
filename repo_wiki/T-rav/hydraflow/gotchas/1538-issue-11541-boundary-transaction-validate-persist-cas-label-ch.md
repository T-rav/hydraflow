---
id: 1538
topic: gotchas
source_issue: 11541
source_phase: plan
created_at: 2026-08-22T00:00:10.177911+00:00
status: active
corroborations: 1
---

# Boundary transaction: validate, persist, CAS label, checkpoint

Brokered artifacts advance through a fixed four-step boundary transaction: validate artifact → persist by idempotency key → CAS the GitHub label → append checkpoint.

- Plan validation, constitution, and cohort gates run on the brokered artifact exactly as on a Classic one — no gate exemption for Fable-directed issues.
- `src/director_checkpoint.py` must checkpoint outstanding request ids so resume-after-crash reproduces the same phase without duplicate dispatch.

**Why:** Safety comes from this transaction boundary, not from Fable — skipping any step lets a crash or outage produce a label advance with no persisted artifact or a duplicate dispatch with no checkpoint.
