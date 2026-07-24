---
id: 0637
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.712365+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# adr_reviewer.py logs pre-validation advisories via logger.warning, not routing

After calling `validate(...)` in `src/adr_reviewer.py`, any `validation.advisories` should be logged with `logger.warning` using a literal format string — do not pass them to `_route_pre_validation_failure`, which is reserved for `issues`.

Example: this keeps the ADR flowing to council even when advisories exist.

**Why:** Reusing the issue-routing path for advisories would gate ADRs on a warning-only signal, defeating the point of a non-blocking nudge.
