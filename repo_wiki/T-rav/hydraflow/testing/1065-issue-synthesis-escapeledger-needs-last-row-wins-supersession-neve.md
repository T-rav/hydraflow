---
id: 1065
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.551654+00:00
status: superseded
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
superseded_by: 1085
---

# EscapeLedger needs last-row-wins supersession, never in-place rewrites

EscapeLedger (src/escape/ledger.py) is append-only. Reaching a terminal state (e.g. encoded_as: detector + regression-test) means appending a new row for the same id, never rewriting the original line.

Example: derived readers must collapse to the latest row per id — src/escape/metrics.py and src/escape_ledger_loop.py's _render_reports/_surface_findings all need the same latest-per-id read. existing_ids() must still contain the id exactly once after supersession, so a re-tick doesn't re-record.

**Why:** the ledger's append-only guarantee preserves audit-trail integrity; in-place rewrites would erase false-positive history.
