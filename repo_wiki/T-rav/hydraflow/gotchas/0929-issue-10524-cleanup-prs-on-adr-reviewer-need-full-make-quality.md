---
id: 0929
topic: gotchas
source_issue: 10524
source_phase: plan
created_at: 2026-07-25T07:08:18.759719+00:00
status: superseded
corroborations: 1
superseded_by: 0940
---

# Cleanup PRs on ADR reviewer need full make quality, not file subsets

For the `ADRCouncilReviewer` signature cleanup (#10524), the testing strategy explicitly runs the full `make quality` gate rather than the targeted files (`tests/test_adr_reviewer.py`, `tests/test_adr_reviewer_loop.py`, `tests/scenarios/test_caretaker_loops.py`, etc.) alone, per the CLAUDE.md rule that cleanup PRs (defensive-guard/dead-code removal) are not verified with file-targeted subsets.

**Why:** PR #8460 over-pruned dead-looking guards and shipped on a green targeted-file run, missing 7 failures in `tests/test_audit_prompts.py`/`tests/test_repo_wiki_loop_pr.py` that only full `make quality` caught.
