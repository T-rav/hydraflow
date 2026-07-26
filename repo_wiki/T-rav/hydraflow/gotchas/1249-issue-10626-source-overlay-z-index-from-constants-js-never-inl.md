---
id: 1249
topic: gotchas
source_issue: 10626
source_phase: plan
created_at: 2026-07-26T11:57:17.619577+00:00
status: active
corroborations: 1
---

# Source overlay z-index from constants.js, never inline literals

Use `src/ui/src/constants.js` for z-index values shared across overlays. The `ReportIssueModal` overlay sits at `zIndex:1000`; any new overlay (e.g. `ImageLightbox`) must import a constant that exceeds it.

- Don't inline a literal in the new component.
- The lightbox z-index must be > 1000 to render above the report modal.

**Why:** A hardcoded lower/equal z-index renders the zoom behind the modal — a stacking bug invisible in unit tests that only surfaces when both overlays coexist.
