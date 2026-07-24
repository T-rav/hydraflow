---
id: 0383
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:12:12.388919+00:00
status: active
corroborations: 1
supersedes: 0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369
---

# Mirror park_issue with a *_infra variant when the failure needs a distinct comment

Rather than branching inside `park_issue` (`src/phase_utils.py`), add a sibling `park_issue_infra(prs, issue_number, *, parked_label, error)` that posts a distinct "## Parked: Triage Infrastructure Failure" comment carrying the actual error text plus an HTML marker like `<!-- triage-infra-park -->`. This fixes the generic "(no original parking reason captured)" fallback comment for infra-caused parks in `triage_phase.py`.

**Why:** keeping cause-specific parking logic in dedicated functions (rather than conditionals in one function) keeps the marker/comment contract auditable per park reason and easy to grep for in issue history.
