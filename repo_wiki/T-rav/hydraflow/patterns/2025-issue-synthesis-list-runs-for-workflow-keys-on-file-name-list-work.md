---
id: 2025
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T18:39:31.780851+00:00
status: superseded
corroborations: 1
supersedes: 1917
superseded_by: 2141
---

# list_runs_for_workflow keys on file name; list_workflow_runs on display name

`PRPort.list_runs_for_workflow` matches the workflow **file name** slot (e.g. `rc-promotion-scenario.yml`) and accepts a numeric run ID. `PRPort.list_workflow_runs` projects the **display name** slot (e.g. `RC Promotion Scenario`) verbatim.

Example: `ports.py` and `pr_manager.py` docstrings must each name which identifier their read keys on. Querying `list_runs_for_workflow` with a display name returns `[]` plus one WARNING. See also: [patterns] — FakeGitHub tracks workflow display name and file name separately.

**Why:** Without documented key-slot pairing, callers pass the wrong identifier type and get silent empty results or false matches.
