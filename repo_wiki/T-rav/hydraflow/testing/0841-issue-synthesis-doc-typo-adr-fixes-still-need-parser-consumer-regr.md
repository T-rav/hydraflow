---
id: 0841
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.222271+00:00
status: active
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
---

# Doc-typo ADR fixes still need parser-consumer regression tests

For a citation-repoint fix on ADR-0049 (`docs/adr/0049-trust-loop-kill-switch-convention.md`), the regression test lives in `tests/regressions/test_issue_10444.py` and asserts against `parse_adr_file()` output — that `source_files` includes `src/base_background_loop.py` and `src/bg_worker_manager.py`, and `source_symbols` maps them to `LoopDeps` / `BGWorkerManager.is_enabled` respectively.

Example: classified as not-load-bearing (no pipeline/runner/loop change), so per `docs/standards/testing/README.md` it skips MockWorld scenario and sandbox e2e — unit-level parser assertions plus the static guard are sufficient.

**Why:** an ADR text edit with no test would let the citation format regress again with no CI signal, same as #9514/#10440.
