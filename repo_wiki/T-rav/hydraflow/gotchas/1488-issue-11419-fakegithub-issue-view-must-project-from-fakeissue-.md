---
id: 1488
topic: gotchas
source_issue: 11419
source_phase: plan
created_at: 2026-08-18T03:36:18.966907+00:00
status: active
corroborations: 1
---

# FakeGitHub issue view must project from FakeIssue state, not constants

The `issue view --json` branch in `FakeGitHub._run_gh` must build its payload from the seeded `FakeIssue` for the fields named after `--json` (labels as `[{"name": …}]`, `body`, `number`, `title`, `state`, `updatedAt`, `comments` reusing `list_issue_comments` shape). Unknown issue number → `{}`-shaped answer consistent with real `gh`.

**Why:** A fixed `{"comments": []}` payload makes the fake lie about issue state, which hid the body-clobber bug where `_verify_issue` rewrote an issue to just the screenshot appendix, discarding the original body.
