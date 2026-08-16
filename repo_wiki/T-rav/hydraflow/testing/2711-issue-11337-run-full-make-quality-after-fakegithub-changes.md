---
id: 2711
topic: testing
source_issue: 11337
source_phase: plan
created_at: 2026-08-16T11:25:49.892542+00:00
status: active
corroborations: 1
---

# Run full make quality after FakeGitHub changes

`src/mockworld/fakes/fake_github.py` is shared by the entire scenario suite. A file-targeted pytest subset is not sufficient evidence after modifying it. Always run the full `make quality` target before declaring done.

**Why:** Hundreds of scenario tests depend on `FakeGitHub` defaults and behavior; a subset run misses regressions in unrelated scenarios.
