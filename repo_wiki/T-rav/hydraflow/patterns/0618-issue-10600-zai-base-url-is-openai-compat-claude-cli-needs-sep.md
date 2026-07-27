---
id: 0618
topic: patterns
source_issue: 10600
source_phase: plan
created_at: 2026-07-26T12:25:53.446771+00:00
status: superseded
corroborations: 1
superseded_by: 0660
---

# zai_base_url is OpenAI-compat; claude CLI needs separate /api/anthropic

Do not reuse `zai_base_url` for claude-CLI-at-z.ai routing. It targets `/api/paas/v4` (OpenAI-compat) for one-shot HTTP backends. Use a separate `credit_fallback_base_url` field defaulting to the `/api/anthropic` Anthropic-compat path. **Why:** Prevents wrong API shape that breaks `stream-json` parsing and `tool_use` event emission silently.
