---
id: 0221
topic: architecture
source_issue: 10578
source_phase: plan
created_at: 2026-07-26T01:20:17.466865+00:00
status: active
corroborations: 1
---

# Path-helper modules import `HydraFlowConfig` only under `TYPE_CHECKING`

When adding a `default_X_path(config)` helper to a leaf module like `src/escape/ledger.py`, import `HydraFlowConfig` under `TYPE_CHECKING` only, never at runtime. `service_registry.py` imports both `escape.ledger` and `config`, so a runtime import the other way creates a cycle.
**Why:** avoids a circular-import failure at startup, matching the existing `wiki_maint_queue` precedent.
