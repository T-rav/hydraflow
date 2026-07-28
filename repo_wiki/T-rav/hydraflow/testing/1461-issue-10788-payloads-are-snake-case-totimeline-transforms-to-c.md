---
id: 1461
topic: testing
source_issue: 10788
source_phase: plan
created_at: 2026-07-28T09:50:57.002376+00:00
status: active
corroborations: 1
---

# Payloads are snake_case; toTimeline transforms to camelCase rows

Backend payloads must use snake_case keys; `timeline.js` `extractDiff` (`timeline.js:134`) reads them directly and `toTimeline` projects them to camelCase timeline rows.

- Emit `commit_sha`, `files_changed` — not `commitSha`, `filesChanged`.
- A scenario test driving real `timeline.js` under node (ESM-hook harness, `shutil.which("node")`-guarded) validates the full transform.

**Why:** The UI reads specific key names with no normalization layer; a case mismatch produces silently missing data with no error.
