---
id: 0047
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.321204+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Preserve the `hf.` namespace prefix when renaming skill or command files

When renaming fixture or command files, keep the `hf.` or `hf-` prefix intact.

Example: rename `hf.audit-code.md` → `hf.audit-contracts.md`, not `audit-contracts.md`.

**Why:** Skill lookup strips the prefix at registration; dropping it makes the skill unreachable via `/hf.audit-contracts` and breaks namespace consistency.
