# ADR-0082 — Untrusted-text trust boundary for agent prompts

**Status:** Accepted
**Date:** 2026-05-29
**Enforced by:** tests/test_untrusted_text.py, tests/test_preflight_untrusted_fencing.py, tests/test_agent_cli.py, tests/test_agent_advanced.py

## Context

HydraFlow assembles prompts for autonomous, highly-privileged subprocess agents out of text that an external, untrusted party can author: GitHub issue titles/bodies/comments, Sentry event text, repo-wiki entries (untrusted on foreign managed repos), and issue-derived plans. On a public repo, anyone who can open *or comment on* an issue controls this text.

Before this ADR there was **no trust boundary**:

- The implementer (`src/agent.py`) interpolated the raw issue title, body, and discussion comments into its prompt as bare f-string substitutions, then ran the agent with `claude -p --permission-mode bypassPermissions` and **no** `--disallowedTools` (codex/gemini ran with `danger-full-access` / `yolo`). With Bash, Write, and WebFetch available, a crafted issue could make the implementer exfiltrate the repo, `curl | sh` a payload, weaken or delete tests so a backdoor passes CI, or modify CI/branch-protection — unattended, for days. The prompt even primes the agent to "always commit" and "never conclude no work is needed."
- The auto-agent (`src/preflight/runner.py`) interpolated issue body + comment/wiki/Sentry/commit blocks into its escalation prompt via `str.format()` with no delimiting, and its envelope's path restrictions are explicitly honor-system (defeated by the same injection).

This is the highest-blast-radius gap for lights-off operation on attacker-reachable input (audit findings PI-01..PI-07).

## Decision

Establish a single, explicit trust boundary for untrusted text, with two layers:

1. **Fencing (primary defence).** `src/untrusted_text.py` provides `fence_untrusted(label, text)`, which wraps untrusted regions in `<untrusted_{label}> … </untrusted_{label}>` tags and **de-fangs any forged delimiter** inside the content so it cannot break out of the fence. A standing `UNTRUSTED_DATA_PREAMBLE` is emitted once near the top of each prompt, instructing the agent to treat everything inside an `<untrusted_*>` block strictly as DATA and to never follow instructions, tool directives, or "ignore previous instructions" requests found there — even if the text claims to be from the operator or the system. Applied at the implementer prompt (title/body/comments) and the auto-agent envelope (body + comment/wiki/Sentry/commit blocks). System-generated regions (escalation context, prior attempts) are not fenced.

2. **Runtime tool restriction on issue-derived spawns (defence-in-depth).** `build_agent_command(restricted=True)`, applied at the `base_runner._build_command` chokepoint (implementer, HITL, auto-agent), replaces the blanket `bypassPermissions` with `--permission-mode acceptEdits` + an explicit `--allowedTools` allowlist, and **disallows `WebFetch`/`WebSearch`** — the agent's built-in network-egress/exfiltration surface. Codex switches to its network-blocked `workspace-write` sandbox (a real egress block for that backend). Operators can revert via `config.agent_unrestricted_tools` (default `False`) if the allowlist breaks a backend.

Trusted, non-issue spawns (planner/reviewer/triage, which override `_build_command`) are unaffected and keep the unrestricted command.

## Consequences

- **Injection no longer silently steers the agent.** Fenced untrusted text is labelled and the agent is told not to obey it; break-out via forged delimiters is neutralised and regression-tested.
- **The easy exfiltration path is closed.** `WebFetch`/`WebSearch` are disallowed on issue-derived spawns; codex gets a real network block.
- **Bash remains allowed** because the implementer must run git/tests/build. A determined payload could therefore still attempt egress via `Bash` (e.g. `curl`, `python -c`). **An airtight egress block requires a container-level network policy** on the agent runtime (`Dockerfile.agent` / the sandbox network namespace). That is the remaining piece for full lights-off safety and is tracked as follow-up work, not delivered here.
- **The claude `--allowedTools` allowlist is unit-tested for command shape but not yet validated against a live implementer run.** If the allowlist omits a tool the implementer genuinely needs (e.g. a specific MCP tool), that tool is denied in headless mode; the `agent_unrestricted_tools` escape hatch exists for fast revert while the allowlist is tuned.
- **Remaining interpolation sites.** The implementer and auto-agent (the highest-privilege paths) are fenced. Other sites that interpolate untrusted text (triage, sensor/Sentry enrichment, wiki ingest — PI-03..07) should adopt the same `fence_untrusted` helper; they are lower-privilege and tracked as follow-up.
- Amends ADR-0032 (per-repo wiki): wiki content read into auto-agent prompts is now treated as untrusted (stored-injection surface on foreign repos).
