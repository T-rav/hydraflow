---
id: 0151
topic: architecture
source_issue: 10306
source_phase: plan
created_at: 2026-07-24T03:48:07.536867+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Shared UI formatters go in utils/*.js with no underscore-prefixed exports

When two components need the same formatter/color-map (e.g. outcome badges shared between a panel and a card), extract to a new `src/ui/src/utils/*.js` module and export everything without a `_` prefix, rather than importing one component's internals into another.

Example: `src/ui/src/utils/outcomeFormat.js` exports `formatCompact`, `formatDuration`, `estimateSavedTokens`, `extractRepoSlug`, `statusStyle`, `OUTCOME_COLORS` for use by both `IssueHistoryPanel.jsx` and `OutcomeCard.jsx`.

**Why:** `_`-prefixed names signal "private" and importing them cross-component risks circular imports between sibling component files.
