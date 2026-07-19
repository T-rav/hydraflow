---
id: 0355
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:25:25.499495+00:00
status: superseded
corroborations: 1
supersedes: 0295,0296,0297,0298,0299,0300,0301,0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333
superseded_by: 0373
---

# Validate skill markers across all 4 backend copies

Validate marker presence via substring search across `.claude/commands/`, `.pi/skills/`, `.codex/skills/`, and `src/*.py`.

Example: Use a manual `SKILL_MARKERS` mapping, not regex introspection. A single skill addition or removal requires updating 3+ test files.

**Why:** Updating fewer than 4 copies silently diverges behavior across execution environments with no test failure to signal the gap.
