# ADR-0023: Multi-Repo Architecture Wiring Pattern

**Status:** Proposed
**Date:** 2026-03-08
**Revised:** 2026-03-15
**Council revision:** 2026-03-15 — Addressed council feedback (scoped remaining
defect, clarified activation condition and registry construction site, reconciled
with ADR-0008 and ADR-0009)

## Context

HydraFlow's multi-repo support relies on `RepoRuntime` (bundles config, event bus,
state tracker, and orchestrator per repository) and `RepoRuntimeRegistry` (manages
multiple `RepoRuntime` instances by slug). Both abstractions exist in
`src/repo_runtime.py` and the dashboard routes in `src/dashboard_routes.py` already
accept an optional `registry` parameter with a `_resolve_runtime()` fallback that
transparently supports single-repo and multi-repo modes.

`HydraFlowDashboard` (in `src/dashboard.py`) already accepts an optional `registry`
parameter in its constructor and forwards it to `create_router()` (lines 51 and 127).
The multi-repo API endpoints (`/api/runtimes`, `/api/runtimes/{slug}`, etc.) are
fully implemented in the router and become operative when a registry is provided.

However, a single wiring gap remains in `server.py`:

- **`_run_with_dashboard()`** (lines 15–54) manually assembles bare `EventBus`,
  `EventLog`, and `StateTracker` instances instead of delegating to
  `RepoRuntime.create()`. The headless path (`_run_headless()`, lines 57–66)
  correctly uses `RepoRuntime.create()`. This means the dashboard startup path
  bypasses the runtime abstraction, duplicating the initialization sequence
  (event-log construction, log rotation, history loading, state-tracker creation)
  that `RepoRuntime` already encapsulates.

Note: the downstream plumbing is **already complete** — `HydraFlowDashboard`
accepts an optional `registry` parameter (line 51), forwards it to
`create_router()` (line 127), and `RouteContext.resolve_runtime()` handles the
`registry=None` fallback for single-repo backward compatibility. The only
remaining defect is the construction site in `_run_with_dashboard()` itself.

This gap was identified through memory issue #2266 and confirmed by code inspection.

## Decision

Refactor `_run_with_dashboard()` in `server.py` to delegate initialization to
`RepoRuntime.create()`, eliminating the asymmetry with `_run_headless()`:

1. **Replace bare-object construction with `RepoRuntime.create()`**: The dashboard
   path in `server.py` should create a `RepoRuntime` via `RepoRuntime.create(config)`
   and derive `event_bus`, `state`, and `orchestrator` from the resulting runtime
   object, eliminating the duplicate initialization sequence.
2. **Wrap the runtime in a `RepoRuntimeRegistry` for API consistency**: Construct a
   `RepoRuntimeRegistry`, register the single `RepoRuntime`, and pass the registry
   to `HydraFlowDashboard`. This activates the `/api/runtimes` introspection
   endpoints without requiring multi-repo configuration.
3. **Preserve single-repo backward compatibility**: The `_resolve_runtime()`
   fallback in `dashboard_routes.py` already handles the `registry=None` case, so
   single-repo deployments require no configuration change even if the registry is
   omitted.

### Multi-Repo Mode Activation

Under ADR-0009's process-per-repo model, there is no in-process "multi-repo mode"
toggle. The supervisor (defined in ADR-0008/ADR-0009) spawns one subprocess per
managed repository; each subprocess constructs exactly one `HydraFlowConfig` from
its environment and therefore creates exactly one `RepoRuntime`. The
`RepoRuntimeRegistry` within each subprocess holds at most one entry.

Multi-repo coordination happens at the **supervisor layer**, not within the
`_run_with_dashboard()` call:

- The supervisor spawns N subprocesses, each running its own dashboard on a
  dedicated port.
- The supervisor's unified dashboard proxies API requests to per-repo dashboards
  (ADR-0008) and aggregates cross-repo state via the TCP JSON protocol (ADR-0009).

Consequently, this ADR's refactoring does not introduce or require any new
configuration field to "enable" multi-repo mode. The activation condition is
architectural: the supervisor spawns multiple processes, each of which is
single-repo.

### Registry Construction Site and Ownership

The `RepoRuntimeRegistry` is constructed and owned by `_run_with_dashboard()` in
`server.py` — the same function that currently performs bare-object construction.
The ownership chain is:

1. `_run_with_dashboard()` creates `RepoRuntimeRegistry` and registers one
   `RepoRuntime` via `registry.register(config)`.
2. The registry is passed to `HydraFlowDashboard(registry=registry)`.
3. `HydraFlowDashboard` forwards it to `create_router(registry=registry)`.
4. Route handlers access the runtime via `RouteContext.resolve_runtime(slug)`.
5. On shutdown, `_run_with_dashboard()` calls `registry.stop_all()`.

