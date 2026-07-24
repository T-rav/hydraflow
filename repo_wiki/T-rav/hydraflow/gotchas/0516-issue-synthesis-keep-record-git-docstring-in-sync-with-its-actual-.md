---
id: 0516
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.786908+00:00
status: active
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
---

# Keep record_git docstring in sync with its actual fixture, not a stale example

`src/contract_recording.py`'s `record_git` docstring referenced a "hello.txt" example that no longer matches the real fixture (now a 3-file `git_sandbox`).

Example: stale docstring examples in contract-recording code are easy to miss because they don't fail tests directly — they only surface when someone trusts the docstring while debugging a cassette mismatch and gets misled about what the recorder actually captures.

**Why:** Contract-recording docstrings double as onboarding docs for `ContractRefreshLoop` maintenance; drift here costs future debugging time even though `make quality` won't catch it.
