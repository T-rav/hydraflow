---
id: 0572
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:39:17.788253+00:00
status: superseded
corroborations: 1
supersedes: 0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0542,0543,0544,0545,0546,0547,0548,0549
superseded_by: 0584
---

# CREDIT_PROSE_SCAN=False marks runners that don't scan transcripts

Runners that analyze transcripts for credit-exhaustion text (vs. relying on exit code/stderr) set `CREDIT_PROSE_SCAN=False` on the ones that don't, so their output is never scanned for prose credit hits at all.

Example: relevant to `src/runner_utils.py`, `src/adversarial_agent_runner.py`, `src/diagnostic_runner.py`.

**Why:** prevents an unrelated nonzero exit coinciding with quoted credit-prose in stdout from misclassifying a signal as `cli`-origin (rc-based classification pre-mortem).
