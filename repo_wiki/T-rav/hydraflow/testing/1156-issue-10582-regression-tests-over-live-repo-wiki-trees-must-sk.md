---
id: 1156
topic: testing
source_issue: 10582
source_phase: plan
created_at: 2026-07-26T02:05:19.449769+00:00
status: active
corroborations: 1
---

# Regression tests over live repo_wiki/ trees must skip-guard on file existence

`RepoWikiLoop` actively rewrites `repo_wiki/` (supersession, pruning, `active_lint_tracked` status flips), so a regression test asserting on a specific live entry (e.g. `0841-*.md`) must `pytest.skip` if the file is absent rather than fail. `tests/regressions/test_issue_10566.py` established this pattern; `tests/regressions/test_issue_10582.py` follows it — mechanism assertions run against synthetic `tmp_path` fixtures, and only a thin, skip-guarded check touches the live tree.

**Why:** Hard-pinning live wiki paths makes CI go red the moment an unrelated `RepoWikiLoop` tick supersedes or prunes the entry.
