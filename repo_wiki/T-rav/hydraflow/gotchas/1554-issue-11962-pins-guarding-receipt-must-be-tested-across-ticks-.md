---
id: 1554
topic: gotchas
source_issue: 11962
source_phase: review
created_at: 2026-09-01T11:05:21.597094+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Pins guarding `_receipt` must be tested across ticks to catch over-reporting

A pin that gates reporting inside `_run_one` can over-report when it fires across multiple ticks. Always test the pin's behavior across at least two ticks, not just a single invocation.

- Pre-fix: pin fires on every tick → over-reports.
- Post-fix: pin fires correctly → reports once.

**Why:** Single-tick tests cannot distinguish a pin that fires correctly from one that over-reports on subsequent ticks, so the over-reporting bug passes undetected until production.
