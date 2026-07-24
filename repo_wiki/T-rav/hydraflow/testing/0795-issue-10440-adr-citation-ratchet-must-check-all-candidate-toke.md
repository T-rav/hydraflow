---
id: 0795
topic: testing
source_issue: 10440
source_phase: plan
created_at: 2026-07-24T10:50:57.616746+00:00
status: superseded
corroborations: 1
superseded_by: 0798
---

# ADR citation ratchet must check all candidate tokens, not just parsed ones

`tests/architecture/test_adr_source_citations_exist.py` originally validated only citations that already matched `_SOURCE_FILE_CITATION_RE` against `source_files` — it never asserted that every `` `src/…py` ``-shaped token in a live ADR *does* match the regex. That let dead tokens (double-colon, trailing parens) exist invisibly. Add a token-parity ratchet: extract every lenient `src/*.py`-like candidate substring per ADR and assert `_SOURCE_FILE_CITATION_RE.fullmatch` succeeds, excluding placeholders via `_is_glob` (e.g. `src/<module>.py:<Symbol>`).
**Why:** testing only the happy path (parsed citations) can't catch citations that fail to parse in the first place — the exact gap that hid ADR-0049's lost coverage.
