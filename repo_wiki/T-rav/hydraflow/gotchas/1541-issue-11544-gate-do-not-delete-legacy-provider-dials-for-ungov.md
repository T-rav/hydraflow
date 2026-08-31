---
id: 1541
topic: gotchas
source_issue: 11544
source_phase: plan
created_at: 2026-08-30T15:37:21.169311+00:00
status: active
corroborations: 1
---

# Gate, do not delete, legacy provider dials for ungoverned repos

Gate legacy model-selection dials (`apply_repo_provider`, `apply_credit_failover`) on governance status rather than deleting them outright. If a repo is not in `gateway_governed_repos`, these dials must still rewrite `--model` for failover or provider switching.

Example: In `src/credit_failover.py` and `src/repo_backend.py`, wrap dial logic in an `if not is_governed(repo)` block so ungoverned repos remain byte-identical.

**Why:** Deleting these dials breaks ungoverned repos and the failover switch-back probe, as only governed repos route through the `PolicyWorkspace`.
