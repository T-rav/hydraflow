---
id: 1485
topic: gotchas
source_issue: 11415
source_phase: plan
created_at: 2026-08-18T03:26:10.006549+00:00
status: active
corroborations: 1
---

# Widen fake signatures, never narrow them

When a conformance violation reveals a fake param stricter than its reference, fix the fake by widening — never narrow the reference or change callers.

- `FakeGitHub.list_closed_issues_by_label`: dropped `*` so `limit` became positional-or-keyword.
- `FakeWikiCompiler.compile_topic_tracked`: added positional `tracked_root, repo, topic` plus keyword-only `other_topics`.

**Why:** Fakes must remain drop-in substitutes for production callers; widening the fake is safe because existing call sites already pass within the narrower contract.
