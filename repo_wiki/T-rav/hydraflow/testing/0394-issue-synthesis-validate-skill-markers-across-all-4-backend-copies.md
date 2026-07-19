---
id: 0394
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:49:52.738834+00:00
status: active
corroborations: 1
supersedes: 0334,0335,0336,0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347,0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369,0370,0371,0372
---

# Validate skill markers across all 4 backend copies

Validate marker presence via substring search across `.claude/commands/`, `.pi/skills/`, `.codex/skills/`, and `src/*.py`.

Example: Use a manual `SKILL_MARKERS` mapping, not regex introspection. A single skill addition or removal requires updating 3+ test files.

**Why:** Updating fewer than 4 copies silently diverges behavior across execution environments with no test failure to signal the gap.
