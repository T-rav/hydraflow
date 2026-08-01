---
id: 1381
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:16:20.897041+00:00
status: superseded
corroborations: 1
supersedes: 1307
superseded_by: 1460
---

# list_runs_for_workflow keys on file name; list_workflow_runs on display name

`PRPort.list_runs_for_workflow` matches the workflow **file name** slot (e.g. `rc-promotion-scenario.yml`) and accepts a numeric run ID. `PRPort.list_workflow_runs` projects the **display name** slot (e.g. `RC Promotion Scenario`) verbatim.

Example: `ports.py` and `pr_manager.py` docstrings must each name which identifier their read keys on. Querying `list_runs_for_workflow` with a display name returns `[]` plus one WARNING naming the namespace mistake, mirroring live GitHub's 404.

**Why:** Without documented key-slot pairing, callers pass the wrong identifier type and get silent empty results or false matches.
