---
id: 1442
topic: gotchas
source_issue: 11329
source_phase: plan
created_at: 2026-08-16T09:40:01.182547+00:00
status: active
corroborations: 1
---

# ADR-0092 spawns: restricted= kwarg gates bypassPermissions

Any agent spawn whose prompt interpolates attacker-authored issue text (title/body) must pass `restricted=` to `build_agent_command(...)`, not blanket `bypassPermissions`.

- `src/reviewer.py:ReviewRunner._build_command` and `src/acceptance_criteria.py:AcceptanceCriteriaGenerator._build_command` use `restricted=not self._config.agent_unrestricted_tools`.
- Restricted mode swaps `bypassPermissions` for `acceptEdits` + an `--allowedTools` allowlist and unions WebFetch/WebSearch into the disallow list (does not replace existing `disallowed_tools`).

**Why:** ADR-0092 §2 defines issue text as outside the trust boundary; blanket `bypassPermissions` on those spawns is the defect class this amendment closes.
