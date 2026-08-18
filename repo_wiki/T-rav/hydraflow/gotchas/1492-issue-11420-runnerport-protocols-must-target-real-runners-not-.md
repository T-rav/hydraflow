---
id: 1492
topic: gotchas
source_issue: 11420
source_phase: plan
created_at: 2026-08-18T03:48:25.160832+00:00
status: active
corroborations: 1
---

# RunnerPort Protocols must target real runners, not fakes

The `*RunnerPort` Protocols in `tests/scenarios/ports/llm_port.py` must mirror the real `TriageRunner`/`PlannerRunner`/`AgentRunner`/`ReviewRunner` signatures — real param names, correct `POSITIONAL_OR_KEYWORD` vs `KEYWORD_ONLY` kinds, and all methods including `fix_review_findings`.

**Why:** Pairing fake↔fake in the conformance sweep validates drift instead of catching it — a fake that renames a param or narrows to keyword-only passes against itself but fails against the real runner.
