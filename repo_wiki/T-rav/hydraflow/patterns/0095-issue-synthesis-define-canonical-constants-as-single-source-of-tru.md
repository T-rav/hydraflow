---
id: 0095
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:07:53.436462+00:00
status: active
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
---

# Define canonical constants as single source of truth for label lists

Establish a canonical constant (e.g., `ALL_LIFECYCLE_LABEL_FIELDS`) and derive every label list from it; never duplicate the list inline.

Example: reset code, validators, and display logic all reference `ALL_LIFECYCLE_LABEL_FIELDS` — no magic strings.

**Why:** Duplicated label lists diverge silently; a canonical constant makes omissions a grep-findable gap, not a runtime miss.
