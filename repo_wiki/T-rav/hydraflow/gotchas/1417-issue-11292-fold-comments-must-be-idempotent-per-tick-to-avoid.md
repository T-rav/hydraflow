---
id: 1417
topic: gotchas
source_issue: 11292
source_phase: plan
created_at: 2026-08-16T01:48:07.890784+00:00
status: active
corroborations: 1
---

# Fold comments must be idempotent per tick to avoid re-comment loops

When `file_or_fold` posts a site-comment to an existing class issue, the comment must be idempotent — re-filing an already-listed site posts NO second comment. Reuse the `LabelDriftWatcher` no-re-comment rule.

**Why:** Loop-tier re-entry (FakeGitHub, no human gating) without idempotency produces comment storms on every tick where the same defect is rediscovered, polluting the issue thread and breaking board-growth assertions.
