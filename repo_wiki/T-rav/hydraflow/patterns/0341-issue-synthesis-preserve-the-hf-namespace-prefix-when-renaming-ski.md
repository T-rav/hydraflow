---
id: 0341
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:37:54.884017+00:00
status: superseded
corroborations: 1
supersedes: 0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294,0295,0296,0297,0298,0299,0300,0301
superseded_by: 0344
---

# Preserve the `hf.` namespace prefix when renaming skill files

When renaming fixture or command files, keep the `hf.` or `hf-` prefix intact.

Example: Rename `hf.audit-code.md` → `hf.audit-contracts.md`, not `audit-contracts.md`.

**Why:** Skill lookup strips the prefix at registration; dropping it makes the skill unreachable via `/hf.audit-contracts` and breaks namespace consistency.
