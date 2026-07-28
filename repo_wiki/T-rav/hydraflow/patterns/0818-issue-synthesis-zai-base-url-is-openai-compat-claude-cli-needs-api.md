---
id: 0818
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T12:54:49.521345+00:00
status: superseded
corroborations: 1
supersedes: 0762
superseded_by: 0873
---

# zai_base_url is OpenAI-compat; claude CLI needs /api/anthropic

Do not reuse `zai_base_url` for claude-CLI-at-z.ai routing. It targets `/api/paas/v4` (OpenAI-compat) for one-shot HTTP backends. Use a separate `credit_fallback_base_url` field defaulting to the `/api/anthropic` Anthropic-compat path.

Example: `credit_fallback_base_url` defaults to the `/api/anthropic` path for claude CLI routing.

**Why:** Prevents wrong API shape that breaks `stream-json` parsing and `tool_use` event emission silently.
