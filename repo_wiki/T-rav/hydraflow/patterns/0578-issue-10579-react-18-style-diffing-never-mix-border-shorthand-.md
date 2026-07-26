---
id: 0578
topic: patterns
source_issue: 10579
source_phase: plan
created_at: 2026-07-26T01:24:12.531309+00:00
status: active
corroborations: 1
---

# React 18 style diffing: never mix `border` shorthand with `borderLeft` longhand

React 18's `setValueForStyles` only writes *changed* style keys on rerender. If an object drops `borderLeft` while keeping `border` (StreamCard.jsx's `cardActiveStyleMap`/`cardInactiveStyleMap` did this at ~382-394), the removed key is cleared (`style.borderLeft = ''`) but `border` doesn't repaint it — the left edge silently renders `none` plus a dev-console shorthand-collision warning. Fix by expressing all four sides as longhands (`borderTop`/`borderRight`/`borderBottom`/`borderLeft`) so every style-map branch has an identical key set. Same latent bug existed in `sectionStyles.js`'s `sectionHeaderStyles`.

**Why:** shorthand+longhand mixing across conditionally-merged style objects (`{...styles.card, ...(cardStageStyle || {})}`) is invisible in a single render and only breaks on the second rerender's diff.
