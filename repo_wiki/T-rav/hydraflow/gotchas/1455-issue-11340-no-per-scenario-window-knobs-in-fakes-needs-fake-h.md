---
id: 1455
topic: gotchas
source_issue: 11340
source_phase: plan
created_at: 2026-08-16T11:56:57.838107+00:00
status: active
corroborations: 1
---

# No per-scenario window knobs in fakes; needs _FAKE_HELPER_OVERRIDES

Do not add per-scenario configurable window sizes to `FakeGitHub`. A knob is a fresh divergence surface from the real adapter and requires a `_FAKE_HELPER_OVERRIDES` entry in `src/fake_coverage_auditor_loop.py`.

- Instead of `FakeGitHub(list_limit=50)`, have the fake import `OPEN_ISSUE_LIST_LIMIT` from `src/pr_manager.py` and always slice to that constant.

**Why:** Configurable fake behavior absent from the real adapter breaks the fake-adapter parity contract (ADR-0047) and adds audit burden.
