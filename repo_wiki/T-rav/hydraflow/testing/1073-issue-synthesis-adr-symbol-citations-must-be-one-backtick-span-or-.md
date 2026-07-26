---
id: 1073
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.563197+00:00
status: superseded
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
superseded_by: 1085
---

# ADR :Symbol citations must be one backtick span or the symbol set parses empty

Splitting a citation like `` `src/phase_utils.py`:`file_memory_suggestion` `` across two backtick spans silently reverts the parser to bare-citation behavior — the cited-symbol set comes back empty and drift protection is lost with no error. It must be a single span: `` `src/phase_utils.py:file_memory_suggestion` ``.

Example: when narrowing ADR citations (e.g. ADR-0108's B5 row), assert the parsed citation exposes the exact symbol as a regression test, not just that the text superficially contains a colon.

**Why:** this is a silent footgun — the ADR looks correctly narrowed to a human reader but still drifts on every unrelated file touch.
