# ADR-0091: Fold Epic Completion Sweep into Epic Monitor

Date: 2026-05-22

## Status

Superseded by ADR-0105 (Autonomous Convergence via Decomposition)

> **Superseded by [ADR-0105](0105-autonomous-convergence-via-decomposition.md).**
> ADR-0105 re-split epic completion back out of the monitor tick. Completion is
> now **event-driven** (`EpicManager._try_auto_close` / `_propagate_epic_close`,
> fired on child completion) plus a separate **`EpicSweeperLoop`**
> (`EpicSweeperLoop._try_sweep_epic`, ADR-0081); `EpicMonitorLoop._do_work` no
> longer performs a completion sweep (`sweep_completed_epics` was removed). The
> historical content below is retained unchanged.

## Enforcement

**Enforcement:** decision-of-record

## Context

Epic lifecycle maintenance had two caretaker loops: one for stale detection and
progress refresh, and one for periodic auto-close checks. The close path was
small but had its own worker name, interval config, UI entry, service registry
wiring, and tests. That split made epic lifecycle behavior harder to reason
about and required operators to configure two loops for one lifecycle concern.

## Decision

`EpicMonitorLoop` owns the periodic epic lifecycle tick. It calls
`EpicManager.check_stale_epics()`, `EpicManager.sweep_completed_epics()`, and
`EpicManager.refresh_cache()` in one cycle. The completion sweep still supports
formal `EpicState.child_issues` and checkbox-style body references, and it keeps
the previous auto-close behavior: verify every child issue is closed, check
remaining checkboxes, post an auto-close comment, optionally add the fixed
label, close the epic, and report sweep stats.

The standalone completion-sweep worker and its config/UI surface are removed.

## Consequences

- Operators configure one epic lifecycle worker interval and kill switch.
- Completion sweep state/cache invalidation lives inside `EpicManager`.
- The monitor tick can perform GitHub mutations when completed epics are found.
- Tests for checkbox-style epic refs move to monitor/manager coverage.
