---
id: 0890
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.570639+00:00
status: superseded
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
superseded_by: 0896
---

# Doc-typo ADR fixes still need parser-consumer regression tests

For a citation-repoint fix on ADR-0049 (`docs/adr/0049-trust-loop-kill-switch-convention.md`), the regression test lives in `tests/regressions/test_issue_10444.py` and asserts against `parse_adr_file()` output — that `source_files` includes `src/base_background_loop.py` and `src/bg_worker_manager.py`, and `source_symbols` maps them to `LoopDeps` / `BGWorkerManager.is_enabled` respectively.

Example: classified as not-load-bearing (no pipeline/runner/loop change), so per `docs/standards/testing/README.md` it skips MockWorld scenario and sandbox e2e — unit-level parser assertions plus the static guard are sufficient.

**Why:** an ADR text edit with no test would let the citation format regress again with no CI signal, same as #9514/#10440.
