---
id: 2382
topic: testing
source_issue: 11101
source_phase: plan
created_at: 2026-08-14T08:02:28.706621+00:00
status: active
corroborations: 1
---

# Disable loop sub-behaviors via config, not new kill-switches

Use config fields like `loop_auto_remediation_max_attempts=0` to disable specific loop sub-behaviors rather than adding new kill-switch env vars. Per ADR-0049, new kill-switches are reserved for new `BaseBackgroundLoop` subclasses or subprocess runners. **Why:** Avoids env var sprawl while allowing granular control, keeping `enabled_cb` as the sole lifecycle gate.
