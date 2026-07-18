---
id: 0131
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:07:53.477671+00:00
status: active
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
---

# Preserve the `hf.` namespace prefix when renaming skill or command files

When renaming fixture or command files, keep the `hf.` or `hf-` prefix intact.

Example: rename `hf.audit-code.md` → `hf.audit-contracts.md`, not `audit-contracts.md`.

**Why:** Skill lookup strips the prefix at registration; dropping it makes the skill unreachable via `/hf.audit-contracts` and breaks namespace consistency.
