---
id: 0245
topic: architecture
source_issue: 10750
source_phase: plan
created_at: 2026-07-27T22:53:53.519960+00:00
status: active
corroborations: 1
---

# FakeWikiCompiler stub can't test supersession frontmatter writes

`FakeWikiCompiler.compile_topic_tracked` is a call-counting stub that never writes supersession frontmatter, so the MockWorld loop tier has no observable surface for supersession behavior. Use real `WikiCompiler` + stubbed LLM over a tmp tracked root for regression tests (pattern: `tests/regressions/test_issue_10566.py`). **Why:** MockWorld tier silently passes supersession defects that only the real-compiler layer catches.
