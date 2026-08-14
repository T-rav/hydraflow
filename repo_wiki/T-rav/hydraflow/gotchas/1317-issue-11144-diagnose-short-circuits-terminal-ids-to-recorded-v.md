---
id: 1317
topic: gotchas
source_issue: 11144
source_phase: plan
created_at: 2026-08-14T14:39:13.298126+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# diagnose() short-circuits terminal ids to recorded verdict

Use `EscapeDiagnosisLedger.recorded_verdict()` (last-row-wins) as the authority for terminal escape ids. `diagnose()` must return it directly — no re-act, no git/`gh` reads, no evidence gathering.

- A repeat diagnose of a dismissed/resolved escape performs no issue-label read; the terminal short-circuit precedes `_gather`.
- A sidecar row with an unrecognised verdict string diagnoses as `INCONCLUSIVE` (fail-safe to human).

**Why:** Re-acting on terminal rows files duplicate human issues and mutates ledger state that should be frozen.
