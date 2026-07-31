---
id: 1914
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T06:59:06.454380+00:00
status: active
corroborations: 1
supersedes: 1809
---

# Derive test personas from preflight.playbooks.get_playbook

Personas in `tests/fixtures/prompts/fakes.py` must call `preflight.playbooks.get_playbook` to obtain their block text. Duplicating playbook prose into fakes creates a silent rot vector: the playbook changes, the fake does not, and tests pass against a stale world.

**Why:** Duplicated prose decouples test fixtures from the source of truth, so coverage ratchets validate against an imaginary prompt rather than the real one.
