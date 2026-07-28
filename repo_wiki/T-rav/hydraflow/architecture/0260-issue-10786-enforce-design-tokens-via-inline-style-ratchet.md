---
id: 0260
topic: architecture
source_issue: 10786
source_phase: plan
created_at: 2026-07-28T09:18:05.893386+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Enforce design tokens via inline-style ratchet

Use `useTokens()` or shared UI primitives exclusively in operator console components; never use `style={{...}}` literals or raw color literals. The `src/ui/src/operator/__tests__/no-inline-style.ratchet.test.js` file strictly enforces this. New components like `WorkflowConfigPanel.jsx` must be written token-first.

**Why:** Prevents the ratchet test from failing late in development and avoids visual drift from the established design system.
