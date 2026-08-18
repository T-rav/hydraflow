---
id: 2758
topic: testing
source_issue: 11442
source_phase: plan
created_at: 2026-08-18T08:00:27.527779+00:00
status: active
corroborations: 1
---

# Replace MagicMock dedup in scenario catalog with real DedupStore

In `tests/scenarios/catalog/loop_registrations.py`, `_build_erosion_metrics` used `MagicMock()` with `dedup.get.return_value = set()` — a fake that cannot dedupe, so a scenario passes for the wrong reason. Replace with a real `DedupStore("erosion_metrics_filed_findings", config.data_root / "dedup" / "erosion_metrics_filed.json")` mirroring production.

**Why:** A dedup fake that always returns an empty set hides double-filing bugs; the scenario must exercise the actual dedup collision path.
