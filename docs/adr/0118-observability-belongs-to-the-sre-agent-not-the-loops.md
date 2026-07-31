# ADR-0118: Observability belongs to the SRE agent, not the loops

- **Status:** Accepted
- **Date:** 2026-07-31
- **Supersedes:** [ADR-0055](0055-otel-honeycomb-instrumentation.md) (OpenTelemetry as the telemetry layer)
- **Superseded by:** none
- **Related:** [ADR-0045](0045-trust-architecture-hardening.md) (fleet roles), [ADR-0029](0029-caretaker-loop-pattern.md) (loops are reflexes)
- **Enforcement:** enforced
- **Binds:** both

**Enforced by:**
pytest:tests/architecture/test_no_otel_imports.py

## Context

ADR-0055 established OpenTelemetry (OTLP/HTTP) → Honeycomb as HydraFlow's telemetry layer — span decorators (`@runner_span`/`@loop_span`/`@port_span`), a Honeycomb export gated on `otel_enabled`, OTel metrics in `review_advisor`, and a `FakeHoneycomb` test double. It was explicitly **Phase A**: an ingest layer whose Phase B (anomaly → issue pipeline) was deferred until real trace data existed.

Phase B never came, and Phase A never turned on. Verified 2026-07-31:

- `otel_enabled` defaults **False**; `HONEYCOMB_API_KEY` is unset — `init_otel` no-ops, so the production tracer is OTel's no-op tracer and **zero spans/metrics are exported**.
- The operator's Honeycomb account is **free-tier**, where the queries/SLOs the Phase-B detection needed are Enterprise-only. Honeycomb *ingestion* was already removed for the same reason (ADR precedent: the `honeycomb_loop` revert, #9244).

So OTel has been dormant instrumentation woven through the hot path (base runner, base loop, every port) and a load-bearing module (`review_advisor`) for no realized signal.

Meanwhile the operating model moved on. Under the four-role model, **observability is the SRE/maintenance role's job**, and the deep-agent plan makes a dedicated **SRE agent** the owner of sensing failures — the loops are reflexes (ADR-0029) and should not each carry telemetry duty. The detection premise ADR-0055 cited (the dark factory files its own ops issues) is better served by an agent that reads a real observability backend than by decorators no one queries.

## Decision

**Remove the OpenTelemetry/Honeycomb layer from the factory. Observability is owned by a dedicated SRE agent, targeting New Relic as the backend, not instrumented into the loops.**

1. **Delete the OTel layer.** The `telemetry/` package (spans/otel/subprocess_bridge/slugs), the `@runner_span`/`@loop_span`/`@port_span` decorators and their usages, `review_advisor`'s `opentelemetry.metrics` instruments, `otel_*` config, `init_otel`, and `FakeHoneycomb` are removed. No `opentelemetry` import remains under `src/` (the enforcement).

2. **Local trace collection stays.** `trace_collector` writes per-subprocess JSON traces to `data_root` and feeds the cost/duration dashboard. It is HydraFlow's own artifact, not OTel, and is unaffected beyond dropping its one span-bridge call.

3. **Sentry is removed too** (separate change) — same rationale: error ingestion is the SRE agent's job, not a loop's. New Relic + the SRE agent replace both the OTel-export and Sentry-ingest paths.

4. **New Relic is the intended backend**, to be wired when the SRE agent lands. This ADR does not build it; it records the direction and removes the machinery that would otherwise rot.

## Consequences

- **Positive:** the hot-path base classes and `review_advisor` shed dormant instrumentation; a recurring slice of test-infra churn (FakeHoneycomb/OTel provider-leak flakes) disappears; the observability responsibility is located in one role instead of smeared across every loop.
- **Negative / transition gap:** with OTel *and* Sentry removed before New Relic + the SRE agent exist, the factory has **no live error/latency observability** in the interim. Accepted deliberately (2026-07-31): OTel exported nothing anyway, and the interim is covered by the deterministic gates + local `trace_collector` cost data until the SRE agent is built.
- **Reversibility:** the removal is a clean deletion in git history; re-introducing distributed tracing (against New Relic) is a fresh, agent-owned design rather than a revert.
