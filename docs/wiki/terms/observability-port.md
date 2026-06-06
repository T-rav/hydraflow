---
id: "01KT3WKPR5MN8QJ14CF77W6K3"
name: "ObservabilityPort"
kind: "port"
bounded_context: "shared-kernel"
code_anchor: "src/ports.py:ObservabilityPort"
aliases: ["observability port", "sentry port", "error capture port"]
related: [{"kind": "depends_on", "target": "01KR1GDECRP5Z9X3HNGX3XFS8B"}, {"kind": "depends_on", "target": "01KTANBHSTGWNRXS6M142101ED"}, {"kind": "depends_on", "target": "01KTANCQNKWYRJ5ETEVNAMEY5A"}, {"kind": "depends_on", "target": "01KTBHAP0E4RHCFZVEC1P12QQM"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T00:00:00.000000+00:00"
updated_at: "2026-06-06T01:04:43.481148+00:00"
---

## Definition

Hexagonal port for the observability boundary (ADR-0044 P7.7). Exposes five methods: `capture_exception`, `capture_message`, `breadcrumb`, `set_measurement`, and `flush`. The production adapter is `SentryObservabilityAdapter` in `src/observability/sentry_adapter.py`, which wraps `sentry_sdk` and silently degrades to a no-op when the SDK is not installed. The port is intentionally minimal — rich APIs drag every backend into the union.

## Invariants

- Pure Protocol — no implementation, no state.
- The adapter is a no-op when `sentry_sdk` is absent; every method returns silently so callers never need a try/except around port calls.
- Domain code never imports `sentry_sdk` directly; all observability routes through the injected `ObservabilityPort` so a future OTLP, structured-log, or sidecar adapter can replace Sentry without touching call sites.
