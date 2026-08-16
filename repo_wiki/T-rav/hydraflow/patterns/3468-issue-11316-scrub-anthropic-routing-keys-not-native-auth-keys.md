---
id: 3468
topic: patterns
source_issue: 11316
source_phase: plan
created_at: 2026-08-16T07:49:06.673197+00:00
status: superseded
corroborations: 1
superseded_by: 3614
---

# Scrub anthropic routing keys, not native auth keys

`make_clean_env` in `src/subprocess_util.py` must scrub ambient routing keys (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`) to prevent host leaks, but must preserve native auth (`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`).

Example: Define `HARNESS_ROUTING_ENV_KEYS` strictly for routing. Do not include native auth keys in this tuple.

**Why:** Endpoint selection must stay sanctioned via `resolve_harness_env`, but native auth tokens are still required for the CLI spawn to function.
