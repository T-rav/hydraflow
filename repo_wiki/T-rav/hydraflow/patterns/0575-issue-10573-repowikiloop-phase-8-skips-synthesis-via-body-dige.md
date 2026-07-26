---
id: 0575
topic: patterns
source_issue: 10573
source_phase: plan
created_at: 2026-07-26T00:55:00.255761+00:00
status: active
corroborations: 1
---

# RepoWikiLoop Phase 8 skips synthesis via body digest, not entry count

`RepoWikiLoop`'s Phase 8 (`_lint_and_compile_repos` in `src/repo_wiki_loop.py`) gated re-synthesis on active-entry *count*, so a stable 5-entry topic still called `compile_topic_tracked` and minted new ids every tick. Fix (#10573): `src/wiki_synthesis_fingerprint.py` digests active entry **bodies** only (ids/timestamps excluded, sorted, multiplicity preserved) keyed `repo/topic`; equal digest → skip. New: `load_tracked_active_entries` (public wrapper in `src/repo_wiki.py`), config `repo_wiki_synthesis_skip_unchanged` (bool, default True) and `repo_wiki_synthesis_fingerprint_ttl_hours` (int, 168) in `src/config.py`.

**Why:** count never changes for a stable topic even when content edits occur, so a count-based gate can't detect "nothing changed" and always re-synthesizes.
