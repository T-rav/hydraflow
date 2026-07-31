---
id: 2057
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:54.053130+00:00
status: superseded
corroborations: 1
supersedes: 1930
superseded_by: 2186
---

# Registry for live MockWorlds must be a WeakSet, not a list

The module-level live-world registry in `tests/scenarios/fakes/mock_world.py` is a `weakref.WeakSet`. Anything stronger (plain `list`, `set` of instances) would itself leak worlds across tests.

Example: when retrofitted cleanup must reach construction sites you cannot edit, register instances weakly and expose a public `close_open_worlds()` accessor; never import a `_`-prefixed helper cross-module.

**Why:** A hard reference would keep dead worlds alive and reproduce the exact leak the drain is meant to prevent.
