---
id: 1071
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:44:02.089340+00:00
status: superseded
corroborations: 1
supersedes: 0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0951,0952,0953,0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014,1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1031,1032,1033,1034,1035,1036
superseded_by: 1144
---

# Unrelated ADR citation fixes need separate PRs, not bundled rollup closes

When fixing a bare-citation bug in one ADR, file separate issues for the same bug in other ADRs rather than bundling them into an unrelated rollup-closing PR.

Example: ADR-0012 has the same bare `src/epic.py` citation bug as ADR-0019 had before #10384's fix — but fixing it there won't close #10384 and is out of scope for that PR.

**Why:** Bundling unrelated ADR fixes risks scope creep per `docs/wiki/architecture-refactoring.md` multi-PR drift discipline.
