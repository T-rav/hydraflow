---
id: 0615
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.239330+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# Keep record_git docstring in sync with its actual fixture, not a stale example

`src/contract_recording.py`'s `record_git` docstring referenced a "hello.txt" example that no longer matches the real fixture (now a 3-file `git_sandbox`).

Example: stale docstring examples in contract-recording code are easy to miss because they don't fail tests directly — they only surface when someone trusts the docstring while debugging a cassette mismatch and gets misled about what the recorder actually captures.

**Why:** Contract-recording docstrings double as onboarding docs for `ContractRefreshLoop` maintenance; drift here costs future debugging time even though `make quality` won't catch it.
