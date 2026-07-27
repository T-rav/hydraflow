---
id: 1151
topic: gotchas
source_issue: 10651
source_phase: plan
created_at: 2026-07-26T15:47:34.663714+00:00
status: active
corroborations: 1
---

# Escalate to HITL issue after 3 failed filings, then abandon fingerprint

After `_MAX_SURFACE_ATTEMPTS` (3) failed filings for a fingerprint, file exactly one escalation issue with the HITL label and `escape-ledger`, naming the escape id and reason. Then abandon the fingerprint and mark it spent so no further attempts or escalations occur.

- `src/escape_ledger_loop.py`: `_surface_findings` checks the attempt count from the sidecar; at the cap it files the escalation issue once.
- Escalation is deduped by fingerprint — restarts must not refile.

**Why:** Unbounded silent retry of a permanently-unfileable pair wastes filing budget forever; without dedup, restarts would file duplicate escalation issues.
