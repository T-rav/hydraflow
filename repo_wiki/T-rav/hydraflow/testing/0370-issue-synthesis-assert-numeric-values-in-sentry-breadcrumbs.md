---
id: 0370
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:25:25.508157+00:00
status: active
corroborations: 1
supersedes: 0295,0296,0297,0298,0299,0300,0301,0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333
---

# Assert numeric values in Sentry breadcrumbs

When testing Sentry integration, assert actual numeric values in breadcrumbs and metrics, not just that a key exists.

Example: `assert breadcrumb['data']['latency_ms'] == 42`

**Why:** Key-presence assertions pass even when values are wrong or zero; numeric value assertions catch metric miscalculation bugs that presence checks miss entirely.
