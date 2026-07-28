---
id: 1148
topic: testing
source_issue: 10592
source_phase: plan
created_at: 2026-07-26T03:33:58.716466+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Header.jsx status dot: encode state via aria-label/title, not visible text, with data-testid anchor

When a status indicator drops its plain-text label (e.g. removing the raw `orchestratorStatus` string from `Header.jsx`), the non-visual state carrier becomes `aria-label`/`title` on the indicator element — these become required assertions, not optional ones, once text is gone. Anchor the element with a stable `data-testid` (e.g. `data-testid="orchestrator-status"`) plus `role="img"` so tests target one element deterministically instead of matching removed text.

**Why:** removing visible text without asserting the aria-label/title in tests silently regresses the accessibility contract with no visual signal.
