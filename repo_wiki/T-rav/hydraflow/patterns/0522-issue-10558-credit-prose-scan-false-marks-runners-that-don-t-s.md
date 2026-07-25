---
id: 0522
topic: patterns
source_issue: 10558
source_phase: plan
created_at: 2026-07-25T23:16:50.588372+00:00
status: active
corroborations: 1
---

# CREDIT_PROSE_SCAN=False marks runners that don't scan transcripts

Runners that analyze transcripts for credit-exhaustion text (vs. relying on exit code/stderr) set `CREDIT_PROSE_SCAN=False` on the ones that don't, so their output is never scanned for prose credit hits at all.
- Relevant to `src/runner_utils.py`, `src/adversarial_agent_runner.py`, `src/diagnostic_runner.py`.
**Why:** prevents an unrelated nonzero exit coinciding with quoted credit-prose in stdout from misclassifying a signal as `cli`-origin (rc-based classification pre-mortem).
