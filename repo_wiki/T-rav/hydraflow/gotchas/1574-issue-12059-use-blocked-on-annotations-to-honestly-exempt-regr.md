---
id: 1574
topic: gotchas
source_issue: 12059
source_phase: plan
created_at: 2026-09-02T22:09:40.835405+00:00
status: active
corroborations: 1
---

# Use blocked-on annotations to honestly exempt regression pins pending epic resolution

Mark deliberately-silenced pins with `# hydraflow-regression-rot: blocked-on #N` annotation in `tests/regressions/regression_issue_<N>.py` rather than rewriting test assertions. This documents why the pin exists without lying about test results. Example: apply to ~40 live-bug pins after reopening their issues under an epic. Pair with epic body listing every reopened issue and its captured failure line. Why: Rewriting assertions to pass deletes the real contract; annotations preserve truth and enable audit trails.
