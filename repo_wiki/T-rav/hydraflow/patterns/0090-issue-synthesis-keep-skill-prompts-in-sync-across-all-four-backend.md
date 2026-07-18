---
id: 0090
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:15:44.541240+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Keep skill prompts in sync across all four backend locations

Skill prompt text lives in `src/`, `.claude/commands/`, `.pi/skills/`, and `.codex/skills/` — update all four locations when changing a prompt.

Example: editing `.claude/commands/hf.diff-sanity.md` requires mirroring the change to the other three locations.

**Why:** Missed updates cause the same skill to behave differently depending on which backend routes the request, producing inconsistent LLM behavior.
