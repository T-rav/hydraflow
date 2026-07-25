---
id: 0915
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.769921+00:00
status: active
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
---

# Verification subprocess timeout should scale to the make-tier, not a fixed 120s

A hardcoded 120s subprocess timeout in agent bash calls is too short for scenario/browser verification and causes false-positive reaps. Add `agent_bash_timeout_secs` to `src/config.py` (make-tier default) and inject it as env into `stream_claude_process` in `src/runner_utils.py`, with explicit config overrides winning. Old state files must still load unchanged after this config addition.

**Why:** a fixed short timeout kills legitimate long-running verification mid-run, which is what caused issue #10493's stranded-PR bug in the first place.
