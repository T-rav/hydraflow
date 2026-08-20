---
id: 0409
topic: architecture
source_issue: 11469
source_phase: plan
created_at: 2026-08-20T06:54:03.674059+00:00
status: active
corroborations: 1
---

# Encapsulate gateway capture file naming inside GatewayBodyStore

Keep capture filename knowledge encapsulated inside `GatewayBodyStore`; expose paths via a validating public accessor. In `src/hydraflow_gateway/ledger.py`, expose `response_body_path(capture_id)` to validate the capture-id pattern and return the path, preventing `scripts/gateway_probe.py` from reconstructing file paths.
**Why:** Re-encoding capture file naming in external scripts creates fragile coupling and risks path traversal or format drift when the store's internal layout changes.
