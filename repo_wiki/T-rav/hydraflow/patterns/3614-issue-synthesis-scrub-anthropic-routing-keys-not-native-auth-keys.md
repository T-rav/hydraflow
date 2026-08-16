---
id: 3614
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T12:13:23.421032+00:00
status: superseded
corroborations: 1
supersedes: 3468
superseded_by: 3759
---

# Scrub anthropic routing keys, not native auth keys

`make_clean_env` in `src/subprocess_util.py` must scrub ambient routing keys (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`) to prevent host leaks, but must preserve native auth (`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`).

Example: Define `HARNESS_ROUTING_ENV_KEYS` strictly for routing. Do not include native auth keys in this tuple.

**Why:** Endpoint selection must stay sanctioned via `resolve_harness_env`, but native auth tokens are still required for the CLI spawn to function.
