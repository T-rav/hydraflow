---
id: 0012
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.313684+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Use metadata tags instead of enum variants for shared-bank categorization

Tag items with metadata (e.g., `{"source": "adr_council"}`) rather than adding new enum variants for each category.

Example: `retain(bank=Bank.LEARNINGS, metadata={"source": "adr_council"})` — no new enum variant needed.

**Why:** Enum variants require syncing type checks, prompts, and display order across the codebase; a metadata tag adds a category with no schema change.
