---
id: 0163
topic: architecture
source_issue: 10394
source_phase: plan
created_at: 2026-07-24T05:04:19.027250+00:00
status: active
corroborations: 1
---

# LabelDriftWatcherLoop reconcile actions must be idempotent, no re-comment loop

New `LabelDrift.kind` values (src/models.py) handled by `LabelDriftWatcherLoop._reconcile` (ADR-0088) must clear the offending label idempotently and post at most one audit comment per drift instance — repeated caretaker ticks over the same closed issue must not re-comment. Scope the scan to recently-closed issues with a `--limit`, not an unbounded history scan.

**Why:** an unbounded or non-idempotent caretaker scan turns a one-time cleanup into a recurring noisy/expensive tick, per the ADR-0029 caretaker loop pattern.
