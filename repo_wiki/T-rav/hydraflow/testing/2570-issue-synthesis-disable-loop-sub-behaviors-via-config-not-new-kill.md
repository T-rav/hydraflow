---
id: 2570
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.647680+00:00
status: active
corroborations: 1
supersedes: 2382
---

# Disable loop sub-behaviors via config, not new kill-switches

Use config fields like `loop_auto_remediation_max_attempts=0` to disable specific loop sub-behaviors rather than adding new kill-switch env vars. Per ADR-0049, new kill-switches are reserved for new `BaseBackgroundLoop` subclasses or subprocess runners.

**Why:** Avoids env var sprawl while allowing granular control, keeping `enabled_cb` as the sole lifecycle gate.
