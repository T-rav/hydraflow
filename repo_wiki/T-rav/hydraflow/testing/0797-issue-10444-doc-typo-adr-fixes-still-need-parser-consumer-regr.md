---
id: 0797
topic: testing
source_issue: 10444
source_phase: plan
created_at: 2026-07-24T10:56:36.678111+00:00
status: superseded
corroborations: 1
superseded_by: 0798
---

# Doc-typo ADR fixes still need parser-consumer regression tests, not just the ADR edit

For a citation-repoint fix on ADR-0049 (`docs/adr/0049-trust-loop-kill-switch-convention.md`), the regression test lives in `tests/regressions/test_issue_10444.py` and asserts against `parse_adr_file()` output — that `source_files` includes `src/base_background_loop.py` and `src/bg_worker_manager.py`, and `source_symbols` maps them to `LoopDeps` / `BGWorkerManager.is_enabled` respectively. This is classified as not-load-bearing (no pipeline/runner/loop change), so per `docs/standards/testing/README.md` it skips MockWorld scenario and sandbox e2e — unit-level parser assertions plus the static guard are sufficient. **Why:** an ADR text edit with no test would let the citation format regress again with no CI signal, same as #9514/#10440.
