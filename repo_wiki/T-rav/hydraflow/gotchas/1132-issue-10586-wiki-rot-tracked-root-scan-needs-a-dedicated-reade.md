---
id: 1132
topic: gotchas
source_issue: 10586
source_phase: plan
created_at: 2026-07-26T02:51:38.701735+00:00
status: active
corroborations: 1
---

# wiki-rot tracked-root scan needs a dedicated reader, not parse_topic_page

`parse_topic_page` (for `docs/wiki/` compiled pages) fabricates a spurious entry when pointed at `repo_wiki/<owner>/<repo>/<topic>/` per-entry files: a tracked body with both a `## Heading` and an embedded ` ```json:entry ` block gets split wrong — verified on `repo_wiki/T-rav/hydraflow/gotchas/0832-*.md`. `WikiRotDetectorLoop._load_wiki_entries` (src/wiki_rot_detector_loop.py) must add a separate tracked branch backed by the existing private tracked frontmatter reader in `src/repo_wiki.py`, not an added `rglob` root reusing the topic-page parser.

**Why:** reusing the topic-page parser on tracked files silently invents entries, generating false shipped-claim/broken-cite findings against a topic that doesn't really exist.
