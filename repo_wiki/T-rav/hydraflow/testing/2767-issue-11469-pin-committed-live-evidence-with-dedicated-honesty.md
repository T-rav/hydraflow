---
id: 2767
topic: testing
source_issue: 11469
source_phase: plan
created_at: 2026-08-20T06:54:03.674083+00:00
status: active
corroborations: 1
---

# Pin committed live evidence with dedicated honesty tests

Pin committed live-run artifacts with dedicated honesty tests that assert behavioral flags, per-turn identity, and disjoint forbidden-key sanitization. Mirror `test_actual_claude_cli_sandbox_evidence_is_honest_and_sanitized` (`tests/test_gateway_conformance.py:213`) to validate `tests/fixtures/gateway/live_probe_evidence.json`: verify `live_provider_session is True`, sha256s present, and raw traces absent.
**Why:** Static artifacts rot or leak secrets if untested; structural honesty pins ensure the committed evidence remains sanitized and scientifically valid.
