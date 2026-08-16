---
id: 0203
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T02:51:17.453614+00:00
status: superseded
corroborations: 1
supersedes: 0190
superseded_by: 0218
---

# CLI parity: import shared adapter, never re-implement

When adding a CLI subcommand that mirrors an HTTP endpoint, import the same adapter and validation gate the endpoint uses — do not re-implement the logic in the CLI.

Example: `scripts/hydraflow_healthcheck/__main__.py` `fix` subcommand imports `is_mechanically_fixable` from `fixability.py` by public name (no `_`-prefix). Non-mechanical check: CLI prints the check's `source` citation and exits nonzero without invoking the adapter.

**Why:** Duplicated logic drifts; the CLI and API must reject the same violations identically.
