---
id: 0048
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.321427+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Keep skill prompts in sync across all four backend locations

Skill prompt text lives in `src/`, `.claude/commands/`, `.pi/skills/`, and `.codex/skills/` — update all four locations when changing a prompt.

Example: editing `.claude/commands/hf.diff-sanity.md` requires mirroring the change to the other three locations.

**Why:** Missed updates cause the same skill to behave differently depending on which backend routes the request, producing inconsistent LLM behavior.
