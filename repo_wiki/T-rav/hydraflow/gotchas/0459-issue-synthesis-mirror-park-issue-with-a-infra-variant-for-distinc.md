---
id: 0459
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.387729+00:00
status: active
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
---

# Mirror park_issue with a *_infra variant for distinct park comments

Rather than branching inside `park_issue` (`src/phase_utils.py`), add a sibling `park_issue_infra(prs, issue_number, *, parked_label, error)` that posts a distinct "## Parked: Triage Infrastructure Failure" comment carrying the actual error text plus an HTML marker like `<!-- triage-infra-park -->`. This fixes the generic "(no original parking reason captured)" fallback comment for infra-caused parks in `triage_phase.py`.

**Why:** keeping cause-specific parking logic in dedicated functions (rather than conditionals in one function) keeps the marker/comment contract auditable per park reason and easy to grep for in issue history.
