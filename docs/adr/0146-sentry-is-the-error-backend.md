# ADR-0146: Sentry is the error backend

- **Status:** Accepted
- **Date:** 2026-09-01
- **Supersedes:** [ADR-0118](0118-observability-belongs-to-the-sre-agent-not-the-loops.md) (observability belongs to the SRE agent — its backend direction only; see "What ADR-0118 said that still stands")
- **Superseded by:** none
- **Related:** [ADR-0055](0055-otel-honeycomb-instrumentation.md) (the OTel layer ADR-0118 removed), [ADR-0044](0044-hydraflow-principles.md) (P7.7, the observability boundary), [ADR-0085](0085-secret-scrubbing.md) (why an error payload is not a free-for-all). Issues: #11879 (the SRE agent epic this changes the target of).
- **Enforcement:** enforced
- **Binds:** factory

**Enforced by:**
pytest:tests/test_sentry_observability_adapter.py::TestTheDsnIsTheSwitch::test_no_dsn_gets_the_no_op
pytest:tests/test_sentry_observability_adapter.py::TestErrorsOnly::test_tracing_is_initialised_off

## Context

ADR-0118 removed the OpenTelemetry/Honeycomb layer, removed Sentry with it, and
named New Relic as the intended backend — to be wired "when the SRE agent
lands." That agent is still an epic (#11879, human-required), so for a month the
`ObservabilityPort` has had exactly one adapter: a no-op that discards every
event. `capture_exception` has been a function that does nothing, called from
code that believes it reports.

The operator's decision on 2026-09-01: turn error ingestion back on now, with
Sentry, rather than wait for an agent that has not been built.

## Decision

**Sentry is the error backend. It supersedes New Relic as the direction, and
its scope is errors only.**

1. **Sentry ingests errors.** `SentryObservabilityAdapter` implements
   `capture_exception`, `capture_message` and `breadcrumb`. This reverses
   ADR-0118 §3, which removed Sentry by name.

2. **New Relic is dropped as the direction.** ADR-0118 §4 named it as the
   intended backend; nothing was built against it, and this ADR does not carry
   it forward. The SRE agent epic (#11879) should be read against Sentry.

3. **Metric ingestion is not implemented.** `set_measurement` stays a no-op.
   ADR-0118 pointed metrics at New Relic; dropping that direction leaves them
   without a home, and saying so plainly beats naming a backend nobody is
   building. This is a gap, recorded as one.

4. **Tracing is out of scope, and spans remain OTel's concern.**
   `phase_utils._sentry_transaction` stays the no-op it is today, and the
   adapter initialises with `traces_sample_rate=0.0`. A transport that quietly
   began sampling transactions would re-instrument the loops through the back
   door — the specific thing ADR-0118 objected to, and the part of it this ADR
   does not reverse.

5. **The DSN's presence is the switch.** No separate enable flag: two settings
   can disagree and one cannot. An environment without a DSN — tests, CI, the
   air-gapped sandbox — gets the no-op adapter automatically, so a test run
   cannot page a human and a network-isolated container never reaches for a
   host that is not there.

## What ADR-0118 said that still stands

This ADR supersedes ADR-0118's *backend direction*, not the whole document. Two
of its rulings are carried forward unchanged, and neither is re-opened here:

- **§1 — no OpenTelemetry under `src/`.** The import-boundary gate that enforces
  it stays exactly as it is. Spans being "OTel's concern" is a statement about
  direction, not permission: re-adding the dependency is its own change, with
  its own ADR, and this one does not lift a gate as a side effect.
- **§2 — local trace collection stays.** `trace_collector` writes per-subprocess
  JSON traces to `data_root` and feeds the cost/duration dashboard. It is
  HydraFlow's own artifact, unaffected by any of this.

## Consequences

- Errors that were silently discarded now reach a human. That is the point, and
  it is also the risk: the first days will surface exceptions the factory has
  been swallowing for a month, and some will be noise.
- `send_default_pii=False`. Prompts and transcripts routinely carry issue and PR
  text, and shipping local variables to a third party as a side effect of an
  error is not a decision an error reporter should make on its own (ADR-0085 is
  the same instinct applied to logs).
- Reporting failures are swallowed. Observability that can fail the work it
  observes has turned a diagnostic into an outage, so every method logs at debug
  and returns; a broken DSN falls back to the no-op rather than stopping boot.
- The DSN is a **credential**, resolved from `os.environ` then the repo `.env`,
  the same way `gh_token` is. An `os.environ`-only read would have left this
  permanently inert on a deployment that keeps the DSN in `.env` and does not
  export it — configured-looking and doing nothing, which is the failure mode
  this ADR exists to end.
