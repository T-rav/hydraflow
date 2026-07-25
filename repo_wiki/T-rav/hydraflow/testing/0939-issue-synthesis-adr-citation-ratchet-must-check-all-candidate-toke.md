---
id: 0939
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:46:40.933582+00:00
status: superseded
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
superseded_by: 0953
---

# ADR citation ratchet must check all candidate tokens, not just parsed ones

`tests/architecture/test_adr_source_citations_exist.py` originally validated only citations that already matched `_SOURCE_FILE_CITATION_RE` against `source_files` — it never asserted that every `` `src/…py` ``-shaped token in a live ADR *does* match the regex. That let dead tokens (double-colon, trailing parens) exist invisibly. Add a token-parity ratchet: extract every lenient `src/*.py`-like candidate substring per ADR and assert `_SOURCE_FILE_CITATION_RE.fullmatch` succeeds, excluding placeholders via `_is_glob` (e.g. `src/<module>.py:<Symbol>`).

**Why:** testing only the happy path (parsed citations) can't catch citations that fail to parse in the first place — the exact gap that hid ADR-0049's lost coverage.
