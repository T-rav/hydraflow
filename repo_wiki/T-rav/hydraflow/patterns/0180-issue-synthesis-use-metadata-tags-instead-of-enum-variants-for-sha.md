---
id: 0180
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:22:06.629788+00:00
status: active
corroborations: 1
supersedes: 0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175
---

# Use metadata tags instead of enum variants for shared-bank categorization

Tag items with metadata (e.g., `{"source": "adr_council"}`) rather than adding new enum variants for each category.

Example: `retain(bank=Bank.LEARNINGS, metadata={"source": "adr_council"})` — no new enum variant needed.

**Why:** Enum variants require syncing type checks, prompts, and display order across the codebase; a metadata tag adds a category with no schema change.
