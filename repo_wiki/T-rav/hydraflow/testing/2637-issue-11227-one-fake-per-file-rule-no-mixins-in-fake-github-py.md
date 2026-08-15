---
id: 2637
topic: testing
source_issue: 11227
source_phase: plan
created_at: 2026-08-15T06:51:55.204466+00:00
status: active
corroborations: 1
---

# One-fake-per-file rule: no mixins in fake_github.py despite size

Keep all `FakeGitHub` code in `src/mockworld/fakes/fake_github.py` even when it exceeds 1600 lines. Do not extract a mixin or helper module.

**Why:** `FakeCoverageAuditorLoop` performs a non-inheriting AST scan that expects one fake class per file. A mixin breaks this scan, causing false positives in the coverage audit.
