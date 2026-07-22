---
id: 0305
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:37:54.866281+00:00
status: active
corroborations: 1
supersedes: 0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294,0295,0296,0297,0298,0299,0300,0301
---

# Define canonical constants for label lists as single source of truth

Establish a canonical constant (e.g., `ALL_LIFECYCLE_LABEL_FIELDS`) and derive every label list from it; never duplicate the list inline.

Example: Reset code, validators, and display logic all reference `ALL_LIFECYCLE_LABEL_FIELDS` — no magic strings.

**Why:** Duplicated label lists diverge silently; a canonical constant makes omissions a grep-findable gap, not a runtime miss.
