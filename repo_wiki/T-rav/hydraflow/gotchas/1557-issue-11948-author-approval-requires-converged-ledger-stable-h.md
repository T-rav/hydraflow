---
id: 1557
topic: gotchas
source_issue: 11948
source_phase: plan
created_at: 2026-09-01T10:57:18.007780+00:00
status: active
corroborations: 1
---

# Author approval requires converged ledger + stable head SHA

An `author`-role approval in `merge_policy` is only issuable by `src/author_convergence.py`, which checks two conditions: `ConvergenceLedger.converged == True` and `StateTracker.get_last_reviewed_sha == pr_head_sha`.

- Converged ledger, moved head → no approval
- Not converged → no approval
- Absent ledger → no approval

**Why:** Prevents merging a substantial PR whose content changed after the last review pass, which is the exact CI-green-only failure `pr_unsticker/_merge.py` exhibited.
