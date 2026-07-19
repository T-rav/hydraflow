---
id: 0077
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:16:33.342771+00:00
status: superseded
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
superseded_by: 0078
---

# Coverage-delta gate is asymmetric: gaps block, clean defers to LLM

The coverage-delta gate overrides LLM verdict only in one direction: uncovered changed lines force FAIL regardless of LLM PASS; clean coverage does NOT override an LLM RETRY or FAIL.

- Uncovered lines found → FAIL (override)
- Clean coverage + LLM PASS → PASS
- Clean coverage + LLM RETRY → RETRY (defer to LLM)
- Gate unavailable → fall back to LLM verdict unchanged

**Why:** Symmetric override would allow a coverage pass to rescue an LLM RETRY, defeating the purpose of independent verification; the gate is a one-way ratchet against self-grading.
