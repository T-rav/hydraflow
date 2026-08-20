---
id: 4075
topic: patterns
source_issue: 11469
source_phase: plan
created_at: 2026-08-20T06:54:03.674031+00:00
status: active
corroborations: 1
---

# Prove provider byte-identity via tap-side capture, not dual live calls

Prove provider-backed SSE byte-transparency by tap-side comparison on the same call, not by comparing two distinct live provider calls. Use `GatewayBodyStore` in `src/hydraflow_gateway/ledger.py` to tee upstream bytes (`{id}.response.body`). The probe byte-compares client-received stream against this exact capture.
**Why:** Distinct live provider calls generate fresh message IDs and usage metrics, making byte-identical comparison impossible and false-negativing the conformance gate.
