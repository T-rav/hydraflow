---
id: 1306
topic: gotchas
source_issue: 11132
source_phase: plan
created_at: 2026-08-14T12:40:51.197350+00:00
status: active
corroborations: 1
---

# Aggregate counter getters silently drop non-int values

Every getter that reads aggregate telemetry counters in `src/prompt_telemetry.py` filters values through `isinstance(v, int)`. A float-typed key is silently dropped from the returned dict, not coerced.

- When adding a new counter key (e.g. `cache_read_input_tokens`), it must be stored and accumulated as **int**, exactly like `estimated_cost_microusd`.
- A `_as_int()` helper exists for safe accumulation; use it on both sides: `_as_int(target.get(k, 0)) + _as_int(record.get(k, 0))`.

**Why:** A float counter key passes `_accumulate_counter()` but vanishes at read time, producing empty fields with no error or log line.
