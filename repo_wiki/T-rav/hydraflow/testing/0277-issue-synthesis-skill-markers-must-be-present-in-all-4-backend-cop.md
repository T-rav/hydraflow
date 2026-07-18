---
id: 0277
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:48:26.491241+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Skill markers must be present in all 4 backend copies

HydraFlow skills replicate across `.claude/commands/`, `.pi/skills/`, `.codex/skills/`, and `src/*.py`. Validate marker presence via substring search across all 4 locations.

Use a manual `SKILL_MARKERS` mapping, not regex introspection. A single skill addition or removal requires updating 3+ test files.

**Why:** Updating fewer than 4 copies silently diverges behavior across execution environments with no test failure to signal the gap.
