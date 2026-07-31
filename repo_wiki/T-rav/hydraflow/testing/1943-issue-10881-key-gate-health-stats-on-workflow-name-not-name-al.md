---
id: 1943
topic: testing
source_issue: 10881
source_phase: plan
created_at: 2026-07-31T07:22:08.358163+00:00
status: active
corroborations: 1
---

# Key gate-health stats on (workflow, name), not name alone

Rule: `tally_job_stats` and the downstream `find_born_broken`/`find_uncorrelated_blame`/`find_suspected_hangs` paths in `gate_health_loop.py` must key check identity on `(workflow, name)`. Same-named checks in different workflows are distinct gates.

Example:
- `Scenario Tests` passing under `CI` and failing 4× under `RC Promotion Scenario`: today yields no finding (name collides); with the tuple key yields a born-broken finding for the RC one.
- Two same-named checks must produce two distinct dedup fingerprints.
- Fingerprint shape changes → `.hydraflow/dedup/gate_health_findings.json` entries refile once; state this in the PR body.

**Why:** Name-only keying collapses a genuinely broken workflow-scoped gate into a passing one and silences the detector. `gate_health_run_window` is a run count — don't rename it, operators set the env.
