---
id: 0406
topic: architecture
source_issue: 11446
source_phase: plan
created_at: 2026-08-18T09:14:02.932561+00:00
status: active
corroborations: 1
---

# DedupStore set_name and filename must match src/service_registry.py verbatim

When constructing a `DedupStore` in tests, copy the `(set_name, filename)` pair exactly from that loop's production wiring in `src/service_registry.py` (~lines 1400–1900).

- `erosion_metrics` → `("erosion_metrics_filed_findings", "dedup/erosion_metrics_filed.json")`
- `gate_activator` → `("gate_activator", "dedup/gate_activator.json")`
- Do not invent or normalize names.

**Why:** Path parity is what lets a scenario pre-seed prior-filed keys by writing the JSON file; a mismatched name makes the store read an empty file and the test exercises nothing.
