---
id: 2709
topic: testing
source_issue: 11337
source_phase: plan
created_at: 2026-08-16T11:25:49.892465+00:00
status: active
corroborations: 1
---

# add_pr defaults must match FakePR field defaults

When adding keyword params to `FakeGitHub.add_pr`, every default must equal the corresponding `FakePR` field default. ~100 existing callers depend on seeded PRs being open, non-draft, and url-less.

Example: `add_pr(draft: bool = False, closed: bool = False, url: str = "")` mirrors `FakePR(draft=False, closed=False, url="")`. The guard test `test_add_pr_defaults_match_fakepr_defaults` enforces this.

**Why:** A default that drifts silently rewrites every seeded world in the scenario suite.
