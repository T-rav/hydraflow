---
id: 2649
topic: testing
source_issue: 11246
source_phase: plan
created_at: 2026-08-15T20:20:19.664578+00:00
status: active
corroborations: 1
---

# gh issue view projection must use gh wire shapes, not FakeIssue attrs

When projecting `FakeIssue` state for `gh issue view --json`, convert to gh wire shapes: `labels` → `[{"name": ...}]`, keys camelCase (`stateReason`, `updatedAt`), `comments` → GraphQL `author.login`/`createdAt` shape.

The output contract must match what `PRManager._normalise_issue_comment` (src/report_issue_loop.py) and `GhIssueSummary` (src/contracts/shapes.py:126) consume from real `gh`.

**Why:** Returning raw `FakeIssue` attribute shapes causes consumer parsing to silently misbehave under MockWorld while tests pass against the fake.
