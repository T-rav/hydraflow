---
id: 0023
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.829989+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# Skill definition changes must update all 4 backend copies

HydraFlow skills are replicated across `.claude/commands/`, `.pi/skills/`, `.codex/skills/`, and `src/*.py`. Use a manual `SKILL_MARKERS` mapping (not regex introspection) to validate that all copies contain matching output markers via substring search.

A single skill change can require updates across 3+ test fixture files.

**Why:** Missing updates in any one copy cause consistency test failures and silent runtime behavior divergence.
