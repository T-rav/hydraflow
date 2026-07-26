---
id: 0226
topic: architecture
source_issue: 10583
source_phase: plan
created_at: 2026-07-26T02:28:58.639387+00:00
status: active
corroborations: 1
---

# Border-shorthand + longhand collision causes silent React style bugs

Inline style objects that mix the `border` shorthand with a per-side longhand (e.g. `borderLeft`) in the same object trigger React's `validateShorthandPropertyCollisionInDev` warning and can silently drop the longhand's effect. Found live in `src/ui/src/components/StreamCard.jsx` (`cardActive/InactiveStyleMap` spread under `styles.card`) and in `sectionHeaderStyles` (`src/ui/src/styles/sectionStyles.js`). Fix by building styles through a shared `src/ui/src/styles/borders.js` helper that emits only longhands, zeroing unused sides explicitly.

**Why:** the collision is easy to reintroduce via style-map spreads, and the bug is invisible until a dev-mode console warning or a visual regression appears.
