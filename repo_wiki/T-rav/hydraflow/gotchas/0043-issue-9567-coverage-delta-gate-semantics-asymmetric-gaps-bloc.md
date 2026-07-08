---
id: 0043
topic: gotchas
source_issue: 9567
source_phase: review
created_at: 2026-06-20T09:15:00.395676+00:00
status: active
corroborations: 1
---

# Coverage-delta gate semantics: asymmetric — gaps block, clean defers

The coverage-delta gate overrides LLM verdict only in one direction: uncovered changed lines force a FAIL regardless of LLM PASS; a clean coverage result does NOT override an LLM RETRY or FAIL.

- Uncovered lines found → FAIL (override)
- Clean coverage + LLM PASS → PASS
- Clean coverage + LLM RETRY → RETRY (defer to LLM)
- Gate unavailable → fall back to LLM verdict unchanged

**Why:** Symmetric override would allow a coverage pass to rescue an LLM RETRY, defeating the purpose of the independent verification; the gate is a one-way ratchet against self-grading, not a replacement for the LLM verdict.
