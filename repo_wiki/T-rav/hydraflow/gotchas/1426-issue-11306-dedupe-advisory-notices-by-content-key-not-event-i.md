---
id: 1426
topic: gotchas
source_issue: 11306
source_phase: plan
created_at: 2026-08-16T05:13:33.717391+00:00
status: active
corroborations: 1
---

# Dedupe advisory notices by content key, not event id

Use a content-derived key for advisory notice deduplication and dismissal: `${source}|${epic_number ?? issue ?? ''}|${message}`. Never use the event `id`. `EpicMonitorLoop` republishes the identical alert every `epic_monitor_interval`, so an id-keyed dismissal resurrects on the next tick. Implemented in `src/ui/src/utils/notices.js` `noticeKey(data)`. **Why:** Id-keyed dismissal causes dismissed stale-epic notices to reappear every monitor cycle, retraining operators to ignore the bell.
