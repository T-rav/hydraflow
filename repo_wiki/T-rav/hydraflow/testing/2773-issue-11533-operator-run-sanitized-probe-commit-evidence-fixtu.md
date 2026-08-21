---
id: 2773
topic: testing
source_issue: 11533
source_phase: plan
created_at: 2026-08-21T09:41:01.976083+00:00
status: active
corroborations: 1
---

# Operator-run sanitized probe: commit evidence fixture, CI checks schema

Prove live runtime boundaries with an operator-run probe whose only output is one sanitized artifact committed as a fixture; CI validates the fixture's schema, never the live run.
- `scripts/director_capability_probe.py` follows the `scripts/gateway_probe.py` pattern; evidence lands at `tests/fixtures/director/director_capability_probe_evidence.json` (mirror: gateway's `live_provider_probe_evidence.json`).
- Fail closed: if the probe can't prove the boundary, the ADR records no-go and dependent arming stays off — never force green.
- Assert the scrubbed spawn env, not host state (macOS/Linux keychain divergence makes host assertions flaky); delete raw captures before exit.
**Why:** Real-account probes cost money and flake in CI; schema-pinned fixtures keep the boundary fact durable without credentials.
