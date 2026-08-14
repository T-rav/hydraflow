---
id: 0337
topic: architecture
source_issue: 11181
source_phase: plan
created_at: 2026-08-14T23:04:04.877842+00:00
status: active
corroborations: 1
---

# Avoid cross-module private-symbol imports; use tuple returns

When a helper in `src/` needs to return extra data to a caller in another module, return a plain `tuple` rather than a `_`-prefixed dataclass that tests or siblings would import.

`_triage_fleet_batch` returns `tuple[str, int]` (outcome, calls attempted) instead of a `_BudgetResult` dataclass, because importing a `_`-prefixed symbol across modules is a known gotcha in this repo.

**Why:** Cross-module `_` imports break the private-symbol contract and create hidden coupling that future refactors will silently miss.
