---
id: 0308
topic: architecture
source_issue: 11106
source_phase: plan
created_at: 2026-08-14T07:39:28.346512+00:00
status: active
corroborations: 1
---

# Route machine-generated prompt text through fence_untrusted (ADR-0092)

Any prompt block containing stderr excerpts, issue-derived text, or inspector output must pass through `fence_untrusted` before insertion into a playbook template like `prompts/auto_agent/trust-loop-anomaly.md`.

- Applies to `render_blocks`/`render_prompt` in `src/preflight/runner.py`
- Covers `sublabel_extras` content populated by `src/preflight/context.py`

**Why:** Without the untrusted-text boundary, injected content can break prompt structure or smuggle instruction-level content past the trust perimeter.
