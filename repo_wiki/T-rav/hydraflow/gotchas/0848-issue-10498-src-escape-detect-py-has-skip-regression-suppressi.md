---
id: 0848
topic: gotchas
source_issue: 10498
source_phase: review
created_at: 2026-07-25T09:07:23.395846+00:00
status: superseded
corroborations: 1
superseded_by: 0851
---

# src/escape/detect.py has_skip_regression suppression is silent (no telemetry)

In `src/escape/detect.py:134`, the bug-issue branch's `has_skip_regression` suppression does a bare `return None` with no logging or counter — a false negative (a real defect fix that legitimately carries `Skip-Regression` for a non-docs reason) is currently invisible to operators. Flagged as a blocking finding in PR #10525 review but left unfixed pending sign-off; when addressing, add an observable counter/log at the loop level rather than inside `detect.py` itself.

**Why:** an uncounted suppression path means regression-pin false negatives can accumulate with no signal, undermining [[escape_detect_skip_regression_gate]].
