---
id: 2653
topic: testing
source_issue: 11275
source_phase: plan
created_at: 2026-08-15T20:45:30.666465+00:00
status: active
corroborations: 1
---

# MockWorld matching-refs fakes need per-prefix branches

When adding a new entry to `_BRANCH_GC_PREFIXES` in `src/stale_issue_loop.py`, add a corresponding fake branch in the MockWorld scenario. The `matching-refs` fake keys on the literal prefix string passed to `_run_gh`.

Example: a new prefix with no fake branch silently returns `[]`; the scenario test stays green but exercises zero new code paths.

**Why:** Silent green tests mask missing coverage — the only signal that the fake matched is an explicit assertion on `_run_gh` calls or a truth-comment assertion on the issue.
