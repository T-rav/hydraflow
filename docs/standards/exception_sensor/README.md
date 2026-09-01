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
| Inbound | The backend's own tracker integration | Turns error groups into GitHub issues |

The inbound half is deliberately *not* a HydraFlow loop. Bugsink already files
GitHub issues, deduplicated per error group; a polling loop here would be a
second implementation of something the backend does, with its own state, its own
backoff, and its own way of going stale.

## House flavour

The client is the **Sentry SDK**, so the target is any endpoint speaking the
Sentry ingest protocol. The house default is **Bugsink** — self-hosted, so error
payloads from a repo full of unreleased work stay on infrastructure the operator
owns. Pointing a repo at sentry.io instead is a DSN change, not a code change,
and this standard is satisfied either way.

## Rules

1. **The sensor is off without a target.** No DSN means the no-op adapter. Tests,
   CI and the air-gapped sandbox must never report.
2. **Reporting never fails the work.** A sensor that raises into the code it
   observes has made reliability worse. Transport errors are swallowed.
3. **A broken target does not stop boot.** An unreachable endpoint degrades to
   the no-op; the factory keeps running blind rather than not at all.
4. **The sensor does not trace.** Errors only. Spans remain OTel's (ADR-0118 §1).
5. **Payloads carry no PII by default.** No local variables, no request bodies.
6. **The target is resolved from the environment.** DSN from the environment or
   the repo `.env`, never from code.
7. **Sensor issues declare their provenance.** They carry the sensor label
   (`bugsink` by default) so an operator reading the board can tell an observed
   failure from an authored finding.
8. **Triage routes them as incoming system exceptions.** A sensor issue that
   fails triage is a transient, not a bug report, and is auto-closed rather than
   parked for clarification that no author will ever supply.

Rules 7 and 8 are why the label matters more than it looks: the label is what
makes an error a routable piece of work rather than a notification.

<!-- standard:enforced-by -->
- `tests/test_sentry_observability_adapter.py`
- `tests/test_triage_phase.py`
<!-- /standard:enforced-by -->

## Why a standard and not just an ADR

ADR-0118 removed the previous Sentry integration and left triage's consumer of
it in place. Nothing in `src/` wrote the marker that route keyed on for months;
the only writers repo-wide were the route's own tests, which hand-build the
string, so the tests stayed green while the route was unreachable in production.
An ADR records a decision at a point in time. A standard is re-checked on every
run, which is what that failure needed and did not have.
