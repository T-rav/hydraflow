---
id: 0109
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.084087+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Skill definition changes must update all 4 backend copies

HydraFlow skills are replicated across `.claude/commands/`, `.pi/skills/`, `.codex/skills/`, and `src/*.py`. Use a manual `SKILL_MARKERS` mapping (not regex introspection) to validate all copies contain matching output markers via substring search. A single skill change can require updates across 3+ test fixture files.

**Why:** Missing updates in any one copy cause consistency test failures and silent runtime behavior divergence.
