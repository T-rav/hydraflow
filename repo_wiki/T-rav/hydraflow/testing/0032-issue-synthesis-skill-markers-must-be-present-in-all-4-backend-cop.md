---
id: 0032
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.411504+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Skill markers must be present in all 4 backend copies

HydraFlow skills replicate across `.claude/commands/`, `.pi/skills/`, `.codex/skills/`, and `src/*.py`. Validate marker presence via substring search across all 4 locations. A single skill addition or removal requires updating 3+ test files.

**Why:** Updating fewer than 4 copies silently diverges behavior across execution environments with no test failure to signal the gap.
