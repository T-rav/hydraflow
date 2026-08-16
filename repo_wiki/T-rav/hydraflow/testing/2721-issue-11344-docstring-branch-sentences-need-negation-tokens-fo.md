---
id: 2721
topic: testing
source_issue: 11344
source_phase: plan
created_at: 2026-08-16T13:29:50.590305+00:00
status: active
corroborations: 1
---

# Docstring branch-sentences need negation tokens for test predicates

Rule: In `src/mockworld/fakes/fake_issue_fetcher.py` docstrings, every sentence containing `branch` AND one of `agent/issue`, `auto-agent`, `branch matches`, or `matches the branch` MUST also contain a negation token from `\b(not|never|n't|no|ignor\w*|unlike|diverg\w*|instead of|rather than)\b`.

- `_docstring_claims_branch_resolution()` in `tests/regressions/` scans per sentence; explanatory prose without negation is read as a **claim** and fails the pin.
- Trap: *"Any branch string resolves, so seeding a PR on the wrong branch stays green."* → no negation → re-fails.

**Why:** The predicate treats gap documentation as an assertion that the gap doesn't exist.
