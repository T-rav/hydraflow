---
id: 0222
topic: architecture
source_issue: 10587
source_phase: plan
created_at: 2026-07-26T02:52:52.792523+00:00
status: active
corroborations: 1
---

# wiki_rot_detector_loop private methods must publish before cross-module reuse

`WikiRotDetectorLoop._shipped_claim_corroborated` held logic needed by `src/repo_wiki.py`'s `active_lint_tracked`. Rather than importing the underscore-prefixed method across modules, extract it to a public `shipped_claim_corroborated(claim, repo_root)` in `src/wiki_rot_citations.py` and have the loop delegate to it. This mirrors the existing rule for `split_tracked_entry` in `repo_wiki.py` (see `[[repo_wiki_cross_module_underscore_wrapper]]`) — the citations/detection module is the canonical home, loops delegate.
**Why:** importing `_`-prefixed methods cross-module couples call sites to an implementation detail that can be renamed or inlined without warning.
