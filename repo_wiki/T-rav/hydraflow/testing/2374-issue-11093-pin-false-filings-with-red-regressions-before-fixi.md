---
id: 2374
topic: testing
source_issue: 11093
source_phase: plan
created_at: 2026-08-14T06:48:30.313353+00:00
status: superseded
corroborations: 1
superseded_by: 2563
---

# Pin false filings with RED regressions before fixing the metric

Before touching metric code, write a regression in `tests/regressions/test_issue_11093.py` that reproduces the exact false filing on today's code.

- Replay the real telemetry snapshot (847 calls / $5.206703) through `compute_skill_efficiency` and a `SkillPromptEvalLoop` fake-PR port — no mocked math.
- Assert the filed +168% appears pre-fix and disappears post-fix.
- Falsify every prescribed repair path in the issue body (zero lifetime `cache_read_input_tokens`, model swap inside baseline, flat prompt size).

**Why:** An implementer who follows the issue body's prescription (context bloat / cache / model swap) without fixing the metric causes the false filing to recur next tick.
