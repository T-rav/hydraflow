---
id: 0806
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T12:54:49.509669+00:00
status: superseded
corroborations: 1
supersedes: 0750
superseded_by: 0861
---

# CREDIT_PROSE_SCAN=False marks runners that don't scan transcripts

Runners that don't analyze transcripts for credit-exhaustion text must set `CREDIT_PROSE_SCAN=False` so their output is never scanned for prose credit hits.

Example: Relevant to `src/runner_utils.py`, `src/adversarial_agent_runner.py`, `src/diagnostic_runner.py`.

**Why:** Prevents an unrelated nonzero exit coinciding with quoted credit-prose in stdout from misclassifying a signal as `cli`-origin (rc-based classification pre-mortem).
