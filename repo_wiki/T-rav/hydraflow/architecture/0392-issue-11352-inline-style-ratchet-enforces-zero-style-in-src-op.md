---
id: 0392
topic: architecture
source_issue: 11352
source_phase: plan
created_at: 2026-08-16T14:31:03.716425+00:00
status: active
corroborations: 1
---

# Inline-style ratchet enforces zero style={{}} in src/operator/**

Any new component under `src/ui/src/operator/` must use `useTokens()` + named style objects — no `style={{…}}` literals, no hex/rgb colors.

- Enforced by `operator/__tests__/no-inline-style.ratchet.test.js`, which gates `src/operator/**` at zero inline styles.
- `ResyncChip.jsx` and all new operator components must comply.

**Why:** The ratchet test fails the build on any inline style addition, blocking merge of non-compliant components.
