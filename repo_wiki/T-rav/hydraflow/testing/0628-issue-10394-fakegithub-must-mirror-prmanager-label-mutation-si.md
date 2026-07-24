---
id: 0628
topic: testing
source_issue: 10394
source_phase: plan
created_at: 2026-07-24T05:04:19.027229+00:00
status: active
corroborations: 1
---

# FakeGitHub must mirror PRManager label-mutation side effects exactly

When `PRManager` (src/pr_manager.py) gains a new side effect in a Port method like `close_issue` (e.g. stripping active stage labels), `src/mockworld/fakes/fake_github.py`'s `close_issue` must be updated in the same change to mirror it. Divergence between the real port and its fake breaks MockWorld scenario fidelity — scenarios would pass against a fake that doesn't reflect real GitHub behavior.

**Why:** MockWorld's value depends on the fake being a faithful contract twin; unmirrored side effects let scenario tests give false confidence.
