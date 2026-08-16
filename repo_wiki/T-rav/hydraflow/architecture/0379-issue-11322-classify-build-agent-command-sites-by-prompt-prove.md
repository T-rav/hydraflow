---
id: 0379
topic: architecture
source_issue: 11322
source_phase: plan
created_at: 2026-08-16T09:00:07.880228+00:00
status: active
corroborations: 1
---

# Classify build_agent_command sites by prompt provenance, not module name

When auditing the ~16 `build_agent_command(` call sites in `src/`, classify each by whether the prompt interpolates issue-derived text — not by whether the module name sounds safe.

Issue-derived (must harden): prompt carries issue title/body/comments/CI logs/agent transcript.
Trusted (exempt): prompt is fully synthetic or operator-authored.

Ambiguous sites requiring explicit decision:
- `src/agent.py:1273` (skill verifier: `issue_title` + diff)
- `src/implement_spec_reviewer.py:355` (`issue_body`)

If a site is exempt, record why in the ADR paragraph; if not exempt, harden it.

**Why:** Module names like `implement_spec_reviewer` sound trusted but interpolate `issue_body`; only prompt-content analysis determines the trust boundary.
