---
id: 2766
topic: testing
source_issue: 11469
source_phase: plan
created_at: 2026-08-20T06:54:03.674075+00:00
status: active
corroborations: 1
---

# Test gateway probe byte-compare via ASGITransport and mutation kill

Test gateway probe byte-comparison deterministically by mounting the app via `ASGITransport` with a `MockTransport` upstream and explicitly mutating the captured bytes. Build the gateway in-process using `create_app`. Assert green on transparent passthrough, then assert red (mutation kill) by substituting a corrupted capture file in `tests/test_gateway_probe.py`.
**Why:** Network flakiness and non-deterministic upstream provider responses cannot validate the strict byte-for-byte identity logic required by the gateway tap.
