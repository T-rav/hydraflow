---
id: 0236
topic: architecture
source_issue: 10616
source_phase: plan
created_at: 2026-07-26T11:05:04.471672+00:00
status: active
corroborations: 1
---

# Build phase lives in src/implement_phase.py, not _phase.py

When an issue references "the phase file" for build work, verify the actual module. `_phase.py` is the review phase; build logic lives in `src/implement_phase.py`. However, the build *prompt seam* is in `src/agent.py` at `_build_tdd_subagent_plan`, not in either phase module.

**Why:** The naming collision between `_phase.py` and `implement_phase.py` causes planners to target the wrong file, and the prompt-shaping seam is in `agent.py`, not the phase modules themselves.
