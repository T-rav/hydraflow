---
id: 0644
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:03:14.315419+00:00
status: active
corroborations: 1
supersedes: 0602
---

# Cloud /code-review ultra has no programmatic entry point

The cloud ultra review tier is client-side, user-triggered, and separately billed — nothing in `src/` can launch it. The reachable equivalent for headless dispatch is the locally-installed `code-review` plugin command (`commands/code-review.md`: 5 parallel reviewers + Haiku confidence scoring, drop <80).

Example: Spawn through the same seam `ReviewPhase._build_post_verify_runner` uses (`agent_cli.build_agent_command` + `BaseRunner._execute`).

**Why:** Prevents re-researching this dead end when a future feature wants to invoke cloud-tier review programmatically — it can't; build on the local-plugin path instead.
