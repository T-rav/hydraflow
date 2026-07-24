---
id: 0446
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:06:34.924979+00:00
status: stale
corroborations: 1
supersedes: 0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431
stale_reason: drift_detected: src/foo.py
---

# adr_index.py bare-collapse: grep the whole ADR before symbol-qualifying

`adr_index.py:249-252` collapses a file's citation to bare (file-level) granularity if *any* bare `src/foo.py` token for that path appears anywhere else in the same ADR — even if other lines correctly cite `src/foo.py:Symbol`. Example: before narrowing e.g. `src/base_background_loop.py` line 107 to `:BaseBackgroundLoop._execute_cycle` (ADR-0055) or an ADR-0019 line 121 target (#10433), grep the whole ADR file for other bare occurrences of that path and confirm the target line is the only citation of it. **Why:** one leftover bare mention silently re-widens the symbol set and reintroduces file-level drift sensitivity, causing spurious rollup reopens on unrelated touches even after the intended fix ships.
