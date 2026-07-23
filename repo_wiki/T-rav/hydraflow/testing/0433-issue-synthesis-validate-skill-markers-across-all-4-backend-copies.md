---
id: 0433
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:46:15.858392+00:00
status: superseded
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401,0402,0403,0404,0405,0406,0407,0408,0409,0410,0411
superseded_by: 0451
---

# Validate skill markers across all 4 backend copies

Validate marker presence via substring search across `.claude/commands/`, `.pi/skills/`, `.codex/skills/`, and `src/*.py`.

Example: Use a manual `SKILL_MARKERS` mapping, not regex introspection. A single skill addition or removal requires updating 3+ test files.

**Why:** Updating fewer than 4 copies silently diverges behavior across execution environments with no test failure to signal the gap.
