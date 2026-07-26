---
id: 0568
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:20:36.864217+00:00
status: active
corroborations: 1
supersedes: 0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0542,0543,0544,0545,0546,0547,0548,0549
---

# Cloud `/code-review ultra` has no programmatic entry point

The cloud ultra review tier is client-side, user-triggered, and separately billed — nothing in `src/` can launch it. The reachable equivalent for headless dispatch is the locally-installed `code-review` plugin command (`commands/code-review.md`: 5 parallel reviewers + Haiku confidence scoring, drop <80), spawnable through the same seam `ReviewPhase._build_post_verify_runner` uses (`agent_cli.build_agent_command` + `BaseRunner._execute`).

**Why:** prevents re-researching this dead end when a future feature wants to invoke cloud-tier review programmatically — it can't; build on the local-plugin path instead.
