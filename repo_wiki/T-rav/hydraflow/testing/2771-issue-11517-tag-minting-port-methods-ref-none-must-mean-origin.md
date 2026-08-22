---
id: 2771
topic: testing
source_issue: 11517
source_phase: plan
created_at: 2026-08-21T09:19:56.754297+00:00
status: active
corroborations: 1
---

# Tag-minting methods: ref is required and keyword-only, never defaulted

`PRManager.create_tag(self, tag: str, *, ref: str)` takes `ref` keyword-only with **no default** (`src/pr_manager.py`). Callers obtain `ref` from `resolve_remote_branch_sha(config.main_branch)` and skip fail-closed on `None`; they never pass a symbolic ref or omit it.

- Do NOT add an `Optional[str] = None` convenience where `None` means "resolve `origin/<main_branch>`" — the sentinel re-creates the default-to-something footgun one step removed, and a future caller reading `ref=None` cannot tell "resolve main" from "whatever HEAD is". Resolution is an explicit, separate call.
- The no-default signature is pinned by `tests/regressions/test_issue_11517.py::test_create_tag_requires_an_explicit_ref`; `tests/test_release.py` covers the resolve/tag argv and the fail-closed branches.
- `create_tag`'s only production caller is `src/epic.py` `_create_release_for_epic`. All git plumbing goes through the existing `_run_gh` seam — no new subprocess path.

**Why:** bare `git tag vX.Y.Z` defaults to HEAD, i.e. the factory checkout (#11517). Making the ref mandatory at the type level is what stops the next caller from silently reintroducing it.
