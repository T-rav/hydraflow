---
id: 0173
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:52:49.032624+00:00
status: active
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
---

# Preserve the `hf.` namespace prefix when renaming skill or command files

When renaming fixture or command files, keep the `hf.` or `hf-` prefix intact.

Example: rename `hf.audit-code.md` → `hf.audit-contracts.md`, not `audit-contracts.md`.

**Why:** Skill lookup strips the prefix at registration; dropping it makes the skill unreachable via `/hf.audit-contracts` and breaks namespace consistency.
