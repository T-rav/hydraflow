---
id: 0227
topic: architecture
source_issue: 10569
source_phase: plan
created_at: 2026-07-26T03:51:14.084320+00:00
status: active
corroborations: 1
---

# MockWorld orchestrator helpers need a public wrapper, not a cross-module `_` import

`tests/scenarios/fakes/mock_world.py` exposes orchestrator construction via a private `_build_wired_orchestrator`; new scenario tests (e.g. `test_shutdown_convergence_scenario.py`) must add a public `build_orchestrator()` that delegates to it rather than importing the underscore-prefixed helper directly from another module.
**Why:** consistent with the repo-wide rule against cross-module `_`-prefixed imports — see [[repo_wiki_cross_module_underscore_wrapper]] and [[repo_wiki_public_accessor_required_cross_module]] for the same pattern elsewhere in the codebase.
