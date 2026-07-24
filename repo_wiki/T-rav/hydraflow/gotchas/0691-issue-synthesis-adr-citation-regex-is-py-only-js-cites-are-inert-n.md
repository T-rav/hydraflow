---
id: 0691
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.490125+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
---

# ADR citation regex is `.py`-only; `.js::` cites are inert, not bugs

`adr_index._SOURCE_FILE_CITATION_RE` only matches `.py` source paths, so a malformed cite like `constants.js::…` (as seen on ADR-0049 line 76) is simply ignored rather than mis-parsed — it's dead weight in the doc, not a drift-gate blind spot, and doesn't need fixing alongside `.py::` repoints.

Example: when repointing double-colon citations, only touch `.py::` spans; leave non-Python extension citations as-is.

**Why:** Avoids scope creep on doc-fix PRs — conflating inert `.js` cites with the load-bearing `.py::` bug wastes review cycles on a non-issue.
