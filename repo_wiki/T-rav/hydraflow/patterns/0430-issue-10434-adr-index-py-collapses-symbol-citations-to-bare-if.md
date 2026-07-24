---
id: 0430
topic: patterns
source_issue: 10434
source_phase: plan
created_at: 2026-07-24T10:19:32.942771+00:00
status: active
corroborations: 1
---

# adr_index.py collapses :Symbol citations to bare if any bare token remains

`adr_index.py:249-252` collapses a file's citation to bare granularity if *any* bare `src/foo.py` token for that file appears anywhere else in the same ADR — even if other lines correctly cite `src/foo.py:Symbol`. One leftover bare mention nullifies a symbol-granularity fix.

Example: fixing ADR-0055's line 107 `src/base_background_loop.py` to `:BaseBackgroundLoop._execute_cycle` only prevents false-positive drift if no other bare occurrence of that path exists in the file.

**Why:** silently reintroduces file-level (bare) drift sensitivity, causing spurious rollup reopens even after the intended fix ships.
