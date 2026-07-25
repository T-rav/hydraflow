---
id: 0807
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T01:13:09.962900+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# adr_reviewer.py logs pre-validation advisories via logger.warning, not routing

After calling `validate(...)` in `src/adr_reviewer.py`, any `validation.advisories` should be logged with `logger.warning` using a literal format string — do not pass them to `_route_pre_validation_failure`, which is reserved for `issues`.

Example: this keeps the ADR flowing to council even when advisories exist.

**Why:** Reusing the issue-routing path for advisories would gate ADRs on a warning-only signal, defeating the point of a non-blocking nudge.
