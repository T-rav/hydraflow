---
id: 1061
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:44:02.076416+00:00
status: active
corroborations: 1
supersedes: 0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0951,0952,0953,0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014,1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1031,1032,1033,1034,1035,1036
---

# Keep record_git docstring in sync with its actual fixture, not a stale example

`src/contract_recording.py`'s `record_git` docstring referenced a "hello.txt" example that no longer matches the real fixture (now a 3-file `git_sandbox`).

Example: stale docstring examples in contract-recording code don't fail tests directly — they only surface when someone trusts the docstring while debugging a cassette mismatch.

**Why:** Contract-recording docstrings double as onboarding docs for `ContractRefreshLoop` maintenance; drift here costs future debugging time even though `make quality` won't catch it.
