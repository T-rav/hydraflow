---
id: 2520
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.887108+00:00
status: active
corroborations: 1
supersedes: 2331
---

# Registry for live MockWorlds must be a WeakSet, not a list

The module-level live-world registry in `tests/scenarios/fakes/mock_world.py` is a `weakref.WeakSet`. Anything stronger (plain `list`, `set` of instances) would itself leak worlds across tests.

Example: when retrofitted cleanup must reach construction sites you cannot edit, register instances weakly and expose a public `close_open_worlds()` accessor; never import a `_`-prefixed helper cross-module.

**Why:** A hard reference would keep dead worlds alive and reproduce the exact leak the drain is meant to prevent.
