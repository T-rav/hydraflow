---
id: 1411
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T16:53:01.982387+00:00
status: superseded
corroborations: 1
supersedes: 1332
superseded_by: 1495
---

# CREDIT_PROSE_SCAN=False marks runners that don't scan transcripts

Runners that don't analyze transcripts for credit-exhaustion text must set `CREDIT_PROSE_SCAN=False` so their output is never scanned for prose credit hits.

Example: Relevant to `src/runner_utils.py`, `src/adversarial_agent_runner.py`, `src/diagnostic_runner.py`.

**Why:** Prevents an unrelated nonzero exit coinciding with quoted credit-prose in stdout from misclassifying a signal as `cli`-origin.
