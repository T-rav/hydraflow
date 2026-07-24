---
id: 0393
topic: gotchas
source_issue: 10230
source_phase: plan
created_at: 2026-07-22T18:13:39.968110+00:00
status: superseded
corroborations: 1
superseded_by: 0402
---

# Keep `record_git` docstring in sync with its actual fixture, not a stale example

`src/contract_recording.py`'s `record_git` docstring referenced a "hello.txt" example that no longer matches the real fixture (now a 3-file `git_sandbox`). Stale docstring examples in contract-recording code are easy to miss because they don't fail tests directly — they only surface when someone trusts the docstring while debugging a cassette mismatch and gets misled about what the recorder actually captures.

**Why:** contract-recording docstrings double as onboarding docs for `ContractRefreshLoop` maintenance; drift here costs future debugging time even though `make quality` won't catch it.
