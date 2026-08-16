---
id: 0190
topic: dependencies
source_issue: 11277
source_phase: plan
created_at: 2026-08-15T21:08:01.026740+00:00
status: superseded
corroborations: 1
superseded_by: 0203
---

# CLI parity: import shared adapter, never re-implement

When adding a CLI subcommand that mirrors an HTTP endpoint (e.g. `make health-fix` vs `/api/rails-health/fix`), import the SAME adapter and validation gate (`is_mechanically_fixable` from `fixability.py`) the endpoint uses. Do not re-implement the logic in the CLI.
- `scripts/hydraflow_healthcheck/__main__.py` `fix` subcommand imports the adapter by its public name (no `_`-prefix)
- Non-mechanical check: CLI prints the check's `source` citation and exits nonzero without invoking the adapter
**Why:** Duplicated logic drifts; the CLI and API must reject the same violations identically.
