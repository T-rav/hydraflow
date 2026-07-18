---
id: 0174
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:52:49.032948+00:00
status: active
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
---

# Keep skill prompts in sync across all four backend locations

Skill prompt text lives in `src/`, `.claude/commands/`, `.pi/skills/`, and `.codex/skills/` — update all four locations when changing a prompt.

Example: editing `.claude/commands/hf.diff-sanity.md` requires mirroring the change to the other three locations.

**Why:** Missed updates cause the same skill to behave differently depending on which backend routes the request, producing inconsistent LLM behavior.
