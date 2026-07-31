---
id: 1954
topic: testing
source_issue: 10904
source_phase: plan
created_at: 2026-07-31T10:40:34.520364+00:00
status: superseded
corroborations: 1
superseded_by: 2072
---

# Parse both sides at runtime in drift-guard tests

A drift guard that hardcodes the expected path list becomes the Nth copy and drifts silently. Parse both sides at runtime — `yaml.safe_load` for workflow YAML, textual regex for `Makefile` assignments — and assert bidirectional set equality. The only acceptable hardcoded constant is a documented *delta* between related sets (e.g. `REAP_TESTS` vs `linux-signal-smoke`: 7 vs 6, differing by `test_auto_pr_preflight_gate.py`).

**Why:** Hardcoding the list makes the guard a participant in the drift it should detect.