The registry does **not** outlive the process and is not shared across processes.
Cross-process runtime management is the supervisor's responsibility (ADR-0008,
ADR-0009).

### Reconciliation with ADR-0008, ADR-0009, and ADR-0006

**ADR-0009 (Process-Per-Repo Model):** The supervisor spawns a separate subprocess
per managed repository, each with its own `asyncio` event loop and full service
registry. This ADR does **not** revive the in-process multi-repo coordination model
proposed in ADR-0006 (now superseded). Within a single subprocess, only one
repository is managed; the `RepoRuntimeRegistry` holds at most one entry and exists
for API consistency so the `/api/runtimes` endpoints work without special-casing
the single-repo case.

**ADR-0008 (Supervisor-Proxied Aggregation):** The supervisor exposes a unified
dashboard that proxies API requests to per-repo subprocesses. Each subprocess runs
its own dashboard instance via `_run_with_dashboard()`. This ADR's refactoring
operates entirely within a single subprocess — it unifies how that subprocess
initializes its runtime, but does not affect the supervisor's proxying or
aggregation behavior. The `/api/repos` endpoints (supervisor-level, ADR-0007)
remain distinct from the `/api/runtimes` endpoints (process-local).

**ADR-0006 (Superseded):** ADR-0006 proposed in-process `RepoRuntime` isolation
with multiple runtimes sharing a single event loop. ADR-0009 rejected that model
in favor of process-per-repo. This ADR's use of `RepoRuntimeRegistry` within a
subprocess is **not** a partial restoration of ADR-0006 — the registry holds
exactly one entry per process, and cross-repo coordination remains the supervisor's
responsibility via the TCP JSON protocol (ADR-0009 §Cross-Repo Coordination).

### `/api/runtimes` vs `/api/repos` Endpoint Naming

The `/api/runtimes` endpoints (in `dashboard_routes.py`) manage the **in-process
`RepoRuntime` lifecycle** — starting, stopping, and inspecting the runtime instance
within the current subprocess. The `/api/repos` endpoints (defined in ADR-0007)
manage the **supervisor's repo registry** — adding, removing, and listing repos
across the multi-repo deployment. They serve different architectural layers:
`/api/runtimes` is process-local, `/api/repos` is supervisor-level.

## Consequences

**Positive:**
- Single initialization path for both dashboard and headless modes, reducing
  divergence and maintenance burden.
- Runtime lifecycle (start, stop, log rotation) is consistently managed through
  `RepoRuntime` regardless of deployment mode.
- The dashboard path gains access to the full `RepoRuntime` API surface (e.g.,
  structured health checks, graceful shutdown) that was previously only available
  in headless mode.

**Negative / Trade-offs:**
- Refactoring `_run_with_dashboard()` touches the critical startup path; changes
  must be carefully tested to avoid regressions in single-repo mode.
- Multi-repo mode remains opt-in and undertested until integration tests cover
  the registry lifecycle (see ADR-0022).

## Alternatives considered

- **Keep bare-object construction in `_run_with_dashboard()`**: Avoids touching the
  startup path but permanently blocks consistent runtime management between dashboard
  and headless modes, and increases initialization code drift.
- **Replace `RepoRuntimeRegistry` with a service-locator pattern**: More flexible
  but adds indirection and makes dependency flow harder to trace. The explicit
  registry is simpler and sufficient for the current scale.
- **Move multi-repo wiring entirely into `orchestrator.py`**: Would centralize
  logic but conflates orchestration (loop scheduling) with runtime lifecycle
  management, violating the current separation of concerns.

## Open Questions

- **Integration test coverage for registry lifecycle**: Multi-repo mode remains
  opt-in and untested. Once the `_run_with_dashboard()` refactor lands, integration
  tests should cover `RepoRuntimeRegistry` registration, runtime start/stop, and
  the `/api/runtimes` endpoint surface under both single-registry and no-registry
  configurations. The integration test infrastructure patterns are established in
  ADR-0022 (Pipeline Integration Harness for Cross-Phase Testing).

## Related

- Source memory: #2266 — [Memory] Multi-repo architecture wiring pattern
- Decision issue: #2267 — [ADR] Draft decision from memory #2266
- ADR-0006: RepoRuntime Isolation Architecture (Superseded)
- ADR-0009: Multi-Repo Process-Per-Repo Model (Accepted)
- ADR-0007: Dashboard API Architecture for Multi-Repo Scoping (Accepted)
- ADR-0008: Multi-Repo Dashboard Architecture (Accepted)
- `src/repo_runtime.py` — `RepoRuntime` and `RepoRuntimeRegistry`
- `src/server.py` — `_run_with_dashboard()` and `_run_headless()` startup paths
- `src/dashboard.py` — `HydraFlowDashboard` (already accepts `registry` parameter)
- `src/dashboard_routes.py` — `create_router()` and `_resolve_runtime()`
