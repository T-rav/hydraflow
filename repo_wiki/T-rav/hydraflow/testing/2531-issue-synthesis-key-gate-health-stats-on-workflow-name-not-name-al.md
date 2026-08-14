---
id: 2531
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.022007+00:00
status: active
corroborations: 1
supersedes: 2342
---

# Key gate-health stats on (workflow, name), not name alone

`tally_job_stats` and downstream `find_born_broken`/`find_uncorrelated_blame`/`find_suspected_hangs` paths in `gate_health_loop.py` must key check identity on `(workflow, name)`. Same-named checks in different workflows are distinct gates.

Example: `Scenario Tests` passing under `CI` and failing 4× under `RC Promotion Scenario` yields no finding with name-only keying; tuple keying yields a born-broken finding.

**Why:** Name-only keying collapses a genuinely broken workflow-scoped gate into a passing one and silences the detector.
