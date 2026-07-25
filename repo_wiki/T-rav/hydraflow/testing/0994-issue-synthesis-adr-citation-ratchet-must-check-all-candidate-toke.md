---
id: 0994
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T06:21:18.137848+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0951,0952
---

# ADR citation ratchet must check all candidate tokens, not just parsed ones

`tests/architecture/test_adr_source_citations_exist.py` originally validated only citations that already matched `_SOURCE_FILE_CITATION_RE` against `source_files` — it never asserted that every `` `src/…py` `` -shaped token in a live ADR *does* match the regex. That let dead tokens (double-colon, trailing parens) exist invisibly. Add a token-parity ratchet: extract every lenient `src/*.py`-like candidate substring per ADR and assert `_SOURCE_FILE_CITATION_RE.fullmatch` succeeds, excluding placeholders via `_is_glob` (e.g. `src/<module>.py:<Symbol>`).

**Why:** testing only the happy path (parsed citations) can't catch citations that fail to parse in the first place — the exact gap that hid ADR-0049's lost coverage.
