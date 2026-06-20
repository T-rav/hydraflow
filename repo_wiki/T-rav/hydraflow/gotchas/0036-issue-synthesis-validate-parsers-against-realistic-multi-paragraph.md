---
id: 0036
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.697465+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Validate parsers against realistic multi-paragraph agent output

Write parser tests against realistic multi-paragraph transcripts — prose interspersed with structured markers — not bare marker strings.

Example: test input should resemble real `claude` CLI output; assert on structured markers, not prose wording, so transcript rewords don't break tests.

**Why:** Bare-marker tests pass even when the parser fails on the surrounding prose context present in real output, hiding real format regressions.
