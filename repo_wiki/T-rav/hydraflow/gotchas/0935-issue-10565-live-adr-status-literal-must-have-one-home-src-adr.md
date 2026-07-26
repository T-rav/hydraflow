---
id: 0935
topic: gotchas
source_issue: 10565
source_phase: plan
created_at: 2026-07-25T23:03:04.264264+00:00
status: active
corroborations: 1
---

# Live-ADR-status literal must have one home: src/adr_index.py

The ("Accepted", "Proposed") status tuple was copy-pasted across `ADRIndex.adrs_touching`, `adr_citation_resolve.py`, and `adr_drift.py`'s `bare_infra_citation_nudges` — the last copy silently omitted the filter, nudging Superseded/Deprecated ADRs (issue #10565, 5 false rows for ADR-0006/0013/0033/0036). Fix: define `LIVE_ADR_STATUSES` frozenset + `ADR.is_live` property (public, no leading `_`) in `src/adr_index.py` once, and route every caller through it.

**Why:** copy-pasted status filters silently diverge when one call site is added without the others being updated in lockstep.
