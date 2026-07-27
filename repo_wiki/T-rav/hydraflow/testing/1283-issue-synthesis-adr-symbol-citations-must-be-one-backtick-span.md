---
id: 1283
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:11:03.423131+00:00
status: active
corroborations: 1
supersedes: 1209
---

# ADR :Symbol citations must be one backtick span

A `path:Symbol` citation must be a single contiguous backtick span — splitting path and symbol across separate spans silently reverts the parser to bare-citation behavior with an empty symbol set.

Example: `src/phase_utils.py:file_memory_suggestion` (correct) vs `src/phase_utils.py`:`file_memory_suggestion` (broken). Assert the parsed citation exposes the exact symbol as a regression test.

**Why:** The ADR looks correctly narrowed to a human reader but still drifts on every unrelated file touch — a silent footgun with no error.
