---
id: 0605
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.350217+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# CREDIT_PROSE_SCAN=False marks runners that don't scan transcripts

Runners that analyze transcripts for credit-exhaustion text set `CREDIT_PROSE_SCAN=False` on the ones that don't, so their output is never scanned for prose credit hits at all.

Example: relevant to `src/runner_utils.py`, `src/adversarial_agent_runner.py`, `src/diagnostic_runner.py`.

**Why:** prevents an unrelated nonzero exit coinciding with quoted credit-prose in stdout from misclassifying a signal as `cli`-origin.
