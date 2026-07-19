---
id: 0247
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.805324+00:00
status: active
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
---

# Coverage-delta gate is asymmetric: gaps block, clean defers to LLM

The coverage-delta gate overrides LLM verdict only in one direction: uncovered changed lines force FAIL; clean coverage does NOT override an LLM RETRY or FAIL.

Example: Uncovered lines found → FAIL (override). Clean coverage + LLM RETRY → RETRY (defer to LLM).

**Why:** Symmetric override would allow a coverage pass to rescue an LLM RETRY, defeating the purpose of independent verification; the gate is a one-way ratchet against self-grading.
