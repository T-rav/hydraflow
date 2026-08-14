---
id: 1743
topic: patterns
source_issue: 11117
source_phase: plan
created_at: 2026-08-14T10:58:30.492166+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Invoke telemetry-only alert checks from no_cases early-return branch

The `no_cases` early-return path in `_consume_efficiency_telemetry` skips the main efficiency loop but must still call `_alert_zero_usage_sources()`. Alerts that depend only on telemetry totals — not corpus cases — must be wired into this branch explicitly, alongside the main branch.
Example: `_alert_zero_usage_sources()` is invoked from both `_consume_efficiency_telemetry` and the `no_cases` early-return branch.
**Why:** A source can burn all spawns anomalously while the corpus produces zero cases, leaving the alert path dead if only wired into the main branch.
