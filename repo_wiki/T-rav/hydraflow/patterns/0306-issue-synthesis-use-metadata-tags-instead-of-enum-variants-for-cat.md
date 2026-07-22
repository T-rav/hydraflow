---
id: 0306
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:37:54.866773+00:00
status: superseded
corroborations: 1
supersedes: 0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294,0295,0296,0297,0298,0299,0300,0301
superseded_by: 0344
---

# Use metadata tags instead of enum variants for categorization

Tag items with metadata (e.g., `{"source": "adr_council"}`) rather than adding new enum variants for each category.

Example: `retain(bank=Bank.LEARNINGS, metadata={"source": "adr_council"})` — no new enum variant needed.

**Why:** Enum variants require syncing type checks, prompts, and display order across the codebase; a metadata tag adds a category with no schema change.
