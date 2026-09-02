# Standard: the exception sensor

**Status:** active · **Id:** `exception_sensor` · **ADR:** [0146](../../adr/0146-sre-v1-the-exception-sensor.md)

A HydraFlow-format repo runs unattended. When something throws in production
there is no human tailing logs, so an unreported exception is not a quiet
failure — it is an invisible one. This standard says every such repo carries a
**sensor**: errors leave the process, become issues on the tracker, and re-enter
the factory as work it can triage and route.

The sensor is the SRE v1 agent. It does not diagnose and it does not fix. It
closes the loop from *the software failed* back to *the board knows*.

## What the sensor is

Two halves, and only the first is code in this repo:

| Half | Where it lives | What it does |
|---|---|---|
| Outbound | `src/observability/sentry_adapter.py` | Ships exceptions to an ingest endpoint |
| Inbound | `src/dashboard_routes/_issue_intake_routes.py` | One authenticated boundary that files the issue |

The inbound half is deliberately *not* a HydraFlow loop — but it is code, which
an earlier draft of ADR-0146 denied. Bugsink has **no** GitHub integration; its
only outbound path is a custom webhook. Because that webhook pushes, the
receiver is a route: no interval, no cursor, no backoff to keep correct.

## House flavour

The client is the **Sentry SDK**, so the target is any endpoint speaking the
Sentry ingest protocol. The house default is **Bugsink** — self-hosted, so error
payloads from a repo full of unreleased work stay on infrastructure the operator
owns. Pointing a repo at sentry.io instead is a DSN change, not a code change,
and this standard is satisfied either way.

## Rules

1. **The sensor is off without a target.** No DSN means the no-op adapter. Tests,
   CI and the air-gapped sandbox must never report.
2. **The operator can turn it off with a target configured.** A live checkout
   keeps its DSN in `.env`, so "unset the DSN" is an edit to a credentials file,
   not an off-switch. `HYDRAFLOW_SENTRY_DISABLED` overrides a present DSN, and
   the override direction is always OFF.
3. **Reporting never fails the work.** A sensor that raises into the code it
   observes has made reliability worse. Transport errors are swallowed.
4. **A broken target does not stop boot.** An unreachable endpoint degrades to
   the no-op; the factory keeps running blind rather than not at all.
5. **The sensor does not trace.** Errors only. Spans remain OTel's (ADR-0118 §1).
6. **Payloads carry no PII by default.** No local variables, no request bodies.
7. **The target is resolved from the environment.** DSN from the environment or
   the repo `.env`, never from code.
8. **Sensor issues declare their provenance.** They carry the sensor label
   (`bugsink` by default) so an operator reading the board can tell an observed
   failure from an authored finding.
9. **Triage routes them as incoming system exceptions.** A sensor issue that
   fails triage is a transient, not a bug report, and is auto-closed rather than
   parked for clarification that no author will ever supply.
10. **The intake refuses anonymous callers.** Filing an issue from outside a
    loop requires the operator credential the repo already has (ADR-0140), and
    a deployment not bound to loopback has no intake endpoint at all. A backend
    that cannot set an `Authorization` header — Bugsink's webhook config is a
    bare URL — gets a proxy in front of it, not a second credential path
    through the application.
11. **One issue per error group.** The backend re-fires the same group on
    regression and unmute; the receiver deduplicates on the group id rather than
    the rendered message, which varies within a group.

Rules 8-11 are why the label matters more than it looks: the label is what
makes an error a routable piece of work rather than a notification.

<!-- standard:enforced-by -->
- `tests/test_sentry_observability_adapter.py`
- `tests/test_triage_phase.py`
- `tests/test_issue_intake_boundary.py`
<!-- /standard:enforced-by -->

## Why a standard and not just an ADR

ADR-0118 removed the previous Sentry integration and left triage's consumer of
it in place. Nothing in `src/` wrote the marker that route keyed on for months;
the only writers repo-wide were the route's own tests, which hand-build the
string, so the tests stayed green while the route was unreachable in production.
An ADR records a decision at a point in time. A standard is re-checked on every
run, which is what that failure needed and did not have.
