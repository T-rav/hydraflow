---
id: 0271
topic: architecture
source_issue: 10858
source_phase: plan
created_at: 2026-07-31T01:20:45.119635+00:00
status: active
corroborations: 1
---

# Declare harness-consumed artifacts as static-text, never fabricate a src reader

`.claude/agents/*.md` has no Python builder. Do not invent a src module to make it look like a builder target. Instead, add a static-text render branch in `scripts/audit_prompts.py:render_target` that reads the file and strips YAML frontmatter.

State in ADR-0116 §11 that the Claude Code harness is the consumer.

**Why:** A fictional consumer misrepresents the system's architecture and creates a maintenance burden for code that does not exist in production.
