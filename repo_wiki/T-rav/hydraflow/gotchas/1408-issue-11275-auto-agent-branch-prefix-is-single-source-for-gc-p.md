---
id: 1408
topic: gotchas
source_issue: 11275
source_phase: plan
created_at: 2026-08-15T20:45:30.666479+00:00
status: active
corroborations: 1
---

# AUTO_AGENT_BRANCH_PREFIX is single source for GC prefix

Use `config.AUTO_AGENT_BRANCH_PREFIX` (no leading underscore on import) as the single source for both the `_BRANCH_GC_PREFIXES` inventory tuple and the `_AGENT_BRANCH_RE` regex in `src/branch_gc_scan.py`.

Example: `^(?:agent/issue-|{re.escape(AUTO_AGENT_BRANCH_PREFIX)})(\d+)$` in the regex; `AUTO_AGENT_BRANCH_PREFIX` as a tuple entry. No `agent/auto-agent-` literals in `src/`.

**Why:** Avoids drift between regex and inventory; cross-module `_`-prefixed imports cause `ImportError` when the constant is not re-exported.
