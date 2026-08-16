---
id: 0364
topic: architecture
source_issue: 11281
source_phase: plan
created_at: 2026-08-16T01:24:32.227592+00:00
status: active
corroborations: 1
---

# Pure engines import config constants by public name only

`branch_gc_scan` is a pure engine. When it needs shared config values (e.g. `AUTO_AGENT_BRANCH_PREFIX` from `config`), import by public name — no `_`-prefixed cross-module imports.

Match the precedent set by `workspace_gc_loop`, which imports values-only config constants the same way.

**Why:** Pure engines must stay testable in isolation. Values-only imports preserve this property while allowing shared constants to drive behavior consistently across modules. A `_`-prefixed import would signal private coupling that doesn't exist.
