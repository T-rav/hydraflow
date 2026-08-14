---
id: 2418
topic: testing
source_issue: 11160
source_phase: plan
created_at: 2026-08-14T18:34:20.225997+00:00
status: active
corroborations: 1
---

# Run full make quality for shared loop modules, not subsets

`src/escape_ledger_loop.py` is shared by 5+ regression pins. File-targeted test subsets are unacceptable; always run full `make quality`. Regression pin tests use real temp git repos, `FakeGitHub`, and `tests/helpers.make_bg_loop_deps` — no new helpers duplicating `tests/conftest.py`.

**Why:** Shared modules have cross-cutting coverage; subset runs miss regressions in dependent pins.
