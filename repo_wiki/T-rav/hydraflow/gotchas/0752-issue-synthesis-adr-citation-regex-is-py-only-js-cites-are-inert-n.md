---
id: 0752
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.906683+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# ADR citation regex is `.py`-only; `.js::` cites are inert, not bugs

`adr_index._SOURCE_FILE_CITATION_RE` only matches `.py` source paths, so a malformed cite like `constants.js::…` (as seen on ADR-0049 line 76) is simply ignored rather than mis-parsed — it's dead weight in the doc, not a drift-gate blind spot, and doesn't need fixing alongside `.py::` repoints.

Example: when repointing double-colon citations, only touch `.py::` spans; leave non-Python extension citations as-is.

**Why:** Avoids scope creep on doc-fix PRs — conflating inert `.js` cites with the load-bearing `.py::` bug wastes review cycles on a non-issue.
