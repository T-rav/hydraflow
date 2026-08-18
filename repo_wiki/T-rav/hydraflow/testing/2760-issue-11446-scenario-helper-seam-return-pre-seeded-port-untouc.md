---
id: 2760
topic: testing
source_issue: 11446
source_phase: plan
created_at: 2026-08-18T09:14:02.932553+00:00
status: active
corroborations: 1
---

# Scenario helper seam: return pre-seeded port untouched before constructing

Scenario-port helpers (e.g. `_scenario_dedup`, `_scenario_github_cache` in `loop_registrations.py`) must check `ports.get(port_key)` first and return it untouched if already set.

- Scenarios that seed their own stateful fake or pre-populated store (e.g. `wiki_rot_detector`, `per_loop_cost`, `adr_conformance`) keep working.
- Only construct the default when the port is absent.

**Why:** Overwriting a scenario-seeded port with a fresh default silently discards the test's intended state, producing false greens.
