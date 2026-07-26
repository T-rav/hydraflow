---
id: 1006
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:48:37.245923+00:00
status: superseded
corroborations: 1
supersedes: 0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895,0896,0897,0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0932,0933,0934,0935,0936,0937,0938,0939
superseded_by: 1039
---

# escape.detect gates bug-issue class on false_close.has_skip_regression

Gate only the `bug-issue` branch of `_classify` in `src/escape/detect.py` on the repo's existing `false_close.has_skip_regression` helper. A commit whose body carries `Skip-Regression:` declares itself behaviour-neutral, so it must not be recorded as a post-merge escape.

- Import the public helper (no leading underscore) rather than copying its regex — it's already the shared P10.6/P10.7 signature and stays pure/git-free.
- Apply the gate only to `bug-issue`: reverts and hotfixes carrying the same trailer must still be recorded as escapes, or the opt-out silences real defects.

**Why:** an over-broad gate above the precedence chain silences real reverts/hotfixes; a copied regex risks drifting from the canonical one.
