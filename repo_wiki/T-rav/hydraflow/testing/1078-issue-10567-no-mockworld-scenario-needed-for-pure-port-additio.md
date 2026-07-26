---
id: 1078
topic: testing
source_issue: 10567
source_phase: plan
created_at: 2026-07-25T23:37:32.613892+00:00
status: stale
corroborations: 1
stale_reason: source issue #10567 closed
---

# No MockWorld scenario needed for pure Port additions with no consumer

Per docs/standards/testing/README.md's three-layer pyramid, a `tests/scenarios/` MockWorld scenario is skipped when a new Port method has no orchestrator/runner consumer yet — a scenario would only assert the fake against itself, same reasoning as existing boot-time-infra exemptions. Unit test (adapter argv) + ADR-0047 cassette + `tests/test_ports.py`/`tests/test_mockworld_runtime_conformance.py` parity checks are the gating layer instead.
**Why:** prevents writing a scenario test that can't fail meaningfully, which would give false confidence without covering real loop integration.
