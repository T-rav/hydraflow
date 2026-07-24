---
id: 0493
topic: gotchas
source_issue: 10419
source_phase: plan
created_at: 2026-07-24T07:06:01.754978+00:00
status: active
corroborations: 1
---

# adr_reviewer.py logs pre-validation advisories via logger.warning, not routing

After calling `validate(...)` in `src/adr_reviewer.py`, any `validation.advisories` should be logged with `logger.warning` using a literal format string — do not pass them to `_route_pre_validation_failure`, which is reserved for `issues`. This keeps the ADR flowing to council even when advisories exist.
**Why:** reusing the issue-routing path for advisories would gate ADRs on a warning-only signal, defeating the point of a non-blocking nudge.
