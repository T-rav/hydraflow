---
id: 2759
topic: testing
source_issue: 11446
source_phase: plan
created_at: 2026-08-18T09:14:02.932527+00:00
status: active
corroborations: 1
---

# MockWorld scenario builders must use real DedupStore, not MagicMock

Scenario builders in `tests/scenarios/catalog/loop_registrations.py` must wire a real `DedupStore` — never `MagicMock(); dedup.get.return_value = set()`.

- A mocked dedup always returns an empty set, so repeat-filing suppression is invisible at scenario tier.
- Use the `_scenario_dedup(ports, config, port_key, set_name, filename)` helper, which constructs `DedupStore(set_name, config.data_root / "dedup" / filename)`.
- `_build_live_corpus_replay` and `_build_memory_backlog` already follow the target shape.

**Why:** A dedup regression that breaks read-your-writes passes green when the collaborator is a mock that always yields `set()`.
