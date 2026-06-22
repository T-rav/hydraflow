---
id: 0050
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.213192+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Skill definition changes must update all 4 backend copies

HydraFlow skills are replicated across `.claude/commands/`, `.pi/skills/`, `.codex/skills/`, and `src/*.py`. Use a manual `SKILL_MARKERS` mapping (not regex introspection) to validate all copies contain matching output markers via substring search.

A single skill change can require updates across 3+ test fixture files.

**Why:** Missing updates in any one copy cause consistency test failures and silent runtime behavior divergence.
