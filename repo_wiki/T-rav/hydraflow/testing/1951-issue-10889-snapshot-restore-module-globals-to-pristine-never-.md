---
id: 1951
topic: testing
source_issue: 10889
source_phase: plan
created_at: 2026-07-31T10:36:59.292288+00:00
status: active
corroborations: 1
---

# Snapshot/restore module globals to pristine, never clear

Test reset fixtures must snapshot and restore `(module, attr)` pairs to their import-time value, not wipe them. The `_restore_phase_utils_memory_seams` precedent restores rather than clears; the table-driven autouse fixture for `execution._default_runner`, `adr_utils._assigned_adr_numbers`, `telemetry.otel._PROVIDER`, and others follows suit.

**Why:** Clearing destroys import-time defaults that later tests depend on being present, producing spurious `None`-where-a-default-should-be failures.
