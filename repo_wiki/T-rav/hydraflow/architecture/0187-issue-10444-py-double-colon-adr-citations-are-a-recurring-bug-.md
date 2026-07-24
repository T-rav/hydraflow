---
id: 0187
topic: architecture
source_issue: 10444
source_phase: plan
created_at: 2026-07-24T10:56:36.678094+00:00
status: active
corroborations: 1
---

# `.py::` double-colon ADR citations are a recurring bug class (#9514, #10440, #10444)

The malformed `.py::Symbol` citation typo has recurred at least three times: #9514 (original), #10440 (same ADR-0049 line 74), and #10444 (lines 74 & 75). Each recurrence silently disabled the ADR-drift gate for the cited module until caught manually. The #10444 fix adds a permanent guard: `tests/architecture/test_adr_no_double_colon_citations.py` scans all live (Accepted/Proposed) ADR bodies for backtick `src/*.py::Symbol` spans and fails the build if any exist, with a synthetic-fixture negative case. **Why:** without a static guard, this class of typo is invisible until someone notices a module isn't covered by drift detection — the guard converts a silent runtime miss into a build-time failure.
