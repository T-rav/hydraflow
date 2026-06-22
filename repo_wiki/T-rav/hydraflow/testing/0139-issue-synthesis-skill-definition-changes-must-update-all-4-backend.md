---
id: 0139
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.436537+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Skill definition changes must update all 4 backend copies

HydraFlow skills are replicated across `.claude/commands/`, `.pi/skills/`, `.codex/skills/`, and `src/*.py`. Use a manual `SKILL_MARKERS` mapping (not regex introspection) to validate all copies contain matching output markers via substring search. A single skill change can require updates across 3+ test fixture files.

**Why:** Missing updates in any one copy cause consistency test failures and silent runtime behavior divergence.
