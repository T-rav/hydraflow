---
id: 1048
topic: gotchas
source_issue: 10582
source_phase: plan
created_at: 2026-07-26T02:05:19.449731+00:00
status: active
corroborations: 1
---

# WikiRotDetectorLoop never walks repo_wiki/, only docs/wiki/

`WikiRotDetectorLoop` calls `repo_dir(slug)`, which for the self repo resolves to `docs/wiki/` — it never scans `repo_wiki/<slug>/gotchas/*.md` directly. A shipped-claim marker added under `repo_wiki/` is only machine-checked once `RepoWikiLoop` synthesis carries that content into `docs/wiki/gotchas.md`. Until then, a regression test (e.g. `tests/regressions/test_issue_10582.py`) is the only verification that the marker is well-formed.

**Why:** Assuming the rot detector validates `repo_wiki/` entries directly leads to false confidence that a marker is being checked when it isn't yet.
