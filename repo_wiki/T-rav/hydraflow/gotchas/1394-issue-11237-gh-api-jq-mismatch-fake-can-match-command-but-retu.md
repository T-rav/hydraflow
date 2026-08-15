---
id: 1394
topic: gotchas
source_issue: 11237
source_phase: plan
created_at: 2026-08-15T09:27:56.205882+00:00
status: active
corroborations: 1
---

# gh api --jq mismatch: fake can match command but return wrong shape

When modelling `gh api` reads in `FakeGitHub`, verify the fake returns the post-`--jq` projected shape, not the raw API payload. `StaleIssueLoop`'s branch-GC reads (`gh api .../git/matching-refs/heads/<prefix>`, `gh api .../commits`) pass `--jq` and parse the projected result.

- A fake that matches the command prefix but returns the full payload passes strict mode silently.
- Assert observable outcomes (e.g., `branch_gc_commented == 1` via `FakeGitHub` state), not just an empty `unmatched_gh_commands()` list.

**Why:** A matched-but-wrong fake response is invisible to strict-mode gating and produces a vacuous scenario.
