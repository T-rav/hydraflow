---
id: 0185
topic: architecture
source_issue: 10440
source_phase: plan
created_at: 2026-07-24T10:50:57.616711+00:00
status: active
corroborations: 1
---

# ADR source citations must use single-colon `src/file.py:Symbol` form

`_SOURCE_FILE_CITATION_RE` in `tests/architecture/test_adr_source_citations_exist.py` only matches `` `src/file.py:Symbol` `` — a doubled colon (`::`) or a trailing `()` fails to parse and the citation silently never enters `source_files`, so the drift gate can never fire for that module. ADR-0049 cited `base_background_loop.py::LoopDeps` and `bg_worker_manager.py::BGWorkerManager.is_enabled` with `::`; ADR-0004:34 cited `agent_cli.py:build_agent_command()` with trailing parens. Both forms silently dropped coverage rather than erroring.
**Why:** a regex mismatch fails open (citation ignored) instead of closed (citation flagged), so drift protection quietly disappears with no test failure to signal it.
