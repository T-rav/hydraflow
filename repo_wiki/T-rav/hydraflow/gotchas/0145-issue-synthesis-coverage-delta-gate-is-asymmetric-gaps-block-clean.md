---
id: 0145
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:37:07.472050+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Coverage-delta gate is asymmetric: gaps block, clean defers to LLM

The coverage-delta gate overrides LLM verdict only in one direction: uncovered changed lines force FAIL regardless of LLM PASS; clean coverage does NOT override an LLM RETRY or FAIL.

- Uncovered lines found → FAIL (override)
- Clean coverage + LLM PASS → PASS; clean + LLM RETRY → RETRY (defer to LLM)
- Gate unavailable → fall back to LLM verdict unchanged

**Why:** Symmetric override would allow a coverage pass to rescue an LLM RETRY, defeating the purpose of independent verification; the gate is a one-way ratchet against self-grading.
