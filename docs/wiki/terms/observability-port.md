---
id: "01KT3WKPR5MN8QJ14CF77W6K3"
name: "ObservabilityPort"
kind: "port"
bounded_context: "shared-kernel"
code_anchor: "src/ports.py:ObservabilityPort"
aliases: ["observability port", "sentry port", "error capture port"]
related: [{"kind": "depends_on", "target": "01KR1GDECRP5Z9X3HNGX3XFS8B"}, {"kind": "depends_on", "target": "01KYABD5XVX4ZXFXT3Z76KMQZ0"}, {"kind": "depends_on", "target": "01KYBV9N8VSTKDRVDFC0FE40ZM"}]
evidence: ["01KQNZEVQVRHE57A588EWZXKKD", "01KQP0HK6TCK1CTRYANSJ8NRTM", "01KQP10AJV73YGEATZKR6QXCAA"]
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T00:00:00.000000+00:00"
updated_at: "2026-07-26T10:16:32.370693+00:00"
---

## Definition

Hexagonal port for the observability boundary (ADR-0044 P7.7). Exposes five methods: `capture_exception`, `capture_message`, `breadcrumb`, `set_measurement`, and `flush`. Sentry was removed by ADR-0118 (observability moves to a dedicated SRE agent targeting New Relic), so the production adapter is now `NoOpObservabilityAdapter` in `src/observability/noop_adapter.py` — a null object whose methods return silently — and the SRE agent will supply the real adapter for this seam. The port is intentionally minimal — rich APIs drag every backend into the union.

## Invariants

- Pure Protocol — no implementation, no state.
- The production adapter (`NoOpObservabilityAdapter`) is a null object; every method returns silently so callers never need a try/except around port calls.
- Domain code never imports an observability SDK directly; all observability routes through the injected `ObservabilityPort` so the SRE agent's future adapter (New Relic, OTLP, structured-log, or sidecar) can replace the no-op without touching call sites.
