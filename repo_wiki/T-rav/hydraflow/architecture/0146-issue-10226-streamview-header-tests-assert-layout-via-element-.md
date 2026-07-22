---
id: 0146
topic: architecture
source_issue: 10226
source_phase: plan
created_at: 2026-07-22T04:13:06.288095+00:00
status: stale
corroborations: 1
stale_reason: source issue #10226 closed
---

# StreamView/Header tests assert layout via element.style.<prop>, not snapshot/CSS-class

`src/ui/src/components/__tests__/StreamView.test.jsx` and `Header.test.jsx` verify inline-style layout properties directly on the rendered DOM node (e.g. `element.style.alignItems === 'flex-start'`) located via `data-testid`, rather than snapshotting or checking CSS module class names. Follow this idiom for any new inline-style regression test in these files — it matches existing conventions and works because these components use inline theme-token styles, not CSS modules.

**Why:** keeps regression tests resilient to markup/class churn while still catching the exact style-token regression (e.g. `alignItems` flipping back to `center`).
