---
id: 1012
topic: testing
source_issue: 10531
source_phase: plan
created_at: 2026-07-25T09:52:15.451007+00:00
status: active
corroborations: 1
---

# ADR :Symbol citations must be one backtick span or the symbol set parses empty

Splitting a citation like `` `src/phase_utils.py`:`file_memory_suggestion` `` across two backtick spans silently reverts the parser to bare-citation behavior — the cited-symbol set comes back empty and drift protection is lost with no error. It must be a single span: `` `src/phase_utils.py:file_memory_suggestion` ``. When narrowing ADR citations (e.g. ADR-0108's B5 row), assert the parsed citation exposes the exact symbol as a regression test, not just that the text superficially contains a colon. **Why:** this is a silent footgun — the ADR looks correctly narrowed to a human reader but still drifts on every unrelated file touch.
