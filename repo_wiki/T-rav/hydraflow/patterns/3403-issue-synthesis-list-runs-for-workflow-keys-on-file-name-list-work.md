---
id: 3403
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T08:05:57.834078+00:00
status: superseded
corroborations: 1
supersedes: 3266
superseded_by: 3550
---

# list_runs_for_workflow keys on file name; list_workflow_runs on display

`PRPort.list_runs_for_workflow` matches the workflow **file name** slot (e.g. `rc-promotion-scenario.yml`) and accepts a numeric run ID. `PRPort.list_workflow_runs` projects the **display name** slot (e.g. `RC Promotion Scenario`) verbatim.

Example: `ports.py` and `pr_manager.py` docstrings must each name which identifier their read keys on. See also: [patterns] — FakeGitHub tracks workflow display name and file name separately.

**Why:** Without documented key-slot pairing, callers pass the wrong identifier type and get silent empty results or false matches.
