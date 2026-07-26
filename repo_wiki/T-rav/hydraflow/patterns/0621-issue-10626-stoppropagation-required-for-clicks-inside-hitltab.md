---
id: 0621
topic: patterns
source_issue: 10626
source_phase: plan
created_at: 2026-07-26T11:57:17.619550+00:00
status: active
corroborations: 1
---

# stopPropagation required for clicks inside HITLTable expandable rows

Any click handler rendered inside a HITLTable detail `<td>` must call `event.stopPropagation()` — the row's own `onClick` collapses the detail row and unmounts whatever overlay was just opened.

Example: the `ImageLightbox` thumbnail click in `HITLTable.jsx` Visual Evidence cards stops propagation or the zoom appears to do nothing (overlay unmounts the same tick it opens).

**Why:** Without propagation control, opening a lightbox inside an expandable row silently no-ops because the row collapses underneath it.
