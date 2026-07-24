---
id: 0361
topic: gotchas
source_issue: 10290
source_phase: plan
created_at: 2026-07-22T17:18:40.189893+00:00
status: superseded
corroborations: 1
superseded_by: 0370
---

# Mirror park_issue with a *_infra variant when the failure needs a distinct comment

Rather than branching inside `park_issue` (`src/phase_utils.py`), add a sibling `park_issue_infra(prs, issue_number, *, parked_label, error)` that posts a distinct "## Parked: Triage Infrastructure Failure" comment carrying the actual error text plus an HTML marker like `<!-- triage-infra-park -->`. This fixes the generic "(no original parking reason captured)" fallback comment for infra-caused parks in `triage_phase.py`.

**Why:** keeping cause-specific parking logic in dedicated functions (rather than conditionals in one function) keeps the marker/comment contract auditable per park reason and easy to grep for in issue history.
