---
id: 1208
topic: gotchas
source_issue: 10829
source_phase: plan
created_at: 2026-07-31T01:09:02.057433+00:00
status: active
corroborations: 1
---

# docs/adr/ is STRUCTURAL (fail-open), not self-modification

Do not promote `docs/adr/` to self-modification in `judge_independence.py` `_SELF_MOD_SUBSTRINGS`. It is currently STRUCTURAL (fail-open, ledgered).

- Promoting it would make every ADR-touching PR fail closed.
- Self-modification scope is limited to the instrument's own code (e.g. `src/setpoint/`, `src/setpoint_erosion_loop.py`).

**Why:** ADRs are routinely edited by humans; fail-closed on every ADR PR would block normal development with no independent-verifier path.
