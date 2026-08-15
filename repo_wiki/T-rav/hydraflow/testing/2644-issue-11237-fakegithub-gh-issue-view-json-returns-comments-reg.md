---
id: 2644
topic: testing
source_issue: 11237
source_phase: plan
created_at: 2026-08-15T09:27:56.205900+00:00
status: active
corroborations: 1
---

# FakeGitHub gh issue view --json returns comments regardless of selector

`FakeGitHub` models `gh issue view --json` by returning `{"comments": []}` for any `--json` selector. This means `report_issue_loop`'s `--json labels,body` read is matched-but-wrong — it receives `comments` instead of `labels` or `body`.

- Strict mode cannot detect this because the command shape matches.
- Requires shape-specific assertions on returned fields to catch.

**Why:** Matched-but-wrong responses are a class of fake defect invisible to strict-mode gating; they need field-level test assertions, not command-level matching.
