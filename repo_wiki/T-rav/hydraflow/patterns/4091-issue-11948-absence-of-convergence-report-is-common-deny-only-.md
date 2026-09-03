---
id: 4091
topic: patterns
source_issue: 11948
source_phase: plan
created_at: 2026-09-01T10:57:18.007865+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Absence of convergence report is common — deny only for substantial class

`post_merge_handler` clears the `ConvergenceLedger` after merge, and PRs resumed through HITL or `pr_unsticker` may never have had one. "No convergence report" is the *common* state for those paths.

- Deny absence only for entries requiring the `author` role (the substantial-change class)
- Non-substantial PRs must merge without a ledger
- Escalation message must name the missing convergence report explicitly

**Why:** Prevents a self-inflicted HITL flood where every ordinary PR escalates.
