---
id: 0224
topic: architecture
source_issue: 10592
source_phase: plan
created_at: 2026-07-26T03:33:58.716480+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Header.jsx colors must come from theme.js tokens, never hardcoded hex

State→style maps in `src/ui/src/components/Header.jsx` (e.g. the dot color map replacing `dotConnected`/`dotDisconnected` near L490-498) must source colors exclusively from `theme.js` tokens like `theme.green`/`theme.yellow`/`theme.red` — never inline hex values, even for one-off variants like a dimmed disconnected state.

**Why:** hardcoded hex bypasses the theme system, breaking future re-theming and creating drift between components that should visually agree.
