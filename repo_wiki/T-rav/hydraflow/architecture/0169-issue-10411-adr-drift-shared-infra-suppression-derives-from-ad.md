---
id: 0169
topic: architecture
source_issue: 10411
source_phase: plan
created_at: 2026-07-24T05:57:06.014352+00:00
status: active
corroborations: 1
---

# ADR-drift shared-infra suppression derives from ADR-index fan-out, not a hand list

In `src/adr_drift.py`, a `src/` file that is **bare-cited** (no `:Symbol`) by ≥ `adr_drift_shared_infra_fanout_threshold` distinct live (Accepted/Proposed) ADRs is auto-unioned into `_SHARED_INFRA_MODULES` instead of requiring a manual add. Superseded/Deprecated ADRs don't count; a `:Symbol` citation still drifts regardless of fan-out. The threshold config field defaults to disabled (≤1) for direct callers of `compute_drift`/`compute_drift_by_adr`/`partition_fleet_drift` — only the auditor (`adr_touchpoint_auditor_loop.py`) passes the real value. **Why:** keeps back-compat for existing direct-call tests while letting genuinely high-churn shared files (e.g. `review_advisor.py`) self-suppress without editing a list every time.
