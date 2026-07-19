# ADR-0038: Multi-Repo Architecture Wiring Pattern

**Status:** Proposed
**Date:** 2026-03-08
**Revised:** 2026-03-15 · Context updated 2026-07 (wiring gap closed)

## Context

HydraFlow's multi-repo support relies on `RepoRuntime` (bundles config, event bus,
state tracker, and orchestrator per repository) and `RepoRuntimeRegistry` (manages
multiple `RepoRuntime` instances by slug). Both abstractions exist in
`src/repo_runtime.py` and the dashboard routes in `src/dashboard_routes/_routes.py` already
accept an optional `registry` parameter with a `_resolve_runtime()` fallback that
transparently supports single-repo and multi-repo modes.

`HydraFlowDashboard` (in `src/dashboard.py`) already accepts an optional `registry`
parameter in its constructor and forwards it to `create_router()`.
The multi-repo API endpoints (`/api/runtimes`, `/api/runtimes/{slug}`, etc.) are
fully implemented in the router and become operative when a registry is provided.

This wiring gap in `server.py` (originally identified via memory issue #2266) has
since been **closed** — the decision below is the shipped behavior:

- **`_run_with_dashboard()`** now constructs a `RepoRuntimeRegistry` and a host
  `RepoRuntime.from_shared(config, bus, state)`, deriving `event_bus`, `state`, and
  `orchestrator` from the runtime (`src/server.py`). This matches the `_run_headless()`
  path (`RepoRuntime.create()`) and eliminates the duplicate bare-object construction,
  so the dashboard path no longer bypasses the runtime abstraction.

The decision is realized in code; this ADR stays **Proposed** pending formal
ratification, but its Context now reflects the shipped state rather than the
original gap.

## Decision

Unify `_run_with_dashboard()` in `server.py` around `RepoRuntime.create()` to
eliminate the initialization asymmetry with `_run_headless()`:

1. **Unify `_run_with_dashboard()` around `RepoRuntime`**: The dashboard path in
   `server.py` should create a `RepoRuntime` via `RepoRuntime.create()` (or a
   `RepoRuntimeRegistry` for multi-repo configs) and derive `event_bus`, `state`,
   and `orchestrator` from it, eliminating the duplicate bare-object construction.
2. **Preserve single-repo backward compatibility**: The `_resolve_runtime()`
   fallback in `dashboard_routes.py` already handles the `registry=None` case, so
   single-repo deployments require no configuration change.

### Relationship to ADR-0009

ADR-0009 (Multi-Repo Process-Per-Repo Model) established the **process-per-repo** model as canonical: the supervisor
spawns a separate subprocess per managed repository, each with its own `asyncio`
event loop and full service registry. This ADR does **not** revive the in-process
multi-repo coordination model proposed in ADR-0006 (RepoRuntime Isolation Architecture; now superseded).

Within a single subprocess, the process-per-repo model from ADR-0009 (Multi-Repo Process-Per-Repo Model) means the subprocess
manages exactly one repository. The `RepoRuntimeRegistry` is designed to hold
multiple `RepoRuntime` instances by slug (its API exposes `register()`, `get()`,
`remove()`, and `all()`), but in this deployment model only one slug is ever
registered per process. The registry exists at this level for API consistency: the
`/api/runtimes` endpoints can introspect the local runtime without special-casing
the single-repo case. Cross-repo coordination remains the supervisor's responsibility
via subprocess isolation and the TCP JSON protocol, per ADR-0009 (Multi-Repo Process-Per-Repo Model).

### `/api/runtimes` vs `/api/repos` Endpoint Naming

The `/api/runtimes` endpoints (in `dashboard_routes.py`) manage the **in-process
`RepoRuntime` lifecycle** — starting, stopping, and inspecting the runtime instance
within the current subprocess. The `/api/repos` endpoints (defined in ADR-0007 — Dashboard API Architecture for Multi-Repo Scoping)
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
  the registry lifecycle (see ADR-0022 — Pipeline Integration Harness for Cross-Phase Testing).

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
- ADR-0006 (RepoRuntime Isolation Architecture) — Superseded
- ADR-0009 (Multi-Repo Process-Per-Repo Model) — Accepted
- ADR-0007 (Dashboard API Architecture for Multi-Repo Scoping) — Accepted
- ADR-0008 (Multi-Repo Dashboard Architecture) — Accepted
- `src/repo_runtime.py` — `RepoRuntime` and `RepoRuntimeRegistry`
- `src/server.py` — `_run_with_dashboard()` and `_run_headless()` startup paths
- `src/dashboard.py` — `HydraFlowDashboard` (already accepts `registry` parameter)
- `src/dashboard_routes/_routes.py:create_router` — `create_router()` and `_resolve_runtime()`
