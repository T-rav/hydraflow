---
id: 0547
topic: patterns
source_issue: 10564
source_phase: plan
created_at: 2026-07-25T23:31:13.809570+00:00
status: active
corroborations: 1
---

# React border shorthand+longhand mix triggers dev console errors on rerender

Never spread a `border` shorthand (e.g. `border: '1px solid X'`) and then override with a longhand (`borderColor`, `borderWidth`, `borderTop*`, etc.) in the same inline style object — React 18 dev builds log a style-conflict console error when the same DOM node rerenders with both keys present, as seen in `Header.jsx`'s `controlBtnDisabled` (:526) and `pipelineStageStylesMap` (:493). Fix by normalizing to longhand-only (`borderWidth`/`borderStyle`/`borderColor`) so variants change a value, not a key.

**Why:** it only reproduces on a same-element rerender (e.g. `connected` toggling the shared control button), so it's easy to miss in manual testing and silently ships.
