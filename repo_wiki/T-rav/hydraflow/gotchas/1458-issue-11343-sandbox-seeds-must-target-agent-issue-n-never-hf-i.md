---
id: 1458
topic: gotchas
source_issue: 11343
source_phase: plan
created_at: 2026-08-16T13:08:39.701098+00:00
status: active
corroborations: 1
---

# Sandbox seeds must target agent/issue-N, never hf/issue-N

Sandbox scenario seeds must place PRs on `agent/issue-N` — the head that `config.branch_for_issue(N)` produces and `src/` actually mints. The `hf/issue-N` namespace matches nothing in `src/`, so every branch-keyed consumer sees "input production cannot produce."

- s04/s08/s38/s81 all had seeds on `hf/issue-N` or non-canonical heads
- `scripts.implement` is out of scope — its `hf/issue-N` usage is tracked separately in #11338

**Why:** Mismatched heads orphan seeded PRs and create branch states production's `pr_manager.py` dedupe logic can never reach.
