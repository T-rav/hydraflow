---
id: 1049
topic: gotchas
source_issue: 10582
source_phase: plan
created_at: 2026-07-26T02:05:19.449750+00:00
status: active
corroborations: 1
---

# Don't add `## ` headings to repo_wiki gotcha entries

In `repo_wiki/<slug>/gotchas/*.md`, adding a `## ` heading flips the file into `parse_topic_page` shape instead of the flat tracked-entry shape, changing how the compiler classifies and reads it. A `json:entry` block should sit directly under the existing prose, with no heading introduced above it.

**Why:** The parser dispatches on structural shape (heading presence), so an incidental heading silently changes which code path processes the file.
