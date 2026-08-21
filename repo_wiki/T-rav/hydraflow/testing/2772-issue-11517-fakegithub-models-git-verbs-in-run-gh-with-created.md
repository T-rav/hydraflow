---
id: 2772
topic: testing
source_issue: 11517
source_phase: plan
created_at: 2026-08-21T09:19:56.754306+00:00
status: active
corroborations: 1
---

# FakeGitHub models git verbs in _run_gh with created_tags recorder

When a Port method gains git plumbing, extend `src/mockworld/fakes/fake_github.py`'s `_run_gh` dispatch with a `git` verb branch modeling `fetch`/`rev-parse`/`tag`/`push`, and record `(tag, ref)` pairs in a list (e.g. `created_tags`). Unknown commands must still raise (#11372).

- MockWorld scenario (auto-discovered by `tests/scenarios/` runner, no registry edit) asserts `created_tags` shows `(tag, ref=origin/<main>)` with the fetch preceding it; Pattern B delegation like `test_rebase_on_conflict_scenario.py:110–118`.

**Why:** keeps the Port docstring / PRManager / FakeGitHub three-layer mirror intact, and scenarios cannot assert ref-targeting without the recorder.
