---
id: 0384
topic: architecture
source_issue: 11326
source_phase: plan
created_at: 2026-08-16T09:29:42.917658+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Target staging and Skip-ADR for pure additive epic helpers

PR purely additive helper modules targeting epic slices with `--base staging` and include `Skip-ADR: [reason]` in the PR body.

Example: `Skip-ADR: additive helper under epic #11325; no architectural decision changed.`

**Why:** Keeps architectural decision records focused on behavior changes while ensuring staging integration for epic slices.
