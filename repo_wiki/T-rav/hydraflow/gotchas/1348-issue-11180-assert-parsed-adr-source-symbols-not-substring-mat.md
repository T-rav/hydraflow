---
id: 1348
topic: gotchas
source_issue: 11180
source_phase: plan
created_at: 2026-08-14T23:23:17.598892+00:00
status: active
corroborations: 1
---

# Assert parsed ADR source_symbols, not substring matches

Prefer asserting on parsed `adr.source_symbols["src/base_background_loop.py"]` containing `LoopDeps` over substring-matching the ADR body.

- A `::` typo in a citation (e.g. `src/base_background_loop.py::LoopDeps`) produces an empty symbol set.
- Substring match on raw text would pass; the parsed-symbol assertion fails.

**Why:** An empty `source_symbols` dict is precisely the failure mode a substring check hides — the parsed assertion is strictly stronger and catches citation-format regressions the substring guard misses.
