---
id: 0213
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.162132+00:00
status: superseded
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
superseded_by: 0214
---

# Coverage-delta gate is asymmetric: gaps block, clean defers to LLM

The coverage-delta gate overrides LLM verdict only in one direction: uncovered changed lines force FAIL; clean coverage does NOT override an LLM RETRY or FAIL.

Example: Uncovered lines found → FAIL (override). Clean coverage + LLM RETRY → RETRY (defer to LLM).

**Why:** Symmetric override would allow a coverage pass to rescue an LLM RETRY, defeating the purpose of independent verification; the gate is a one-way ratchet against self-grading.
