---
id: 2712
topic: testing
source_issue: 11333
source_phase: plan
created_at: 2026-08-16T11:30:55.516414+00:00
status: active
corroborations: 1
---

# FakeGitHub.list_issues_by_label is unwindowed; truncation tests need real gh

The MockWorld tier cannot exercise window-saturation truncation because `FakeGitHub.list_issues_by_label` returns all matching issues regardless of limit. The meaningful integration seam for truncation is the `gh` subprocess, driven by the regression pin directly.

- Mark MockWorld tier `N/A with reason` when the behavior under test is subprocess-window-specific.
- Sandbox e2e is also N/A when no docker/UI/wiring surface is touched.

**Why:** Asserting truncation against an unwindowed fake would always pass vacuously and hide the real `gh` window regression.
