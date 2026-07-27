---
id: 0542
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:44:03.246817+00:00
status: superseded
corroborations: 1
supersedes: 0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522
superseded_by: 0550
---

# Cloud `/code-review ultra` has no programmatic entry point

The cloud ultra review tier is client-side, user-triggered, and separately billed — nothing in `src/` can launch it. The reachable equivalent for headless dispatch is the locally-installed `code-review` plugin command (`commands/code-review.md`: 5 parallel reviewers + Haiku confidence scoring, drop <80), spawnable through the same seam `ReviewPhase._build_post_verify_runner` uses (`agent_cli.build_agent_command` + `BaseRunner._execute`).

**Why:** prevents re-researching this dead end when a future feature wants to invoke cloud-tier review programmatically — it can't; build on the local-plugin path instead.
