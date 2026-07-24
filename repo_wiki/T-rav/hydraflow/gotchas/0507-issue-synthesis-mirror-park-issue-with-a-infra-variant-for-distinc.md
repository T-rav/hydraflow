---
id: 0507
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.780188+00:00
status: active
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
---

# Mirror park_issue with a *_infra variant for distinct park comments

Rather than branching inside `park_issue` (`src/phase_utils.py`), add a sibling `park_issue_infra(prs, issue_number, *, parked_label, error)` that posts a distinct "## Parked: Triage Infrastructure Failure" comment carrying the actual error text plus an HTML marker like `<!-- triage-infra-park -->`.

Example: fixes the generic "(no original parking reason captured)" fallback comment for infra-caused parks in `triage_phase.py`.

**Why:** Keeping cause-specific parking logic in dedicated functions keeps the marker/comment contract auditable per park reason and easy to grep for in issue history.
