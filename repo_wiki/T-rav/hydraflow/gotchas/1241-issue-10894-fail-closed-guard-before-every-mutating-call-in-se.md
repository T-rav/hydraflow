---
id: 1241
topic: gotchas
source_issue: 10894
source_phase: plan
created_at: 2026-07-31T11:12:50.925708+00:00
status: active
corroborations: 1
---

# Fail-closed guard before every mutating call in setup_branch_protection.py

`scripts/setup_branch_protection.py` must check `undeclared_contexts_by_branch` before any `POST`, `PUT`, or branch-create call, not after `_ensure_*` writes. Provide `--allow-derequire` to override and `--audit` to report-and-exit-1.

- Dry-run: warn, exit 0.
- `--apply` with undeclared context: exit non-zero, zero writes.
- `--allow-derequire`: performs the PUT.

**Why:** A guard that runs after writes already de-required the live check (#10878), or that blocks legitimate reconciliation, defeats the safety contract.
