---
id: 0169
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.579421+00:00
status: superseded
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
superseded_by: 0183
---

# Skill definition changes must update all 4 backend copies

HydraFlow skills are replicated across `.claude/commands/`, `.pi/skills/`, `.codex/skills/`, and `src/*.py`. Use a manual `SKILL_MARKERS` mapping (not regex introspection) to validate all copies contain matching output markers via substring search. A single skill change can require updates across 3+ test fixture files.

**Why:** Missing updates in any one copy cause consistency test failures and silent runtime behavior divergence.
