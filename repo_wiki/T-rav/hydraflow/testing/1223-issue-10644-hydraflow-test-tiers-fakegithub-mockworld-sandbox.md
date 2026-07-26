---
id: 1223
topic: testing
source_issue: 10644
source_phase: plan
created_at: 2026-07-26T12:01:31.012812+00:00
status: active
corroborations: 1
---

# Hydraflow test tiers: FakeGitHub, MockWorld, sandbox

Three test tiers, each with a strict scope:

- **Regression** (`tests/regressions/`): drives the real loop against `FakeGitHub`, extracts rendered commands, invokes `scripts/resolve_escape.py:main` against a tmp ledger. No subprocess/git/gh.
- **Scenario** (`tests/scenarios/`): MockWorld fakes only — no subprocess, git, or `gh` calls.
- **Sandbox e2e** (`tests/sandbox_scenarios/`): docker wiring only; delegates surfacing behaviour to the MockWorld tier.

`make quality` runs all tiers. A fix touching a shared render path must extend coverage at every relevant tier.

**Why:** Skipping a tier leaves a close path unverified at that abstraction level; the sandbox tier's docstring explicitly delegates surfacing logic downward.
