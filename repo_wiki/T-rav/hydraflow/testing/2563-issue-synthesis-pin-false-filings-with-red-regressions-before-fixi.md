---
id: 2563
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.541942+00:00
status: active
corroborations: 1
supersedes: 2374
---

# Pin false filings with RED regressions before fixing the metric

Before touching metric code, write a regression in `tests/regressions/test_issue_11093.py` that reproduces the exact false filing on today's code.

Example: replay the real telemetry snapshot (847 calls / $5.206703) through `compute_skill_efficiency` and a `SkillPromptEvalLoop` fake-PR port — no mocked math. Assert the filed +168% appears pre-fix and disappears post-fix. Falsify every prescribed repair path in the issue body.

**Why:** An implementer who follows the issue body's prescription without fixing the metric causes the false filing to recur next tick.
