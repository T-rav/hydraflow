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
| Outbound | `src/observability/sentry_adapter.py` | Ships exceptions to an ingest endpoint. Installed per process at each entrypoint (`server.main`, `hydraflow_gateway.__main__.main`), and injected as an `ObservabilityPort` where a caller takes one. |
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

## Configuring an application

[`RUNBOOK.md`](RUNBOOK.md), stamped into every HydraFlow-format repo alongside
this file: SDK init for Python and Node, the check at each step, how Bugsink's
grouping differs from Sentry's, and a symptom table for "we get no error
issues". This file states the rules; the runbook states how to satisfy them.

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
11. **The caller does not choose its own provenance.** Each exposed lane pins
    its `source` at the proxy. Triage treats sensor issues differently, so a
    report able to label itself as a system exception is a report that can get
    itself auto-closed.
12. **One issue per error group.** The backend re-fires the same group on
    regression and unmute; the receiver deduplicates on the group id rather than
    the rendered message, which varies within a group.

13. **Every unattended process installs the sensor at its entrypoint.** Not at
    the composition root. A process that dies during config load or factory
    boot never reaches its composition root, and "the factory will not start"
    is the failure an operator most needs on the board. `install_process_sensor`
    is the entrypoint half; `build_observability_adapter` remains the injected
    port for code that takes one.
14. **The SDK is initialised once per process.** `sentry_sdk.init` replaces the
    global client wholesale, so a second call silently discards the first —
    including its component tag. `init_sentry_sdk` is the only caller.
15. **Every event names the process it came from.** One backend project
    receives from the server and the gateway, which are separate deployables
    with separate failure modes. The `hydraflow.component` tag is set on the
    *global* scope, because the loops and the ASGI middleware both push scopes.
16. **Incidental log promotion is not a bug report.** Sentry's logging
    integration turns every `logger.error` into an event, and most of this
    repo's error-level call sites attach no exception. Those arrive with no
    stack trace, group on message text, and reach triage as a sentence with
    nothing to act on. An event with no exception is dropped unless a call
    site asked for it explicitly.

Rules 8-12 are why the label matters more than it looks: the label is what
makes an error a routable piece of work rather than a notification. Rules
13-16 are why it is *reported at all*: before them the sensor covered one
process, from partway through its boot.

<!-- standard:enforced-by -->
- `tests/test_sentry_observability_adapter.py`
- `tests/test_triage_phase.py`
- `tests/test_issue_intake_boundary.py`
- `tests/architecture/test_intake_proxy_config.py`
- `tests/scenarios/test_exception_sensor_triage_scenario.py`
- `tests/test_process_sentry_sensor.py`
<!-- /standard:enforced-by -->

## Why a standard and not just an ADR

ADR-0118 removed the previous Sentry integration and left triage's consumer of
it in place. Nothing in `src/` wrote the marker that route keyed on for months;
the only writers repo-wide were the route's own tests, which hand-build the
string, so the tests stayed green while the route was unreachable in production.
An ADR records a decision at a point in time. A standard is re-checked on every
run, which is what that failure needed and did not have.
