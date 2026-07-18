---
id: 0054
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T14:57:29.416496+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Use metadata tags instead of enum variants for shared-bank categorization

Tag items with metadata (e.g., `{"source": "adr_council"}`) rather than adding new enum variants for each category.

Example: `retain(bank=Bank.LEARNINGS, metadata={"source": "adr_council"})` — no new enum variant needed.

**Why:** Enum variants require syncing type checks, prompts, and display order across the codebase; a metadata tag adds a category with no schema change.
