---
id: 4092
topic: patterns
source_issue: 12058
source_phase: plan
created_at: 2026-09-02T22:01:19.186916+00:00
status: active
corroborations: 1
---

# Digest-change pre-mortem: triage ships with fixes

Changing overflow-line format invalidates old `memory_backlog:summary:*` dedup keys, so the batch re-enters the overflow path. Triage (P5) must land in the same PR as code fixes (P1/P2), and every triaged entry must carry a verdict preventing re-filing.

Example: Set `promoted_in: <artifact>` or `wontfix_reason: <reason>` for all entries; never leave rows pending with spent keys.

**Why:** A triage-only PR allows old keys to survive, filing a second summary alongside the first.
