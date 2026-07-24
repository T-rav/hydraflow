---
id: 0641
topic: gotchas
source_issue: 10444
source_phase: plan
created_at: 2026-07-24T10:56:36.678104+00:00
status: active
corroborations: 1
---

# ADR citation regex is `.py`-only; `.js::` cites are inert, not bugs

`adr_index._SOURCE_FILE_CITATION_RE` only matches `.py` source paths, so a malformed cite like `constants.js::…` (as seen on ADR-0049 line 76) is simply ignored rather than mis-parsed — it's dead weight in the doc, not a drift-gate blind spot, and doesn't need fixing alongside `.py::` repoints. When repointing double-colon citations, only touch `.py::` spans; leave non-Python extension citations as-is. **Why:** avoids scope creep on doc-fix PRs — conflating inert `.js` cites with the load-bearing `.py::` bug wastes review cycles on a non-issue.
