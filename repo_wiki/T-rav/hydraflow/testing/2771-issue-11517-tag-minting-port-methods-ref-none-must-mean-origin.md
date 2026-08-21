---
id: 2771
topic: testing
source_issue: 11517
source_phase: plan
created_at: 2026-08-21T09:19:56.754297+00:00
status: active
corroborations: 1
---

# Tag-minting Port methods: ref=None must mean origin/main, never HEAD

Design tag-minting Port methods with an explicit `ref: str | None = None` where `None` means "resolve `origin/<main_branch>`" — never "use `HEAD`".

- `PRManager.create_tag`'s only production caller is `src/epic.py` `_create_release_for_epic`; `tests/test_release.py:318,350` mock it.
- Route all git plumbing through the existing `_run_gh` seam — no new subprocess path.

**Why:** bare `git tag vX.Y.Z` defaults to HEAD, i.e. the factory checkout — a future caller omitting the ref would silently reintroduce #11517.
