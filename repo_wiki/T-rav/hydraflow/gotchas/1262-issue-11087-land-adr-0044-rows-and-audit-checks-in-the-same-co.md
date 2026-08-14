---
id: 1262
topic: gotchas
source_issue: 11087
source_phase: plan
created_at: 2026-08-14T06:12:02.565749+00:00
status: active
corroborations: 1
---

# Land ADR-0044 rows and audit checks in the same commit

When adding a principle to `docs/adr/0044-hydraflow-principles.md` (e.g. P8.7), register the corresponding check in `scripts/hydraflow_audit/checks/p8_superpowers.py` in the same commit. A row without a registered check produces `NOT_IMPLEMENTED`, which fails `make audit`. **Why:** The audit dispatcher treats an unregistered principle as a hard failure, not a warning — splitting the row and the check across commits breaks CI for every adopter.
