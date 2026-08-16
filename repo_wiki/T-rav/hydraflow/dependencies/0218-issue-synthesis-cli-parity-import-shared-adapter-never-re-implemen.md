---
id: 0218
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T04:51:57.147438+00:00
status: active
corroborations: 1
supersedes: 0203
---

# CLI parity: import shared adapter, never re-implement

When adding a CLI subcommand that mirrors an HTTP endpoint, import the same adapter and validation gate the endpoint uses — do not re-implement the logic in the CLI.

Example: `scripts/hydraflow_healthcheck/__main__.py` `fix` subcommand imports `is_mechanically_fixable` from `fixability.py` by public name (no `_`-prefix). Non-mechanical check: CLI prints the check's `source` citation and exits nonzero without invoking the adapter.

**Why:** Duplicated logic drifts; the CLI and API must reject the same violations identically.
