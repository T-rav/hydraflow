---
id: 2746
topic: testing
source_issue: 11418
source_phase: plan
created_at: 2026-08-18T03:42:49.483141+00:00
status: active
corroborations: 1
---

# Record contract cassettes from real gh api output

Generate contract cassettes for `PRPort` parity tests from real GitHub API output, not from `FakeGitHub` state. Cassettes in `tests/trust/contracts/cassettes/github/` define the expected shape that `src/mockworld/fakes/fake_github.py` must satisfy.

**Why:** Recording cassettes from the fake creates circular parity checks, masking real API drift and breaking the contract gate.
