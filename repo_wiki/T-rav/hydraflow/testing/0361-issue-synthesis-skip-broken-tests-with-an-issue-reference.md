---
id: 0361
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:25:25.502793+00:00
status: active
corroborations: 1
supersedes: 0295,0296,0297,0298,0299,0300,0301,0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333
---

# Skip broken tests with an issue reference

Mark broken tests with a referenced issue, never a bare skip. Remove the skip immediately after the issue is resolved.

Example: `@pytest.mark.skip(reason="documenting bug: #1234")`

**Why:** Without an issue reference, skipped tests become permanent dead weight with no path to removal or triage.
