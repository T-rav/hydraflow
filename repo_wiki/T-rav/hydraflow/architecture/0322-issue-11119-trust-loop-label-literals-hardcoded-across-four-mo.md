---
id: 0322
topic: architecture
source_issue: 11119
source_phase: plan
created_at: 2026-08-14T12:19:29.537616+00:00
status: active
corroborations: 1
---

# Trust-loop label literals hardcoded across four modules

Use config-driven label fields, not string literals, for any label read by more than one module. In T-rav/hydraflow, `hitl-escalation` / `trust-loop-anomaly` appear as literals in `src/trust_fleet_sanity_loop.py`, `src/dashboard_routes/_trust_routes.py`, and `src/prep.py`.

- `HydraFlowConfig` now exposes `trust_loop_anomaly_label` and `trust_loop_anomaly_confirmed_label`
- Only the sanity loop call sites were converted in #11119
- Dashboard route still greps the literal, so renaming via config silently blanks `/api/trust/fleet` `anomalies_recent`

All readers must resolve from `HydraFlowConfig`.

**Why:** Config-tunable labels that remain hardcoded in one reader create silent dead-ends when the value changes.
