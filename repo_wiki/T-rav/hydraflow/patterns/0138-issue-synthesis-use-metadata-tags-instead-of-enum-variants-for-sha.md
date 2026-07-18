---
id: 0138
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:34:46.621314+00:00
status: active
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
---

# Use metadata tags instead of enum variants for shared-bank categorization

Tag items with metadata (e.g., `{"source": "adr_council"}`) rather than adding new enum variants for each category.

Example: `retain(bank=Bank.LEARNINGS, metadata={"source": "adr_council"})` — no new enum variant needed.

**Why:** Enum variants require syncing type checks, prompts, and display order across the codebase; a metadata tag adds a category with no schema change.
