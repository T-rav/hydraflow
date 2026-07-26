---
id: 1056
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.528822+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# ADR citation ratchet must check all candidate tokens, not just parsed ones

tests/architecture/test_adr_source_citations_exist.py originally validated only citations that already matched _SOURCE_FILE_CITATION_RE against source_files — it never asserted that every `src/...py`-shaped token in a live ADR does match the regex, letting dead tokens (double-colon, trailing parens) exist invisibly.

Example: add a token-parity ratchet: extract every lenient src/*.py-like candidate substring per ADR and assert _SOURCE_FILE_CITATION_RE.fullmatch succeeds, excluding placeholders via _is_glob (e.g. src/<module>.py:<Symbol>).

**Why:** testing only the happy path (parsed citations) can't catch citations that fail to parse in the first place — the exact gap that hid ADR-0049's lost coverage.
