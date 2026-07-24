---
id: 0939
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T22:10:19.635257+00:00
status: active
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
---

# Doc-typo ADR fixes still need parser-consumer regression tests

For a citation-repoint fix on ADR-0049 (`docs/adr/0049-trust-loop-kill-switch-convention.md`), the regression test lives in `tests/regressions/test_issue_10444.py` and asserts against `parse_adr_file()` output — that `source_files` includes `src/base_background_loop.py` and `src/bg_worker_manager.py`, and `source_symbols` maps them to `LoopDeps` / `BGWorkerManager.is_enabled` respectively.

Example: classified as not-load-bearing (no pipeline/runner/loop change), so per `docs/standards/testing/README.md` it skips MockWorld scenario and sandbox e2e — unit-level parser assertions plus the static guard are sufficient.

**Why:** an ADR text edit with no test would let the citation format regress again with no CI signal, same as #9514/#10440.
