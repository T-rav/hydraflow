---
id: 0546
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:44:03.250004+00:00
status: superseded
corroborations: 1
supersedes: 0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522
superseded_by: 0550
---

# CREDIT_PROSE_SCAN=False marks runners that don't scan transcripts

Runners that analyze transcripts for credit-exhaustion text (vs. relying on exit code/stderr) set `CREDIT_PROSE_SCAN=False` on the ones that don't, so their output is never scanned for prose credit hits at all.

Example: relevant to `src/runner_utils.py`, `src/adversarial_agent_runner.py`, `src/diagnostic_runner.py`.

**Why:** prevents an unrelated nonzero exit coinciding with quoted credit-prose in stdout from misclassifying a signal as `cli`-origin (rc-based classification pre-mortem).
