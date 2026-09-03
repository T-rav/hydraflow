---
id: 0445
topic: architecture
source_issue: 12058
source_phase: plan
created_at: 2026-09-02T22:01:19.186922+00:00
status: active
corroborations: 1
---

# Promoted/wontfix verdict rules for memory backlog

Pending entries that return to `pending` must release their dedup keys, or re-filing resumes. Promoted entries must cite a real artifact in `promoted_in` (ADR, hook, ratchet, rule). Wontfix entries must carry `wontfix_reason`. Test reversion guards (`promoted_in`, `is_bot_close`, 3-strikes bound) negative-case-first.

Example: `feedback-ratchet-pattern` enforced by ADR-0104; mark `promoted_in: docs/adr/0104-*.md`.

**Why:** Violated verdicts cause the loop to spam the board with re-filed settled entries.
