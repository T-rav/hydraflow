---
id: 0625
topic: patterns
source_issue: 10731
source_phase: plan
created_at: 2026-07-27T18:39:53.932366+00:00
status: active
corroborations: 1
---

# Rows without detection_ref use __noref__:<id> keys, not a shared singleton

In `escape_by_id()` (`src/escape/metrics.py`), rows with no `detection_ref` use the synthetic key `__noref__:<id>` so each maps to itself.

Example: two no-ref rows with ids `a1` and `b2` produce two distinct index entries, not one shared `None` entry.

**Why:** A shared `None` key would collapse unrelated no-ref rows into one, losing entries and silently dropping reconciliations.
