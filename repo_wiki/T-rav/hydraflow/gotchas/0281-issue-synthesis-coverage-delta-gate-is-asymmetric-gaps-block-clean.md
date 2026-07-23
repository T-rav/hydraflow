---
id: 0281
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.037379+00:00
status: superseded
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
superseded_by: 0282
---

# Coverage-delta gate is asymmetric: gaps block, clean defers to LLM

The coverage-delta gate overrides LLM verdict only in one direction: uncovered changed lines force FAIL; clean coverage does NOT override an LLM RETRY or FAIL.

Example: Uncovered lines found → FAIL (override). Clean coverage + LLM RETRY → RETRY (defer to LLM).

**Why:** Symmetric override would allow a coverage pass to rescue an LLM RETRY, defeating the purpose of independent verification; the gate is a one-way ratchet against self-grading.
