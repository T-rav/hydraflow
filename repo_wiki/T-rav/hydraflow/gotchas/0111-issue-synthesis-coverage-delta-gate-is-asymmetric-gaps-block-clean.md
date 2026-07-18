---
id: 0111
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T18:33:11.851674+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Coverage-delta gate is asymmetric: gaps block, clean defers to LLM

The coverage-delta gate overrides LLM verdict only in one direction: uncovered changed lines force FAIL regardless of LLM PASS; clean coverage does NOT override an LLM RETRY or FAIL.

- Uncovered lines found → FAIL (override)
- Clean coverage + LLM PASS → PASS
- Clean coverage + LLM RETRY → RETRY (defer to LLM)
- Gate unavailable → fall back to LLM verdict unchanged

**Why:** Symmetric override would allow a coverage pass to rescue an LLM RETRY, defeating the purpose of independent verification; the gate is a one-way ratchet against self-grading.
