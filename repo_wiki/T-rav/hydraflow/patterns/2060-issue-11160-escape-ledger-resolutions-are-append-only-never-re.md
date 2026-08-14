---
id: 2060
topic: patterns
source_issue: 11160
source_phase: plan
created_at: 2026-08-14T18:34:20.225990+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Escape ledger resolutions are append-only, never rewrites

`escape.resolve` writes a new superseding row; existing ledger rows are never mutated. `DISMISSED` on an aging row closes the link through the sidecar `dismissal_reasons()` path (#11148), not by editing ledger rows. `terminal_ids` suppresses all reasons for terminal verdicts.

**Why:** Append-only guarantees the audit trail; mutating rows would break historical traceability and double-count metrics.
