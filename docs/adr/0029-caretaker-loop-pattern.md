# ADR-0029: Caretaker Background Loop Pattern

## Status

Accepted (CodeGroomingLoop removed in ADR-0065 — the pattern itself remains in use by the other three caretaker loops listed below)

**Enforcement:** enforced

**Enforced by:** pytest:tests/test_caretaker_loop_wiring.py

## Context

HydraFlow needed proactive maintenance workers — auto-closing stale issues, monitoring CI health, patching security vulnerabilities, and (originally) running code audits. These are "caretaker" concerns: low-priority, periodic, zero-token, and independent of the main pipeline.

Four loops were introduced under this pattern: `StaleIssueGCLoop`, `CIMonitorLoop`, `SecurityPatchLoop`, and `CodeGroomingLoop`. The fourth — `CodeGroomingLoop` — has since been retired (see ADR-0065); the pattern remains in use by the other three.

## Decision

### Pattern: Extend `BaseBackgroundLoop` with `DedupStore`

All active loops follow the same pattern:

1. **Extend `BaseBackgroundLoop`** — provides the polling loop, enabled/disabled check, error handling, status publishing, and interval management
2. **Constructor takes `(config, pr_manager, deps: LoopDeps)`** — minimal dependencies, no direct state coupling
3. **`_do_work()` returns a stats dict** — consumed by the `BACKGROUND_WORKER_STATUS` event for dashboard display
4. **`DedupStore` for idempotency** — `SecurityPatchLoop` tracks processed items to avoid filing duplicate issues across restarts (the retired `CodeGroomingLoop` used the same mechanism)

### Wiring: ServiceRegistry + BGWorkerManager

Each loop is:
1. Instantiated in `build_services()` with `# noqa: F841` to suppress unused-variable lint
2. Added as a field to the `ServiceRegistry` dataclass
3. Registered in the orchestrator's `bg_loop_registry` dict by worker name
4. Listed in `BACKGROUND_WORKERS` in `ui/src/constants.js` for dashboard display

### Config: Interval + threshold fields with env var overrides

Each loop gets a config field with `ge`/`le` validation and an `_ENV_INT_OVERRIDES` entry:
- `stale_issue_gc_interval` (300-86400, default 3600)
- `ci_monitor_interval` (60-86400, default 300)
- `security_patch_interval` (300-86400, default 3600)

(The retired `code_grooming_interval` knob followed the same convention; see ADR-0065.)

Intervals are also in `_INTERVAL_BOUNDS` in `_common.py` for dashboard API editing.

### CaretakerPanel: Dedicated dashboard tab

A dedicated "Caretaker" tab shows all maintenance workers with status dots, last-run times, enable/disable toggles, and manual trigger buttons. Worker definitions are derived from `BACKGROUND_WORKERS` constant (DRY).

## Consequences

- Adding a new caretaker loop requires: 1 file, 1 test file, 3 wiring points (service_registry, orchestrator, constants.js), 1 config field
- All caretaker loops are enabled by default — operators can disable via dashboard or env vars
- `CIMonitorLoop` persists its open-issue tracker via a GitHub label (`hydraflow-ci-failure`) to survive restarts
- `DedupStore` files persist across restarts, preventing duplicate issue creation
