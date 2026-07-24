---
id: 0424
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:55:43.296672+00:00
status: active
corroborations: 1
supersedes: 0370,0371,0372,0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
---

# Keep record_git docstring in sync with its actual fixture, not a stale example

`src/contract_recording.py`'s `record_git` docstring referenced a "hello.txt" example that no longer matches the real fixture (now a 3-file `git_sandbox`). Stale docstring examples in contract-recording code are easy to miss because they don't fail tests directly — they only surface when someone trusts the docstring while debugging a cassette mismatch and gets misled about what the recorder actually captures.

**Why:** contract-recording docstrings double as onboarding docs for `ContractRefreshLoop` maintenance; drift here costs future debugging time even though `make quality` won't catch it.
