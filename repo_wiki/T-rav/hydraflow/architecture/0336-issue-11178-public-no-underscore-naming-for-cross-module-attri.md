---
id: 0336
topic: architecture
source_issue: 11178
source_phase: plan
created_at: 2026-08-14T23:03:00.703671+00:00
status: stale
corroborations: 1
stale_reason: source issue #11178 closed
---

# Public (no underscore) naming for cross-module attribution helpers

Functions in `src/escape/attribution.py` imported by `src/escape/auto_diagnose.py` must omit the leading underscore — e.g., `regression_pins_added` not `_regression_pins_added`.

- `adds_regression_pin` stays public for the same reason (used by `escape/detect.py:106`).
- Internal-only helpers keep the underscore.

**Why:** The underscore is the repo's module-private signal; cross-module imports of underscored names violate the convention and confuse future readers.
